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

def parse(cron,zone):
    match=re.fullmatch(r"(\d{1,2}) (\d{1,2}) \* \* (\*|mon|tue|wed|thu|fri|sat|sun)",cron)
    if not match or len(zone)>64:
        raise ValueError("Use daily/weekly cron: minute hour * * * or mon..sun")
    minute,hour,day=match.groups()
    if not 0<=int(minute)<=59 or not 0<=int(hour)<=23:
        raise ValueError("Invalid schedule time")
    try:
        tz=ZoneInfo(zone)
    except (ZoneInfoNotFoundError,ValueError):
        raise ValueError("Unknown IANA timezone") from None
    return int(minute),int(hour),day,tz

def next_slot(cron,zone,after):
    minute,hour,day,tz=parse(cron,zone)
    start=datetime.fromtimestamp(after,timezone.utc).astimezone(tz).date()
    for offset in range(15):
        d=start+timedelta(days=offset)
        if day!="*" and d.weekday()!=DAYS[day]:
            continue
        local=datetime(d.year,d.month,d.day,hour,minute,tzinfo=tz,fold=0)
        instant=local.timestamp()
        back=datetime.fromtimestamp(instant,tz)
        if back.replace(tzinfo=None)!=local.replace(tzinfo=None):
            continue
        if instant>after:
            return instant
    raise ValueError("No valid next schedule occurrence")

def configure(db,tenant,wid,cron,zone,enabled,now=None):
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
    db.commit()
    return serialize(row)

def serialize(row):
    return {key:getattr(row,key) for key in ("workflow_id","cron","timezone","enabled","next_due_at","last_run_id","last_status","coalesced")}

def run_due(db,tenant,now=None,limit=10):
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
                row.coalesced=coalesced
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
