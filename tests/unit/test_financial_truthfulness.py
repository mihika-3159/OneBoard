"""Financial truthfulness regressions for issue #3.

All calculations use isolated SQLite fixtures; no paid services or external data.
"""
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import Request, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.core.database import Base
import apps.api.models.business  # noqa: F401
import apps.api.models.entities  # noqa: F401
import apps.api.models.goals_tasks  # noqa: F401
import apps.api.models.workflow  # noqa: F401
import apps.api.models.memory  # noqa: F401
import apps.api.models.agent_council  # noqa: F401
import apps.api.models.decision_evidence  # noqa: F401
import apps.api.models.integrations  # noqa: F401
from apps.api.models.business import Business
from apps.api.models.entities import Customer, Expense, Invoice
from apps.api.services.financial_metrics import (
    calculate_business_financials, monthly_expense_amount, runway_from_records,
)
from apps.api.services.council_engine import council_engine
from apps.api.routers.business_router import get_dashboard_metrics
from apps.api.routers.auth_router import RegisterRequest, register


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.mark.parametrize("cash,mrr,expenses,months,status", [
    (0, 0, 0, None, "breakeven"),
    (0, 0, 100, 0.0, "critical_depleted"),
    (1200, 0, 100, 12.0, "healthy"),
    (600, 0, 100, 6.0, "warning"),
    (299, 0, 100, 3.0, "critical"),
    (0, 100, 0, None, "profitable"),
    (0, 100, 100, None, "breakeven"),
    (100, 50, 100, 2.0, "critical"),
    (1200, 100, 200, 12.0, "healthy"),
    (-10, 0, 100, 0.0, "critical_depleted"),
    (1000, 300, 100, None, "profitable"),
])
def test_runway_boundary_cases(cash, mrr, expenses, months, status):
    actual_months, actual_status, burn = runway_from_records(cash, expenses, mrr)
    assert actual_months == months
    assert actual_status == status
    assert burn == round(expenses - mrr, 2)


def test_tenant_financials_are_dynamic_and_council_matches_dashboard(db):
    a = Business(name="Real Company A", current_cash_balance=1200)
    b = Business(name="Other Company B", current_cash_balance=77777)
    db.add_all([a, b])
    db.flush()
    db.add_all([
        Customer(business_id=a.id, name="A Customer", status="active", mrr=100),
        Expense(business_id=a.id, category="Infrastructure", vendor="Hosting",
                amount=200, billing_period="monthly"),
        Expense(business_id=a.id, category="Software", vendor="Annual SaaS",
                amount=1200, billing_period="annual"),
        Expense(business_id=a.id, category="Legal", vendor="One-time setup",
                amount=5000, billing_period="one-off"),
        Invoice(business_id=a.id, customer_name="A Customer", invoice_number="A-1",
                amount=75, status="overdue", due_date=datetime.utcnow()),
        Customer(business_id=b.id, name="B Customer", status="active", mrr=9000),
    ])
    db.commit()

    a_metrics = get_dashboard_metrics(current_user=SimpleNamespace(business_id=a.id), db=db)
    a_council = council_engine._calculate_deterministic_financials(db, a.id)
    b_metrics = calculate_business_financials(db, b.id)

    assert a_metrics["mrr"] == 100
    assert a_metrics["monthly_burn"] == 300
    assert a_metrics["net_burn"] == 200
    assert a_metrics["runway_months"] == 6
    assert a_metrics["overdue_receivables_amount"] == 75
    assert a_council["cash_balance"] == 1200
    assert a_council["monthly_expenses"] == a_metrics["monthly_burn"]
    assert a_council["runway_months"] == a_metrics["runway_months"]
    assert b_metrics["mrr"] == 9000
    assert b_metrics["overdue_receivables_amount"] == 0

    a.current_cash_balance = 2400
    db.commit()
    updated = council_engine._calculate_deterministic_financials(db, a.id)
    assert updated["runway_months"] == 12
    assert updated["cash_balance"] == 2400
    assert updated["cash_balance"] != b.current_cash_balance


def test_unconfigured_business_has_no_fake_health_or_runway(db):
    business = Business(name="New Company", current_cash_balance=0)
    db.add(business)
    db.commit()
    metrics = get_dashboard_metrics(
        current_user=SimpleNamespace(business_id=business.id), db=db
    )
    assert metrics["financial_data_status"] == "unconfigured"
    assert metrics["health_score"] is None
    assert metrics["runway_months"] is None
    assert metrics["runway_status"] == "unconfigured"


def test_registration_does_not_invent_cash_burn_or_runway(db):
    req = RegisterRequest(
        name="Real Founder", email="real-founder@example.test",
        password="strong-password-123", business_name="Actual Business"
    )
    request = Request({"type": "http", "method": "POST", "headers": []})
    result = register(req=req, response=Response(), request=request, db=db)
    business = db.get(Business, result["business"]["id"])
    assert business is not None
    assert business.current_cash_balance == 0
    assert business.monthly_burn_rate == 0
    assert business.runway_months == 0
    assert result["business"]["current_cash_balance"] == 0


def test_financial_snapshot_provenance_and_no_cross_tenant_overdue(db):
    a = Business(name="A", current_cash_balance=500)
    b = Business(name="B", current_cash_balance=0)
    db.add_all([a, b])
    db.flush()
    db.add(Invoice(business_id=b.id, customer_name="B", invoice_number="B-1",
                   amount=10000, status="overdue", due_date=datetime.utcnow()))
    db.commit()
    snapshot = calculate_business_financials(db, a.id)
    assert snapshot["overdue_receivables_amount"] == 0
    assert snapshot["financial_sources"]["cash_balance"] == "business_profile"
    assert snapshot["financial_data_updated_at"] is not None
