"""Adversarial deterministic-finance provenance and invalid-record boundaries."""
from datetime import datetime
from decimal import Decimal

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
import apps.api.models.memory
import apps.api.models.integrations
import apps.api.models.workflow
from apps.api.models.business import Business
from apps.api.models.entities import Customer, Expense, Invoice
from apps.api.services.financial_metrics import calculate_business_financials
from apps.api.routers.business_router import get_dashboard_metrics


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_record_ids_and_currency_provenance_are_tenant_scoped(db):
    from types import SimpleNamespace
    a = Business(name="A", currency="AED", current_cash_balance=600)
    b = Business(name="B", currency="USD", current_cash_balance=1000000)
    db.add_all([a, b])
    db.flush()
    ca = Customer(business_id=a.id, name="A customer", status="active", mrr=100)
    cb = Customer(business_id=b.id, name="B customer", status="active", mrr=10000)
    ea = Expense(business_id=a.id, category="Operations", vendor="A", amount=50,
                 billing_period="monthly")
    ib = Invoice(business_id=b.id, customer_name="B", invoice_number="B-1",
                 amount=50000, due_date=datetime.utcnow(), status="overdue")
    db.add_all([ca, cb, ea, ib])
    db.commit()
    output = calculate_business_financials(db, a.id)
    assert output["financial_record_ids"]["active_customer_ids"] == [ca.id]
    assert output["financial_record_ids"]["expense_ids"] == [ea.id]
    assert cb.id not in repr(output["financial_record_ids"])
    assert ib.id not in repr(output["financial_record_ids"])
    assert output["financial_provenance"]["currency"] == "AED"
    assert output["financial_provenance"]["independent_ledger_reconciliation"] is False
    assert output["financial_data_verified"] is False
    assert output["mrr"] == 100
    assert output["monthly_burn"] == 50
    assert output["runway_months"] is None
    assert output["runway_status"] == "profitable"
    assert output["health_score"] if "health_score" in output else True
    metrics = get_dashboard_metrics(current_user=SimpleNamespace(business_id=a.id), db=db)
    assert metrics["health_score"] is not None


@pytest.mark.parametrize("value", [
    -1, float("nan"), float("inf"), float("-inf"),
])
def test_invalid_active_customer_mrr_suppresses_runway_and_health(db, value):
    from types import SimpleNamespace
    biz = Business(name="Data quality", current_cash_balance=500)
    db.add(biz)
    db.flush()
    cust = Customer(business_id=biz.id, name="Unsafe", mrr=value, status="active")
    db.add(cust)
    if value != -1:
        from sqlalchemy.exc import StatementError
        with pytest.raises(StatementError,match="Nonfinite"):
            db.commit()
        db.rollback()
        return
    db.commit()
    snapshot = calculate_business_financials(db, biz.id)
    assert snapshot["financial_data_status"] == "needs_review"
    assert snapshot["runway_months"] is None
    assert snapshot["financial_data_issues"] == [f"invalid_customer_mrr:{cust.id}"]
    assert get_dashboard_metrics(
        current_user=SimpleNamespace(business_id=biz.id), db=db
    )["health_score"] is None


@pytest.mark.parametrize("period", [None, "", "quarterly", "weekly", "monthly-and-annual"])
def test_unknown_expense_period_not_guessed_as_monthly(db, period):
    from types import SimpleNamespace
    biz = Business(name="Period ambiguity", current_cash_balance=1200)
    db.add(biz)
    db.flush()
    exp = Expense(business_id=biz.id, category="Software", vendor="Vendor",
                  amount=100, billing_period=period)
    db.add(exp)
    db.commit()
    if period is None:
        # SQLAlchemy applies the model's default "monthly" when a Python
        # ORM insert omits/sets None. Explicitly simulate a corrupt legacy
        # database row rather than testing a normalized monthly expense.
        db.execute(text("UPDATE expenses SET billing_period = NULL WHERE id = :id"),
                   {"id": exp.id})
        db.commit()
        db.expire_all()
    snapshot = calculate_business_financials(db, biz.id)
    assert snapshot["monthly_burn"] == 0
    assert snapshot["financial_data_status"] == "needs_review"
    assert snapshot["runway_months"] is None
    assert snapshot["financial_data_issues"] == [
        f"invalid_expense_period_or_amount:{exp.id}"
    ]
    assert get_dashboard_metrics(
        current_user=SimpleNamespace(business_id=biz.id), db=db
    )["health_score"] is None


def test_recorded_overdue_receivables_exclude_other_tenants_and_paid_invoices(db):
    biz = Business(name="Receivables", current_cash_balance=100)
    outsider = Business(name="Outsider", current_cash_balance=0)
    db.add_all([biz, outsider])
    db.flush()
    overdue = Invoice(business_id=biz.id, customer_name="A", invoice_number="A1",
                      amount=120.25, status="overdue", due_date=datetime.utcnow())
    paid = Invoice(business_id=biz.id, customer_name="B", invoice_number="A2",
                   amount=900, status="paid", due_date=datetime.utcnow())
    foreign = Invoice(business_id=outsider.id, customer_name="C", invoice_number="B1",
                      amount=90000, status="overdue", due_date=datetime.utcnow())
    db.add_all([overdue, paid, foreign])
    db.commit()
    snapshot = calculate_business_financials(db, biz.id)
    assert snapshot["overdue_receivables_amount"] == 120.25
    assert snapshot["overdue_invoices_count"] == 1
    assert sorted(snapshot["financial_record_ids"]["invoice_ids"]) == sorted([overdue.id, paid.id])
    assert foreign.id not in repr(snapshot["financial_record_ids"])


def test_annual_expense_rounding_and_one_off_exclusion_are_explicit(db):
    biz = Business(name="Periods", current_cash_balance=1000)
    db.add(biz)
    db.flush()
    db.add_all([
        Expense(business_id=biz.id, category="SaaS", vendor="Annual",
                amount=1000, billing_period="annual"),
        Expense(business_id=biz.id, category="Legal", vendor="One-off",
                amount=9999, billing_period="one-off"),
        Expense(business_id=biz.id, category="Hosting", vendor="Monthly",
                amount=50, billing_period="monthly"),
    ])
    db.commit()
    snapshot = calculate_business_financials(db, biz.id)
    assert snapshot["monthly_burn"] == 133.33
    assert snapshot["financial_data_status"] == "recorded"
    assert snapshot["financial_data_verified"] is False


def test_negative_overdue_invoice_amount_is_not_treated_as_credit(db):
    biz = Business(name="Invalid invoice", current_cash_balance=10)
    db.add(biz)
    db.flush()
    invoice = Invoice(business_id=biz.id, customer_name="A", invoice_number="A",
                      amount=-10, status="overdue", due_date=datetime.utcnow())
    db.add(invoice)
    db.commit()
    result = calculate_business_financials(db, biz.id)
    assert result["financial_data_status"] == "needs_review"
    assert result["overdue_receivables_amount"] == 0
    assert f"invalid_overdue_invoice_amount:{invoice.id}" in result["financial_data_issues"]
