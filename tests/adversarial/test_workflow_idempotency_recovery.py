"""Workflow request idempotency and fail-closed crash recovery.

The test suite uses only disposable SQLite with no live tool calls. PostgreSQL
tests independently verify cross-worker advisory-lock serialization.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.goals_tasks
import apps.api.models.decision_evidence
import apps.api.models.agent_council
import apps.api.models.memory
import apps.api.models.integrations
from apps.api.models.workflow import WorkflowDefinition, WorkflowRun, AuditLog
from apps.api.services.workflow_engine import workflow_engine


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def workflow(db, biz="tenant-a"):
    wf = WorkflowDefinition(
        business_id=biz, name="Synthetic deterministic job",
        nodes=[{"id": "start", "type": "trigger", "data": {}}],
        edges=[], is_valid=True
    )
    db.add(wf)
    db.commit()
    return wf


def test_retry_same_key_returns_original_run_without_dispatch(db):
    wf = workflow(db)
    with patch.object(workflow_engine, "_dispatch_node_tool",
                      return_value={"triggered": True}) as dispatch:
        first = workflow_engine.execute_workflow(
            db, "tenant-a", wf.id, idempotency_key="retry_job_0001"
        )
        second = workflow_engine.execute_workflow(
            db, "tenant-a", wf.id, idempotency_key="retry_job_0001"
        )
    assert first.id == second.id
    assert db.query(WorkflowRun).count() == 1
    dispatch.assert_called_once()


def test_reusing_key_for_different_workflow_or_dry_run_fails_closed(db):
    first_workflow = workflow(db)
    second_workflow = workflow(db)
    workflow_engine.execute_workflow(
        db, "tenant-a", first_workflow.id, idempotency_key="retry_job_0002"
    )
    with pytest.raises(ValueError, match="conflicts"):
        workflow_engine.execute_workflow(
            db, "tenant-a", second_workflow.id, idempotency_key="retry_job_0002"
        )
    with pytest.raises(ValueError, match="conflicts"):
        workflow_engine.execute_workflow(
            db, "tenant-a", first_workflow.id, dry_run=True,
            idempotency_key="retry_job_0002"
        )
    assert db.query(WorkflowRun).count() == 1


@pytest.mark.parametrize("key", ["", "short", "spaces are not valid", "x" * 129, "*malformed*"])
def test_invalid_execution_idempotency_key_rejected_before_write(db, key):
    wf = workflow(db)
    with pytest.raises(ValueError, match="Invalid"):
        workflow_engine.execute_workflow(
            db, "tenant-a", wf.id, idempotency_key=key
        )
    assert db.query(WorkflowRun).count() == 0


def test_separate_tenants_can_use_identical_request_key(db):
    a = workflow(db, "tenant-a")
    b = workflow(db, "tenant-b")
    first = workflow_engine.execute_workflow(
        db, "tenant-a", a.id, idempotency_key="shared_key_0001"
    )
    second = workflow_engine.execute_workflow(
        db, "tenant-b", b.id, idempotency_key="shared_key_0001"
    )
    assert first.id != second.id
    assert db.query(WorkflowRun).count() == 2


def test_interrupted_run_is_quarantined_not_replayed(db):
    wf = workflow(db)
    run = WorkflowRun(
        workflow_id=wf.id, business_id="tenant-a", workflow_name=wf.name,
        status="running", trigger_source="manual",
        started_at=datetime.utcnow() - timedelta(hours=1),
        idempotency_key="crashed_run_0001",
        verification_details={"dry_run": False},
        step_results={"start": {"status": "started"}},
    )
    db.add(run)
    db.commit()
    with patch.object(workflow_engine, "_dispatch_node_tool") as dispatch:
        assert workflow_engine.reconcile_interrupted_runs(db, "tenant-b", 900) == 0
        assert workflow_engine.reconcile_interrupted_runs(db, "tenant-a", 900) == 1
        assert workflow_engine.reconcile_interrupted_runs(db, "tenant-a", 900) == 0
        retry = workflow_engine.execute_workflow(
            db, "tenant-a", wf.id, idempotency_key="crashed_run_0001"
        )
    assert retry.id == run.id
    assert retry.status == "paused"
    assert retry.verified_success is False
    dispatch.assert_not_called()
    assert db.query(WorkflowRun).count() == 1
    assert db.query(AuditLog).filter_by(
        action="quarantine_interrupted_workflow"
    ).count() == 1


def test_recent_execution_remains_running_during_reconciliation(db):
    wf = workflow(db)
    db.add(WorkflowRun(
        workflow_id=wf.id, business_id="tenant-a", workflow_name=wf.name,
        status="running", started_at=datetime.utcnow(),
    ))
    db.commit()
    assert workflow_engine.reconcile_interrupted_runs(db, "tenant-a", 300) == 0
    assert db.query(WorkflowRun).filter_by(status="running").count() == 1


@pytest.mark.parametrize("age", [-1, 1, 299, 86401])
def test_manual_reconciliation_rejects_unsafe_age(db, age):
    with pytest.raises(ValueError, match="Recovery"):
        workflow_engine.reconcile_interrupted_runs(db, "tenant-a", age)
