"""Durable opt-in daily/weekly IANA timezone schedules.

A nonexistent DST wall time is skipped, an ambiguous wall time occurs once
at fold=0. Missed slots coalesce into one execution; an uncertain running
checkpoint pauses the schedule instead of replaying external actions.
"""
import hashlib
import re
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from sqlalchemy import text
from apps.api.models.operations import WorkflowSchedule
from apps.api.models.workflow import WorkflowDefinition
from apps.api.services.durable_jobs import execution_lock,_key,_now
from apps.api.services.workflow_engine import workflow_engine

DAYS={"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}

def field(value,minimum,maximum,aliases=None):
    if value=="*":return set(range(minimum,maximum+1))
    output=set()
    for part in value.split(","):
        if aliases and part in aliases:output.add(aliases[part]);continue
        if part.startswith("*/"):
            step=int(part[2:])
            if not 1<=step<=maximum-minimum+1:raise ValueError("Invalid cron interval")
            output.update(range(minimum,maximum+1,step));continue
        if "-" in part:
            low,high=map(int,part.split("-"))
            if not minimum<=low<=high<=maximum:raise ValueError("Invalid cron range")
            output.update(range(low,high+1));continue
        n=int(part)
        if not minimum<=n<=maximum:raise ValueError("Invalid cron value")
        output.add(n)
    return output


def parse(cron,zone):
    if not isinstance(cron,str) or len(cron)>80 or len(zone)>64:
        raise ValueError("Invalid cron or timezone")
    try:
        minute,hour,dom,month,dow=cron.split()
        if dom!="*" and dow!="*":raise ValueError("Specify day of month OR weekday, not both")
        minutes=field(minute,0,59)
        # Bound frequency to at most 12 slots/hour.
        if len(minutes)>12 or any(b-a<5 for a,b in zip(sorted(minutes),sorted(minutes)[1:])):
            raise ValueError("Schedule interval must be at least five minutes")
        if len(minutes)>1 and 60-max(minutes)+min(minutes)<5:raise ValueError("Schedule interval must be at least five minutes")
        return minutes,field(hour,0,23),field(dom,1,31),field(month,1,12),field(dow,0,6,DAYS),ZoneInfo(zone)
    except (ValueError,TypeError,ZoneInfoNotFoundError):
        raise ValueError("Invalid cron: use five fields, minimum five-minute frequency and one day selector") from None


def next_slot(cron,zone,after):
    minutes,hours,dom,months,days,tz=parse(cron,zone)
    start=datetime.fromtimestamp(after,timezone.utc).astimezone(tz).date()
    for offset in range(1462):
        d=start+timedelta(days=offset)
        if d.month not in months or d.day not in dom or d.weekday() not in days:continue
        for hour in sorted(hours):
            for minute in sorted(minutes):
                local=datetime(d.year,d.month,d.day,hour,minute,tzinfo=tz,fold=0)
                instant=local.timestamp()
                back=datetime.fromtimestamp(instant,tz)
                if back.replace(tzinfo=None)==local.replace(tzinfo=None) and instant>after:return instant
    raise ValueError("No valid next schedule occurrence within four years")

def configure(db,tenant,wid,cron,zone,enabled,now=None,missed_policy="coalesce"):
    if missed_policy not in ("coalesce","skip","catch_up"):raise ValueError("Invalid missed-run policy")
    now=_now(db) if now is None else now
    due=next_slot(cron,zone,now)
    if db.get_bind().dialect.name=="postgresql":
        if not db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"),{"key":_key("workflow-schedule:"+wid)}).scalar_one():
            raise ValueError("Schedule is currently executing; retry after completion")
    wf=db.query(WorkflowDefinition).filter_by(id=wid,business_id=tenant,is_active=True,is_valid=True).first()
    if not wf:
        raise ValueError("Workflow missing, inactive or invalid")
    row=db.get(WorkflowSchedule,wid)
    if row and row.business_id!=tenant:
        raise ValueError("Workflow missing")
    if row is None:
        row=WorkflowSchedule(workflow_id=wid,business_id=tenant)
        db.add(row)
    row.cron,row.timezone,row.enabled,row.next_due_at=cron,zone,enabled,due
    row.last_status="configured"
    row.coalesced=False
    row.missed_policy=missed_policy
    row.missed_count=0
    db.commit()
    return serialize(row)

def serialize(row):
    return {key:getattr(row,key) for key in ("workflow_id","cron","timezone","enabled","next_due_at","last_run_id","last_status","coalesced","missed_policy","missed_count")}

def run_due(db,tenant,now=None,limit=20):
    now=_now(db) if now is None else now
    ids=[r[0] for r in db.query(WorkflowSchedule.workflow_id).filter(
        WorkflowSchedule.business_id==tenant,WorkflowSchedule.enabled.is_(True),
        WorkflowSchedule.next_due_at<=now).order_by(WorkflowSchedule.next_due_at,WorkflowSchedule.workflow_id).limit(limit).all()]
    db.rollback()
    completed=0
    failures=0
    for wid in ids:
        with execution_lock(db.get_bind(),"workflow-schedule:"+wid) as acquired:
            if not acquired:
                continue
            try:
                row=db.query(WorkflowSchedule).filter_by(workflow_id=wid,business_id=tenant,enabled=True).first()
                if row is None or row.next_due_at>now:
                    db.rollback()
                    continue
                slot=row.next_due_at
                cron,zone=row.cron,row.timezone
                try:
                    next_due=next_slot(cron,zone,now)
                    coalesced=next_slot(cron,zone,slot)<=now
                except ValueError:
                    row.enabled=False
                    row.last_status="invalid_schedule"
                    db.commit()
                    failures+=1
                    continue
                wf=db.query(WorkflowDefinition).filter_by(id=wid,business_id=tenant,is_active=True,is_valid=True).first()
                if wf is None:
                    row.enabled=False
                    row.last_status="inactive_workflow"
                    db.commit()
                    continue
                policy=row.missed_policy or "coalesce"
                if policy=="skip" and coalesced:
                    row.last_status="missed_skipped"
                    row.missed_count=(row.missed_count or 0)+1
                    row.next_due_at=next_due
                    db.commit();continue
                if policy=="catch_up":
                    # Replay one oldest slot per scheduler pass, bounded by queue limit.
                    next_due=next_slot(cron,zone,slot)
                key="scheduled_"+hashlib.sha256(f"{tenant}:{wid}:{slot:.0f}".encode()).hexdigest()
                run=workflow_engine.execute_workflow(db,tenant,wid,trigger_source="schedule",idempotency_key=key)
                row=db.query(WorkflowSchedule).filter_by(workflow_id=wid,business_id=tenant).first()
                if row is None:
                    db.rollback()
                    continue
                row.last_run_id=run.id
                row.last_status=run.status
                if run.status in ("running","pending","paused","failed","awaiting_approval"):
                    # Require the founder to review or resolve before future dispatch.
                    row.enabled=False
                row.coalesced=coalesced and policy=="coalesce"
                if row.coalesced:row.missed_count=(row.missed_count or 0)+1
                row.next_due_at=next_due
                db.commit()
                completed+=1
            except Exception:
                db.rollback()
                failures+=1
                # Preserve due slot for stable-id retry. A committed running
                # checkpoint returns without dispatch; then pauses the schedule.
                import logging
                logging.getLogger(__name__).error("Scheduled workflow attempt failed")
    if failures:
        raise RuntimeError('One or more scheduled workflow attempts failed')
    return completed
