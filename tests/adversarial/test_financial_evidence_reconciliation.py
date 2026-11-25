"""Financial evidence can expose disagreement, never certify uploaded files as bank records."""
from datetime import date, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import pytest
from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.goals_tasks
import apps.api.models.workflow
import apps.api.models.memory
import apps.api.models.agent_council
import apps.api.models.decision_evidence
import apps.api.models.integrations
import apps.api.models.operations
from apps.api.models.business import Business
from apps.api.models.entities import Invoice, Expense
from apps.api.services.financial_reconciliation import reconcile_financial_evidence, parse_evidence


@pytest.fixture
def records():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        a, b = Business(name="Synthetic A", currency="AED", current_cash_balance=250), Business(
            name="Synthetic B", currency="USD", current_cash_balance=100000)
        db.add_all([a, b])
        db.flush()
        inv = Invoice(business_id=a.id, invoice_number="A1", customer_name="One",
                      amount=95.25, status="paid", due_date=datetime.utcnow())
        exp = Expense(business_id=a.id, vendor="Host", category="Infrastructure",
                      amount=49, billing_period="monthly")
        secret = Invoice(business_id=b.id, invoice_number="SECRET",
                         customer_name="Outside", amount=98765, status="paid",
                         due_date=datetime.utcnow())
        db.add_all([inv, exp, secret])
        db.commit()
        yield db, a, b, inv, exp, secret
    engine.dispose()


def line(kind, rid, amount, currency="AED"):
    return f"{kind},{rid},{amount},{currency},{date.today().isoformat()}\n"


def test_matching_evidence_is_not_independent_verification(records):
    db, a, _, inv, exp, _ = records
    source = "record_type,record_id,amount,currency,as_of\n"
    source += line("invoice", inv.id, "95.25") + line("expense", exp.id, "49.00")
    source += line("cash", "business", "250.00")
    result = reconcile_financial_evidence(db, a.id, source)
    assert result["discrepancy_count"] == 0
    assert result["rows_checked"] == 3
    assert result["independently_verified"] is False
    assert result["bank_settlement_verified"] is False
    assert result["mutated_financial_records"] is False
    assert result["source_type"] == "user_supplied_evidence_not_authenticated"
    assert db.get(Invoice, inv.id).status == "paid"


def test_cross_tenant_id_is_indistinguishable_from_missing(records):
    db, a, _, inv, _, foreign = records
    head = "record_type,record_id,amount,currency,as_of\n"
    source = head + line("invoice", foreign.id, "98765") + line("invoice", "not-present", "12")
    result = reconcile_financial_evidence(db, a.id, source)
    assert [row["comparison"] for row in result["results"]] == [
        "missing_or_inaccessible", "missing_or_inaccessible",
    ]
    assert all(row["expected_amount"] is None for row in result["results"])
    assert "USD" not in str(result)
    assert result["independently_verified"] is False


def test_amount_currency_and_invalid_db_records_are_flagged(records):
    db, a, _, inv, _, _ = records
    source = "record_type,record_id,amount,currency,as_of\n"
    source += line("invoice", inv.id, "95.24")
    source += line("cash", "business", "250", "USD")
    result = reconcile_financial_evidence(db, a.id, source)
    assert [row["comparison"] for row in result["results"]] == ["amount_mismatch", "currency_mismatch"]
    assert result["discrepancy_count"] == 2
    db.get(Invoice, inv.id).amount = float("inf")
    from sqlalchemy.exc import StatementError
    with pytest.raises(StatementError,match="Nonfinite"):
        db.flush()
    db.rollback()
    db.get(Invoice,inv.id).amount=-1
    db.flush()
    result=reconcile_financial_evidence(db,a.id,source)
    assert result["results"][0]["comparison"]=="invalid_application_record"


@pytest.mark.parametrize("source", [
    "", "record_type,record_id,amount,currency,as_of\n",
    "record_type,record_id,amount,currency,as_of\ninvoice,id,-10,AED,2026-01-01\n",
    "record_type,record_id,amount,currency,as_of\ninvoice,id,nan,AED,2026-01-01\n",
    "record_type,record_id,amount,currency,as_of\ninvoice,id,1.234,AED,2026-01-01\n",
    "record_type,record_id,amount,currency,as_of\ninvoice,id,1,USD,9999-12-31\n",
    "record_type,record_id,amount,currency,as_of\ninvoice,id,1,AED,2026-01-01\ninvoice,id,1,AED,2026-01-01\n",
    "record_type,record_id,amount,currency,as_of\ninvoice,id,1,AED,2026-01-01,oversized\n",
    "record_type,record_id,amount,currency,as_of\ninvoice,id,1,AED\n",
    "record_type,record_id,amount,currency,as_of\nother,id,1,AED,2026-01-01\n",
])
def test_malformed_or_duplicate_evidence_rejected(source):
    with pytest.raises(ValueError):
        parse_evidence(source)


def test_limit_prevents_large_record_lists():
    header = "record_type,record_id,amount,currency,as_of\n"
    source = header + "".join(line("invoice", str(i), "1") for i in range(501))
    with pytest.raises(ValueError, match="500"):
        parse_evidence(source)
