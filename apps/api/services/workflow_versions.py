"""Immutable workflow revision snapshots, optimistic editor conflicts and opt-in activation."""
from apps.api.models.workflow import WorkflowDefinition
from apps.api.models.operations import WorkflowRevision, WorkflowSchedule
from apps.api.services.workflow_events import activate,config_for
from apps.api.services.workflow_engine import workflow_engine
from apps.api.services.tenant_storage import _lock
from apps.api.services.workflow_effects import canonical_digest

FIELDS=("name","description","category","trigger_type","trigger_config","nodes","edges","is_active")


def snapshot(wf):
    return {key:getattr(wf,key) for key in FIELDS}


def current_version(db,tenant,wid):
    from sqlalchemy import func
    return db.query(func.max(WorkflowRevision.version)).filter_by(business_id=tenant,workflow_id=wid).scalar() or 0


def ensure_version(db,wf):
    version=current_version(db,wf.business_id,wf.id)
    if not version:
        db.add(WorkflowRevision(business_id=wf.business_id,workflow_id=wf.id,version=1,definition=snapshot(wf)))
        db.flush()
        return 1
    return version


def validate(definition):
    if not isinstance(definition.get("name"),str) or not 1<=len(definition["name"].strip())<=255:
        raise ValueError("Invalid workflow name")
    if len(str(definition.get("description") or ""))>8000:
        raise ValueError("Description exceeds limit")
    if not isinstance(definition.get("category"),str) or not 1<=len(definition["category"])<=50:
        raise ValueError("Invalid category")
    if len(str(definition.get("nodes")))+len(str(definition.get("edges")))>100000:
        raise ValueError("Workflow graph exceeds size limit")
    config_for(definition["trigger_type"],definition["trigger_config"])
    result=workflow_engine.validate_workflow(definition)
    if not result["is_valid"]:
        raise ValueError(result["error"])
    canonical_digest(definition)


def edit(db,tenant,wid,expected_version,definition=None,rollback_version=None):
    _lock(db,tenant)
    # Coordinate edits with the scheduler's session-level dispatch lock.
    from apps.api.services.durable_jobs import _key
    from sqlalchemy import text
    if db.get_bind().dialect.name=="postgresql" and not db.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"),{"key":_key("workflow-schedule:"+wid)}
    ).scalar_one():
        raise ValueError("Schedule is currently executing; retry after completion")
    wf=db.query(WorkflowDefinition).filter_by(business_id=tenant,id=wid).with_for_update().first()
    if not wf: raise ValueError("Workflow unavailable")
    current=ensure_version(db,wf)
    if current!=expected_version:
        raise ValueError("Workflow version changed; reload before editing")
    if current>=100:
        raise ValueError("Revision history limit reached")
    if rollback_version is not None:
        prior=db.query(WorkflowRevision).filter_by(business_id=tenant,workflow_id=wid,version=rollback_version).first()
        if not prior:raise ValueError("Revision unavailable")
        definition=dict(prior.definition)
        # Restoration never silently resumes automatic activity.
        definition["is_active"]=False
    validate(definition)
    for key in FIELDS:
        setattr(wf,key,definition[key])
    wf.is_valid=True
    db.add(WorkflowRevision(business_id=tenant,workflow_id=wid,version=current+1,definition=snapshot(wf)))
    # Editing a definition suspends preexisting schedules. Re-enable explicitly.
    sched=db.query(WorkflowSchedule).filter_by(business_id=tenant,workflow_id=wid).first()
    if sched:
        sched.enabled=False
        sched.last_status="definition_changed"
    db.flush()
    activate(db,wf)
    db.commit()
    return wf


def serialize(wf,version):
    return {c.name:getattr(wf,c.name) for c in WorkflowDefinition.__table__.columns}|{"version":version or 1}
