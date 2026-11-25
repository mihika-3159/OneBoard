from unittest.mock import patch
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from apps.api.core.database import Base
from apps.api.models.operations import ScheduledJobLease, SideEffectOutbox
from apps.api.models.memory import MemoryDocument, MemoryChunk
from apps.api.models.workflow import WorkflowDefinition
from apps.api.services.durable_jobs import claim_job, finish_job, process_local_outbox
from apps.api.services.memory_engine import memory_engine
from apps.api.services.workflow_engine import WorkflowEngine
from apps.api.services import tenant_storage
from apps.api.core.config import settings

@pytest.fixture
def db():
    import apps.api.models.business
    import apps.api.models.entities
    import apps.api.models.goals_tasks
    import apps.api.models.decision_evidence
    import apps.api.models.agent_council
    import apps.api.models.integrations
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        yield session
    engine.dispose()

def test_lease_recovery_and_stale_worker_cannot_finish(db):
    first = claim_job(db, "synthetic", 10, now=100)
    assert first and claim_job(db, "synthetic", 10, now=109) is None
    second = claim_job(db, "synthetic", 10, now=110)
    assert second and second != first
    assert not finish_job(db, "synthetic", first, True, now=111)
    assert finish_job(db, "synthetic", second, True, now=112)
    assert claim_job(db, "synthetic", now=171) is None
    assert claim_job(db, "synthetic", now=172)
    assert db.get(ScheduledJobLease, "synthetic").attempts == 3

def test_outbox_is_transactional_and_local_only(db):
    from types import SimpleNamespace
    run = SimpleNamespace(business_id="a", id="run")
    node = {"connector": "demo_email", "operation": "draft_invoice_reminders"}
    WorkflowEngine._record_draft_intent(db, run, "draft", "action", node, {"drafts": []})
    db.flush()
    db.rollback()
    assert db.query(SideEffectOutbox).count() == 0
    WorkflowEngine._record_draft_intent(db, run, "draft", "action", node, {"drafts": []})
    db.commit()
    assert process_local_outbox(db) == 1
    assert process_local_outbox(db) == 0
    assert db.query(SideEffectOutbox).one().state == "draft_ready"

def test_storage_quota_counts_utf8_and_keeps_other_tenant_available(db, monkeypatch):
    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
    monkeypatch.setattr(tenant_storage, "MAX_TEXT_BYTES", 8)
    memory_engine.add_document_with_chunks(db, "a", "test", "éé")
    with pytest.raises(HTTPException) as denied:
        memory_engine.add_document_with_chunks(db, "a", "test", "x")
    assert denied.value.status_code == 429
    db.rollback()
    memory_engine.add_document_with_chunks(db, "b", "test", "éé")
    assert db.query(MemoryDocument).count() == 2
    assert db.query(MemoryChunk).count() == 2

def test_resource_quota_is_per_tenant(db, monkeypatch):
    monkeypatch.setitem(tenant_storage.RESOURCE_LIMITS, "workflow", (WorkflowDefinition, 1))
    tenant_storage.check_resource(db, "a", "workflow")
    db.add(WorkflowDefinition(business_id="a", name="first"))
    db.commit()
    with pytest.raises(HTTPException):
        tenant_storage.check_resource(db, "a", "workflow")
    db.rollback()
    tenant_storage.check_resource(db, "b", "workflow")
