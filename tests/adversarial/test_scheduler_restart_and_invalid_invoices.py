"""P1 monitoring: persistent records, process restarts, and failure truthfulness.

No external scheduler, network, bank connection or provider is used. These
checks use an isolated SQLite session factory and synthetic invoice records.
"""
from datetime import datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.goals_tasks
import apps.api.models.memory
import apps.api.models.workflow
import apps.api.models.agent_council
import apps.api.models.decision_evidence
import apps.api.models.integrations
from apps.api.core.config import settings
from apps.api.models.business import Business
from apps.api.models.entities import Invoice
import apps.api.services.scheduler_service as scheduler_module


@pytest.fixture
def records(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scheduler_module, "SessionLocal", factory)
    tenant_a, tenant_b = str(uuid4()), str(uuid4())
    invoice_id = str(uuid4())
    with factory() as session:
        session.add_all([
            Business(id=tenant_a, name="Synthetic A", currency="AED"),
            Business(id=tenant_b, name="Synthetic B", currency="USD"),
            Invoice(
                id=invoice_id, business_id=tenant_a,
                customer_name="Synthetic", invoice_number="CI",
                due_date=datetime.utcnow(), amount=250.75, status="overdue",
            ),
        ])
        session.commit()
    try:
        yield factory, tenant_a, tenant_b, invoice_id
    finally:
        engine.dispose()


def test_alerts_can_be_regenerated_after_process_restart_from_db(records):
    _, tenant_a, tenant_b, _ = records
    first = scheduler_module.SchedulerService()
    before = first.get_alerts(tenant_a)
    assert len(before) == 1
    assert before[0]["type"] == "receivables_overdue"
    assert "AED 250.75" in before[0]["title"]
    assert first.get_alerts(tenant_b) == []
    # Construct a completely new scheduler, with no cached memory. Alerts
    # survive as facts because the source invoices are durable DB records.
    restarted = scheduler_module.SchedulerService()
    assert restarted.active_alerts_by_business == {}
    restored = restarted.get_alerts(tenant_a)
    assert restored[0]["id"] == before[0]["id"]
    assert "AED 250.75" in restored[0]["title"]
    assert restarted.get_alerts(tenant_b) == []


def test_invalid_invoice_amount_never_generates_false_total(records):
    factory, tenant_a, tenant_b, invoice_id = records
    with factory() as db:
        invoice = db.get(Invoice, invoice_id)
        invoice.amount = -13.0
        db.commit()
    service = scheduler_module.SchedulerService()
    alerts = service.get_alerts(tenant_a)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "financial_data_quality"
    assert "250.75" not in repr(alerts)
    assert "13.00" not in repr(alerts)
    assert service.get_alerts(tenant_b) == []
    with factory() as db:
        db.get(Invoice, invoice_id).amount = 50
        db.commit()
    refreshed = service.get_alerts(tenant_a)
    assert len(refreshed) == 1
    assert refreshed[0]["type"] == "receivables_overdue"
    assert "AED 50.00" in refreshed[0]["title"]


def test_production_startup_failure_does_not_claim_active_monitoring(
    monkeypatch, caplog
):
    service = scheduler_module.SchedulerService()
    fake = Mock()
    fake.running = False
    fake.start.side_effect = RuntimeError("private-connection-string")
    service.scheduler = fake
    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
    with pytest.raises(RuntimeError, match="Required scheduler failed"):
        service.start()
    assert "private-connection-string" not in caplog.text


def test_local_development_scheduler_failure_is_logged_but_not_fatal(
    monkeypatch, caplog
):
    service = scheduler_module.SchedulerService()
    fake = Mock()
    fake.running = False
    fake.start.side_effect = RuntimeError("private-connection-string")
    service.scheduler = fake
    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", False)
    service.start()
    assert "Scheduler startup failed" in caplog.text
    assert "private-connection-string" not in caplog.text
