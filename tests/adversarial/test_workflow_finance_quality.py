"""Ensure executable finance tools reject invalid records and tenant leaks."""
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.goals_tasks
import apps.api.models.decision_evidence
import apps.api.models.agent_council
import apps.api.models.workflow
import apps.api.models.memory
import apps.api.models.integrations
from apps.api.models.business import Business
from apps.api.models.entities import Invoice
from apps.api.models.workflow import WorkflowDefinition
from apps.api.services.workflow_engine import ToolRegistry, workflow_engine


@pytest.fixture
def records():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        a, b = str(uuid4()), str(uuid4())
        db.add_all([
            Business(id=a, name="Synthetic A"),
            Business(id=b, name="Synthetic B")
        ])
        db.flush()
        db.add_all([
            Invoice(business_id=a, customer_name="A1", invoice_number="A1",
                    status="overdue", amount=12.75, due_date=datetime.utcnow()),
            Invoice(business_id=a, customer_name="Paid", invoice_number="A2",
                    status="paid", amount=500, due_date=datetime.utcnow()),
            Invoice(business_id=b, customer_name="Private", invoice_number="B1",
                    status="overdue", amount=999999, due_date=datetime.utcnow()),
        ])
        db.commit()
        yield db, a, b
    engine.dispose()


def test_invoice_tool_uses_only_tenant_overdue_records_and_labels_provenance(records):
    db, a, _ = records
    result = ToolRegistry.calculate_invoice_totals(db, a)
    assert result == {
        "total_overdue": 12.75, "invoice_count": 1,
        "verified": False,
        "source": "tenant_overdue_invoice_records_unreconciled",
    }


@pytest.mark.parametrize("invalid", [-1.0, float("inf"), float("-inf")])
def test_invoice_tool_rejects_negative_and_nonfinite_totals(records, invalid):
    db, a, _ = records
    invoice = db.query(Invoice).filter(
        Invoice.business_id == a, Invoice.status == "overdue"
    ).one()
    invoice.amount = invalid
    db.commit()
    with pytest.raises(ValueError, match="invoice.amount"):
        ToolRegistry.calculate_invoice_totals(db, a)


def test_invoice_tool_rejects_null_record_without_guessing_zero():
    # The actual database has a NOT NULL constraint. Simulate malformed
    # data coming from a mocked adapter or an older schema without
    # weakening real database constraints merely for this regression.
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        SimpleNamespace(amount=None)
    ]
    with pytest.raises(ValueError, match="invoice.amount"):
        ToolRegistry.calculate_invoice_totals(db, "tenant-a")


def test_invalid_invoice_causes_workflow_failure_instead_of_action_success(records):
    db, a, _ = records
    db.execute(text(
        "UPDATE invoices SET amount = -5 WHERE business_id=:tenant AND status='overdue'"
    ), {"tenant": a})
    wf = WorkflowDefinition(
        business_id=a, name="Synthetic invoices",
        is_valid=True, nodes=[
            {"id": "sum", "type": "calculate", "data": {"connector": "demo_finance"}}
        ], edges=[]
    )
    db.add(wf)
    db.commit()
    result = workflow_engine.execute_workflow(db, a, wf.id)
    assert result.status == "failed"
    assert result.verified_success is False
    assert result.step_results["sum"]["status"] == "failed"
