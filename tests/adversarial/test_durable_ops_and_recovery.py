"""Durable operations and recovery with synthetic tenant data only."""
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.goals_tasks
import apps.api.models.agent_council
import apps.api.models.decision_evidence
import apps.api.models.memory
import apps.api.models.workflow
import apps.api.models.integrations
import apps.api.models.operations
from apps.api.models.business import Business
from apps.api.models.entities import Customer, Invoice
from apps.api.models.operations import AlertSnapshot, LocalCustomerImport
from apps.api.models.workflow import WorkflowRun, WorkflowDefinition
import apps.api.services.scheduler_service as scheduler_module
from apps.api.services.customer_csv_import import parse_customer_csv, import_customer_csv
from apps.api.services.workflow_engine import workflow_engine
from scripts.operations.test_encrypted_restore import require_disposable_restore


@pytest.fixture
def db_factory(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scheduler_module, "SessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()


def test_alert_status_and_history_persist_after_restart(db_factory):
    tenant, other = str(uuid4()), str(uuid4())
    with db_factory() as db:
        db.add_all([Business(id=tenant, name="Synthetic A", currency="AED"),
                    Business(id=other, name="Synthetic B")])
        db.add(Invoice(business_id=tenant, invoice_number="DRILL-1",
                       customer_name="Synthetic", amount=13.25,
                       due_date=datetime.utcnow(), status="overdue"))
        db.commit()
    one = scheduler_module.SchedulerService()
    assert len(one.get_alerts(tenant)) == 1
    one.get_alerts(tenant)
    two = scheduler_module.SchedulerService()
    history = two.get_alert_history(tenant)
    assert len(history) == 1
    assert history[0]["is_active"] is True
    assert "AED 13.25" in history[0]["title"]
    assert two.get_alert_history(other) == []
    with db_factory() as db:
        assert db.query(AlertSnapshot).filter_by(business_id=tenant).count() == 1
        db.query(Invoice).filter_by(business_id=tenant).update({"status": "paid"})
        db.commit()
    assert two.get_alerts(tenant) == []
    resolved = two.get_alert_history(tenant)
    assert len(resolved) == 1
    assert resolved[0]["is_active"] is False
    assert resolved[0]["resolved_at"] is not None


@pytest.mark.parametrize("bad_csv", [
    "", "name,mrr\nAlice,-1\n", "name,mrr\nAlice,nan\n",
    "name,mrr\nAlice,inf\n", "name,mrr\nAlice,12.345\n",
    "name,mrr,status\nAlice,2,unknown\n",
    "name,name,mrr\nAlice,Bob,3\n",
    "name,mrr,unexpected\nAlice,3,value\n",
    "name,mrr\nAlice,3,additional\n",
    "name,mrr\n",
])
def test_csv_parser_rejects_invalid_input_before_database_mutation(bad_csv):
    with pytest.raises(ValueError):
        parse_customer_csv(bad_csv)


def test_csv_preview_import_and_retry_are_durable_and_tenant_scoped(db_factory):
    csv_text = "name,mrr,status\nTest Alice,32.50,active\nTest Bob,0,churned\n"
    tenant, other = str(uuid4()), str(uuid4())
    with db_factory() as db:
        preview = import_customer_csv(db, tenant, csv_text, "test_batch_0001", dry_run=True)
        assert preview["written"] is False
        assert db.query(Customer).count() == 0
        done = import_customer_csv(db, tenant, csv_text, "test_batch_0001", dry_run=False)
        assert done["rows_imported"] == 2
        again = import_customer_csv(db, tenant, csv_text, "test_batch_0001", dry_run=False)
        assert again["status"] == "already_imported"
        assert done["customer_ids"] == again["customer_ids"]
        assert db.query(Customer).filter_by(business_id=tenant).count() == 2
        assert db.query(LocalCustomerImport).filter_by(business_id=tenant).count() == 1
        with pytest.raises(ValueError, match="already used"):
            import_customer_csv(db, tenant, csv_text + "\n", "test_batch_0001", dry_run=False)
        # Another workspace is entirely independent, even with the same key.
        imported = import_customer_csv(db, other, csv_text, "test_batch_0001", dry_run=False)
        assert imported["rows_imported"] == 2
        assert db.query(Customer).filter_by(business_id=other).count() == 2
        assert db.query(LocalCustomerImport).filter_by(business_id=other).count() == 1


def test_crash_persists_workflow_checkpoint_before_tool_dispatch(db_factory):
    tenant = str(uuid4())
    with db_factory() as db:
        wf = WorkflowDefinition(
            business_id=tenant, name="Synthetic interrupted workflow",
            is_valid=True,
            nodes=[{"id": "start", "type": "trigger", "data": {}}],
            edges=[],
        )
        db.add(wf)
        db.commit()
        workflow_id = wf.id
    with db_factory() as db:
        with patch.object(workflow_engine, "_dispatch_node_tool",
                          side_effect=KeyboardInterrupt("synthetic crash")) as tool:
            with pytest.raises(KeyboardInterrupt):
                workflow_engine.execute_workflow(
                    db, tenant, workflow_id, idempotency_key="crash_batch_0001"
                )
            tool.assert_called_once()
    # A different DB session and worker sees a durable 'running' record.
    with db_factory() as db:
        run = db.query(WorkflowRun).filter_by(business_id=tenant).one()
        assert run.status == "running"
        assert run.verification_details["dry_run"] is False
        with patch.object(workflow_engine, "_dispatch_node_tool") as no_replay:
            duplicate = workflow_engine.execute_workflow(
                db, tenant, workflow_id, idempotency_key="crash_batch_0001"
            )
            assert duplicate.id == run.id
            no_replay.assert_not_called()
        run.started_at = datetime.utcnow() - timedelta(hours=1)
        run.verification_details={**run.verification_details,"checkpoint_at":run.started_at.isoformat()}
        db.commit()
    with db_factory() as db:
        assert workflow_engine.reconcile_interrupted_runs(db, tenant, 900) == 1
        assert db.query(WorkflowRun).filter_by(business_id=tenant).one().status == "paused"


def test_restore_drill_never_targets_existing_or_remote_customer_database(tmp_path):
    secret = tmp_path / "age-key.txt"
    secret.write_text("synthetic private key placeholder")
    secret.chmod(0o600)
    with pytest.raises(RuntimeError, match="approval"):
        require_disposable_restore({
            "ONEBOARD_RESTORE_SCRATCH_URL":
                "postgresql+psycopg://ci:synthetic@localhost/oneboard_restore_drill",
        }, secret)
    with pytest.raises(RuntimeError, match="exact local disposable"):
        require_disposable_restore({
            "ONEBOARD_RESTORE_DRILL_APPROVED": "YES",
            "ONEBOARD_RESTORE_SCRATCH_URL":
                "postgresql+psycopg://ci:synthetic@remote.example.test/customer_data",
        }, secret)
