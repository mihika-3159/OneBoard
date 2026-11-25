"""Opt-in tenant event triggers, stable deduplication and fenced dead-letter queue."""
import hashlib
import json
from datetime import datetime
from math import isfinite
from uuid import uuid4
from sqlalchemy import or_,and_
from apps.api.models.workflow import WorkflowDefinition,WorkflowRun
from apps.api.models.operations import WorkflowEvent,WorkflowTriggerState
from apps.api.models.entities import Customer,Invoice
from apps.api.services.financial_metrics import calculate_business_financials
from apps.api.services.tenant_storage import _lock
from apps.api.services.durable_jobs import _now,execution_lock
from apps.api.services.workflow_effects import canonical_digest

KINDS={"new_customer","invoice_overdue","metric_threshold","webhook"}
METRICS={"mrr","monthly_burn","net_burn","cash_balance","overdue_receivables_amount","active_customers_count"}
MAX_EVENTS=10000
MAX_ATTEMPTS=3


def config_for(kind,config):
    if kind not in KINDS|{"manual","schedule"} or not isinstance(config,dict):
        raise ValueError("Unknown workflow trigger")
    if kind=="metric_threshold":
        if set(config)!={"metric","operator","threshold"} or config["metric"] not in METRICS or config["operator"] not in ("gt","gte","lt","lte"):
            raise ValueError("Invalid metric trigger")
        value=config["threshold"]
        if type(value) not in (int,float) or abs(value)>1e15 or not isfinite(value):
            raise ValueError("Invalid metric threshold")
    elif kind in KINDS and config:
        raise ValueError("Unexpected event configuration")
    return dict(config)


def fingerprint(wf):
    return canonical_digest({"nodes":wf.nodes or [],"edges":wf.edges or [],"trigger":wf.trigger_type,"config":wf.trigger_config or {}})


def activate(db,wf):
    # Only explicit create/edit opts in; old seeded trigger labels never run.
    row=db.query(WorkflowTriggerState).filter_by(business_id=wf.business_id,workflow_id=wf.id).first()
    if wf.trigger_type not in KINDS or not wf.is_active:
        if row: db.delete(row)
        return
    if not row:
        row=WorkflowTriggerState(business_id=wf.business_id,workflow_id=wf.id,config_digest=fingerprint(wf))
        db.add(row)
    row.config_digest=fingerprint(wf)
    row.activated_at=datetime.utcnow()
    row.state={}


def enqueue(db,wf,kind,identity,payload):
    if kind not in KINDS or wf.trigger_type!=kind or not wf.is_active or not wf.is_valid:
        raise ValueError("Trigger not enabled")
    if not isinstance(identity,str) or not 1<=len(identity)<=200:
        raise ValueError("Invalid event identity")
    if len(json.dumps(payload,allow_nan=False).encode())>8192:
        raise ValueError("Event payload too large")
    key=hashlib.sha256((kind+":"+identity).encode()).hexdigest()
    old=db.query(WorkflowEvent).filter_by(business_id=wf.business_id,workflow_id=wf.id,event_key=key).first()
    if old:
        if canonical_digest(old.payload)!=canonical_digest(payload):
            raise ValueError("Event ID already used for different payload")
        return old
    if db.query(WorkflowEvent).filter_by(business_id=wf.business_id).count()>=MAX_EVENTS:
        raise ValueError("Event storage exhausted; no event was accepted")
    row=WorkflowEvent(business_id=wf.business_id,workflow_id=wf.id,event_key=key,kind=kind,
                      payload=payload,definition_digest=fingerprint(wf),next_attempt_at=0)
    db.add(row);db.flush()
    return row


def active_workflows(db,tenant,kind=None):
    q=db.query(WorkflowDefinition,WorkflowTriggerState).join(WorkflowTriggerState,
      (WorkflowTriggerState.workflow_id==WorkflowDefinition.id)&(WorkflowTriggerState.business_id==WorkflowDefinition.business_id)
    ).filter(WorkflowDefinition.business_id==tenant,WorkflowDefinition.is_active.is_(True),WorkflowDefinition.is_valid.is_(True))
    if kind:q=q.filter(WorkflowDefinition.trigger_type==kind)
    return [(wf,state) for wf,state in q.order_by(WorkflowDefinition.id).limit(200) if state.config_digest==fingerprint(wf)]


def customer_created(db,tenant,customer):
    # Invoked in the same import transaction as the customer creation.
    for wf,state in active_workflows(db,tenant,"new_customer"):
        enqueue(db,wf,"new_customer",customer.id,{"customer_id":customer.id})


def webhook(db,tenant,wid,event_id,payload):
    _lock(db,tenant)
    pair=next(((wf,state) for wf,state in active_workflows(db,tenant,"webhook") if wf.id==wid),None)
    if not pair:raise ValueError("Webhook workflow unavailable")
    row=enqueue(db,pair[0],"webhook",event_id,payload)
    db.commit()
    return serialize(row)


def detect(db,tenant,now=None):
    """Bounded scans with persisted cursor; metric fires on false-to-true transition."""
    _lock(db,tenant)
    now=now or datetime.utcnow()
    for wf,state in active_workflows(db,tenant):
        kind=wf.trigger_type
        progress=dict(state.state or {})
        if kind in ("invoice_overdue","new_customer"):
            model=Invoice if kind=="invoice_overdue" else Customer
            q=db.query(model).filter(model.business_id==tenant,model.id>progress.get("cursor",""))
            if kind=="invoice_overdue":
                q=q.filter(Invoice.status.in_(["sent","overdue"]),Invoice.due_date<now)
            else:q=q.filter(Customer.created_at>=state.activated_at)
            rows=q.order_by(model.id).limit(100).all()
            for row in rows:
                if kind=="invoice_overdue":
                    enqueue(db,wf,kind,row.id+":"+row.due_date.isoformat(),{"invoice_id":row.id,"due_date":row.due_date.isoformat()})
                else:enqueue(db,wf,kind,row.id,{"customer_id":row.id})
            progress["cursor"]=rows[-1].id if len(rows)==100 else ""
        elif kind=="metric_threshold":
            values=calculate_business_financials(db,tenant)
            cfg=config_for(kind,wf.trigger_config or {})
            value=values.get(cfg["metric"])
            if values.get("financial_data_status")!="recorded" or type(value) not in (int,float) or not isfinite(value):
                continue
            threshold=cfg["threshold"]
            matched={"gt":value>threshold,"gte":value>=threshold,"lt":value<threshold,"lte":value<=threshold}[cfg["operator"]]
            if matched and not progress.get("matched"):
                seq=progress.get("sequence",0)+1
                enqueue(db,wf,kind,str(seq)+":"+state.activated_at.isoformat(),{"metric":cfg["metric"],"value":value,"threshold":threshold})
                progress["sequence"]=seq
            progress["matched"]=matched
        state.state=progress
    db.commit()


def serialize(row):
    return {k:getattr(row,k) for k in ("id","workflow_id","kind","status","attempts","run_id","error","created_at","next_attempt_at")}


def drain(db,tenant,limit=20,now=None):
    from apps.api.services.workflow_engine import workflow_engine
    now=_now(db) if now is None else now
    ids=[r[0] for r in db.query(WorkflowEvent.id).filter(WorkflowEvent.business_id==tenant,
        WorkflowEvent.next_attempt_at<=now,or_(WorkflowEvent.status=="queued",
        and_(WorkflowEvent.status=="running",WorkflowEvent.lease_until<=now))).order_by(WorkflowEvent.next_attempt_at,WorkflowEvent.id).limit(limit)]
    db.rollback()
    for ident in ids:
        with execution_lock(db.get_bind(),"workflow-event:"+ident) as held:
            if not held:continue
            row=db.query(WorkflowEvent).filter_by(business_id=tenant,id=ident).with_for_update().first()
            if not row or row.status not in ("queued","running") or row.next_attempt_at>now or (row.status=="running" and row.lease_until>now):
                db.rollback();continue
            wf=db.query(WorkflowDefinition).filter_by(business_id=tenant,id=row.workflow_id,is_active=True,is_valid=True).first()
            if row.attempts>=MAX_ATTEMPTS or not wf or fingerprint(wf)!=row.definition_digest:
                row.status="dead_letter";row.error="Retry budget exhausted or workflow changed";db.commit();continue
            token=str(uuid4());row.status="running";row.owner_token=token;row.lease_until=now+300;row.attempts+=1
            wid,kind,payload=row.workflow_id,row.kind,row.payload
            db.commit()
            try:
                run=workflow_engine.execute_workflow(db,tenant,wid,trigger_source=kind,idempotency_key="event_"+ident,
                                                     event_payload=payload)
                state="dispatched" if run.status in ("completed","awaiting_approval") else "dead_letter"
                values={"status":state,"run_id":run.id,"error":None if state=="dispatched" else "Run requires operator review"}
            except Exception:
                db.rollback()
                values={"status":"queued","next_attempt_at":now+60,"error":"Dispatch failed; retry same execution identity"}
            values.update(owner_token=None,lease_until=0)
            db.query(WorkflowEvent).filter_by(business_id=tenant,id=ident,owner_token=token).update(values,synchronize_session=False)
            db.commit()
    return len(ids)
