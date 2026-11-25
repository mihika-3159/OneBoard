"""Batch I: real durable workflow graph, approval, event and schedule regressions."""
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apps.api.core.database import Base
from apps.api.models.business import Business
from apps.api.models.entities import Customer, Invoice
from apps.api.models.workflow import WorkflowDefinition,WorkflowRun,ApprovalRequest
from apps.api.models.operations import WorkflowEvent,WorkflowRevision,SideEffectOutbox,WorkflowSchedule
from apps.api.services.workflow_engine import workflow_engine
from apps.api.services import workflow_events as events,workflow_versions as versions,workflow_schedule as schedules
from apps.api.services.customer_csv_import import import_customer_csv
from apps.api.services.workflow_effects import canonical_digest,stage_effect


@pytest.fixture
def db():
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:yield s
    engine.dispose()


def workflow(db,tenant="a",kind="manual",nodes=None,edges=None,config=None):
    row=WorkflowDefinition(business_id=tenant,name="Batch I fixture",trigger_type=kind,trigger_config=config or {},
                           nodes=nodes or [{"id":"start","type":"trigger","data":{}}],edges=edges or [],is_active=True,is_valid=True)
    db.add(row);db.flush();versions.ensure_version(db,row);events.activate(db,row);db.commit()
    return row


def test_customer_import_event_is_atomic_and_deduplicated(db):
    a=workflow(db,kind="new_customer");b=workflow(db,tenant="b",kind="new_customer")
    result=import_customer_csv(db,"a","name,mrr\nFixture,30\n","fixture-import-1",dry_run=False)
    assert result["written"]
    events.detect(db,"a")
    assert db.query(WorkflowEvent).count()==1
    assert events.drain(db,"b")==0
    assert events.drain(db,"a")==1
    event=db.query(WorkflowEvent).one()
    assert event.workflow_id==a.id and event.status=="dispatched"
    assert db.get(WorkflowRun,event.run_id).step_results["start"]["result"]["event"]["customer_id"]==result["customer_ids"][0]
    events.detect(db,"a");events.drain(db,"a")
    assert db.query(WorkflowRun).count()==1


def test_invoice_event_deduplicates_and_excludes_paid_foreign_rows(db):
    wf=workflow(db,kind="invoice_overdue")
    now=datetime.utcnow()
    for tenant,status in [("a","sent"),("a","paid"),("b","overdue")]:
        db.add(Invoice(business_id=tenant,customer_name="Fixture",invoice_number=tenant+status,amount=20,status=status,due_date=now-timedelta(days=1)))
    db.commit()
    events.detect(db,"a",now);events.detect(db,"a",now)
    row=db.query(WorkflowEvent).one()
    assert row.workflow_id==wf.id and row.kind=="invoice_overdue"


def test_metric_crossing_and_quality_gate(db):
    wf=workflow(db,kind="metric_threshold",config={"metric":"mrr","operator":"gt","threshold":100})
    def observe(value,status="recorded"):
        with patch.object(events,"calculate_business_financials",return_value={"mrr":value,"financial_data_status":status}):
            events.detect(db,"a")
    observe(150,"needs_review");assert db.query(WorkflowEvent).count()==0
    observe(150);observe(160);assert db.query(WorkflowEvent).count()==1
    observe(20);observe(200);assert db.query(WorkflowEvent).count()==2


def test_webhook_replay_and_changed_revision_dead_letter(db):
    wf=workflow(db,kind="webhook")
    first=events.webhook(db,"a",wf.id,"event-id-1",{"value":10})
    assert events.webhook(db,"a",wf.id,"event-id-1",{"value":10})["id"]==first["id"]
    with pytest.raises(ValueError):events.webhook(db,"a",wf.id,"event-id-1",{"value":11})
    db.rollback()
    with pytest.raises(ValueError):events.webhook(db,"b",wf.id,"event-id-2",{})
    db.rollback()
    versions.edit(db,"a",wf.id,1,{**versions.snapshot(wf),"name":"New version"})
    events.drain(db,"a")
    assert db.get(WorkflowEvent,first["id"]).status=="dead_letter"
    assert db.query(WorkflowRun).count()==0


def test_dead_letter_retries_stay_bounded_and_same_id(db):
    wf=workflow(db,kind="webhook");row=events.webhook(db,"a",wf.id,"event-id-2",{})
    with patch.object(workflow_engine,"execute_workflow",side_effect=RuntimeError("offline")) as execute:
        for now in (1000,1200,1500):
            events.drain(db,"a",now=now)
        e=db.get(WorkflowEvent,row["id"])
        assert e.status=="dead_letter" and e.attempts==3
        events.retry_dead_letter(db,"a",e.id)
        events.drain(db,"a",now=1800)
        assert e.status=="dead_letter" and e.attempts==4
        assert {c.kwargs["idempotency_key"] for c in execute.call_args_list}=={"event_"+e.id}
        with pytest.raises(ValueError):events.retry_dead_letter(db,"a",e.id)


def test_condition_passes_event_data_and_skips_wrong_branch(db):
    nodes=[{"id":"start","type":"trigger","data":{}},
           {"id":"branch","type":"condition","data":{"operator":"gt","right":10,"bindings":{"left":{"step":"start","field":"event.value"}}}},
           {"id":"yes","type":"trigger","data":{}},{"id":"no","type":"trigger","data":{}}]
    edges=[{"source":"start","target":"branch"},{"source":"branch","target":"yes","branch":True},{"source":"branch","target":"no","branch":False}]
    wf=workflow(db,nodes=nodes,edges=edges)
    run=workflow_engine.execute_workflow(db,"a",wf.id,event_payload={"value":20})
    assert run.status=="completed"
    assert run.step_results["branch"]["result"]["branch"] is True
    assert run.step_results["yes"]["status"]=="success"
    assert run.step_results["no"]["status"]=="skipped"


def test_approval_payload_is_bound_to_run_and_actual_draft(db):
    wf=workflow(db,nodes=[{"id":"draft","type":"action","data":{"risk":"high","connector":"demo_email","operation":"draft_invoice_reminders"}}])
    invoice=Invoice(business_id="a",customer_name="Fixture",invoice_number="invoice",amount=20,status="overdue",due_date=datetime.utcnow()-timedelta(days=1))
    db.add(invoice);db.commit()
    run=workflow_engine.execute_workflow(db,"a",wf.id)
    approval=db.query(ApprovalRequest).filter_by(workflow_run_id=run.id).one()
    assert approval.payload["effect_preview"]["drafts_created"]==1
    invoice.amount=30;db.commit()
    with pytest.raises(ValueError,match="inputs changed"):workflow_engine.approve_and_resume_run(db,run.id,approval.id,"a")
    db.rollback()
    assert db.query(SideEffectOutbox).count()==0
    invoice.amount=20;db.commit()
    original=dict(approval.payload)
    changed={**original,"effect_preview":None}
    changed["payload_digest"]=canonical_digest({k:v for k,v in changed.items() if k!="payload_digest"})
    approval.payload=changed;db.commit()
    with pytest.raises(ValueError,match="digest changed"):workflow_engine.approve_and_resume_run(db,run.id,approval.id,"a")
    db.rollback()
    approval.payload=original;db.commit()
    assert workflow_engine.approve_and_resume_run(db,run.id,approval.id,"a").status=="completed"
    assert db.query(SideEffectOutbox).count()==1


def test_interrupted_after_effect_commit_resumes_without_repeating(db):
    wf=workflow(db,nodes=[{"id":"draft","type":"action","data":{"connector":"demo_email","operation":"draft_invoice_reminders"}},
                          {"id":"later","type":"trigger","data":{}}],edges=[{"source":"draft","target":"later"}])
    original=workflow_engine._dispatch_node_tool
    def crash_later(db,tenant,node_type,data):
        if node_type=="trigger":raise KeyboardInterrupt("synthetic crash")
        return original(db,tenant,node_type,data)
    with patch.object(workflow_engine,"_dispatch_node_tool",side_effect=crash_later):
        with pytest.raises(KeyboardInterrupt):workflow_engine.execute_workflow(db,"a",wf.id,idempotency_key="crash-fixture-1")
    db.rollback();run=db.query(WorkflowRun).one()
    assert run.step_results["draft"]["status"]=="success"
    assert db.query(SideEffectOutbox).count()==1
    run.started_at=datetime.utcnow()-timedelta(hours=1)
    run.verification_details={**run.verification_details,"checkpoint_at":run.started_at.isoformat()};db.commit()
    assert workflow_engine.reconcile_interrupted_runs(db,"a",900)==1
    assert workflow_engine.recover_run(db,"a",run.id).status=="completed"
    assert db.query(SideEffectOutbox).count()==1
    with pytest.raises(ValueError):workflow_engine.recover_run(db,"b",run.id)


def test_version_rollback_creates_new_inactive_revision_and_blocks_stale_run(db):
    wf=workflow(db,nodes=[{"id":"gate","type":"approval","data":{}}])
    run=workflow_engine.execute_workflow(db,"a",wf.id)
    approval=db.query(ApprovalRequest).one()
    versions.edit(db,"a",wf.id,1,{**versions.snapshot(wf),"name":"Revision 2"})
    with pytest.raises(ValueError,match="revision changed"):workflow_engine.approve_and_resume_run(db,run.id,approval.id,"a")
    db.rollback()
    versions.edit(db,"a",wf.id,2,rollback_version=1)
    assert not wf.is_active and versions.current_version(db,"a",wf.id)==3
    assert db.query(WorkflowRevision).count()==3
    with pytest.raises(ValueError):workflow_engine.execute_workflow(db,"a",wf.id)
    db.rollback()
    assert workflow_engine.cancel_run(db,"a",run.id).status=="cancelled"
    assert approval.status=="cancelled"


def test_unknown_effect_cannot_be_staged(db):
    wf=workflow(db)
    run=workflow_engine.execute_workflow(db,"a",wf.id)
    with pytest.raises(ValueError):stage_effect(db,run,"bad","external_send",{})
    assert db.query(SideEffectOutbox).count()==0


def test_expanded_cron_and_missed_policy(db):
    epoch=lambda s:datetime.fromisoformat(s).timestamp()
    assert schedules.next_slot("0 9 1 * *","UTC",epoch("2026-11-25T00:00:00+00:00"))==epoch("2026-12-01T09:00:00+00:00")
    assert schedules.next_slot("*/15 * * * *","UTC",epoch("2026-11-25T00:00:00+00:00"))==epoch("2026-11-25T00:15:00+00:00")
    wf=workflow(db)
    due=schedules.configure(db,"a",wf.id,"0 9 * * *","UTC",True,0,missed_policy="skip")["next_due_at"]
    schedules.run_due(db,"a",now=due+3*86400)
    assert db.get(WorkflowSchedule,wf.id).last_status=="missed_skipped"
    assert db.query(WorkflowRun).count()==0
    due=schedules.configure(db,"a",wf.id,"0 9 * * *","UTC",True,0,missed_policy="catch_up")["next_due_at"]
    assert schedules.run_due(db,"a",now=due+3*86400)==1
    assert db.get(WorkflowSchedule,wf.id).next_due_at==due+86400
    assert schedules.run_due(db,"a",now=due+3*86400)==1
    assert db.query(WorkflowRun).count()==2
