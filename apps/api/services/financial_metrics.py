"""Tenant-scoped financial calculations shared by dashboard and executive council.

Amounts are derived from recorded customer MRR, recurring expenses, invoices
and the business cash balance. Demo fixture amounts are never substituted.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
from typing import Any, Dict

from sqlalchemy.orm import Session

from apps.api.models.business import Business
from apps.api.models.entities import Customer, Expense, Invoice
from apps.api.services.tenant_storage import _lock
from apps.api.models.operations import JournalEntry


def _money(value: Any, label: str, scale=2) -> Decimal:
    """Reject non-finite or negative unverified recorded amounts.

    Do not allow NaN, infinity, or malformed strings to quietly contaminate
    financial figures used by deterministic advisers.
    """
    try:
        if value is None:
            raise ValueError(label + " is missing")
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise ValueError(label + " must be finite and nonnegative")
        return number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(label + " is not a valid nonnegative amount") from exc


def monthly_expense_decimal(expense: Expense,scale=2) -> Decimal:
    """Normalize only known recurring periods; never guess unknown periods."""
    period = (expense.billing_period or "").strip().lower()
    amount = _money(expense.amount, "expense.amount",scale)
    if period == "annual":
        return (amount / Decimal(12)).quantize(Decimal(1).scaleb(-scale),rounding=ROUND_HALF_UP)
    if period == "monthly":
        return amount
    if period in ("one-off", "one_time", "one-time"):
        return Decimal(0)
    raise ValueError("Unrecognized expense billing period")

def monthly_expense_amount(expense:Expense,scale=2)->float:
    return float(monthly_expense_decimal(expense,scale))


def runway_from_records(cash: float, monthly_burn: float, mrr: float,scale=2) -> tuple[float | None, str, float]:
    """Return months, status and signed net burn without an invented 999-month runway."""
    net_burn_decimal = Decimal(str(monthly_burn)) - Decimal(str(mrr))
    net_burn_decimal=net_burn_decimal.quantize(Decimal(1).scaleb(-scale),rounding=ROUND_HALF_UP)
    net_burn = float(net_burn_decimal)
    if net_burn < 0:
        return None, "profitable", net_burn
    if net_burn == 0:
        return None, "breakeven", net_burn
    if cash <= 0:
        return 0.0, "critical_depleted", net_burn
    exact_months = Decimal(str(cash)) / net_burn_decimal
    months = float(round(exact_months, 1))
    return months, ("healthy" if exact_months >= 12 else "warning" if exact_months >= 6 else "critical"), net_burn


def calculate_business_financials(db: Session, business_id: str) -> Dict[str, Any]:
    """Tenant-scoped, dated financial snapshot with explicit uncertainty.

    No bank connection or independently reconciled ledger is available.
    These values describe user-maintained application records, not verified
    accounting balances. Invalid records are reported instead of silently
    converted or used to produce reassuring health indicators.
    """
    _lock(db,business_id)
    business = db.query(Business).filter(Business.id == business_id).first()
    if business is None:
        raise ValueError("Business not found")
    customers = db.query(Customer).filter(
        Customer.business_id == business_id, Customer.status == "active"
    ).all()
    invoices = db.query(Invoice).filter(Invoice.business_id == business_id).all()
    expenses = db.query(Expense).filter(Expense.business_id == business_id).all()

    issues: list[str] = []
    from apps.api.services.finance_ledger import precision
    try:scale=precision(business.currency)
    except ValueError:scale=2;issues.append("unsupported_business_currency")
    customer_total = Decimal("0.00")
    expense_total = Decimal("0.00")
    overdue_total = Decimal("0.00")
    overdue_count = 0
    journal_rows=db.query(JournalEntry).filter(JournalEntry.business_id==business_id).all()
    by_invoice={}
    for row in journal_rows:
        if row.invoice_id:by_invoice.setdefault(row.invoice_id,[]).append(row)
    cash = business.current_cash_balance
    profile_cash=cash
    opening_recorded=any(r.kind in ("opening_cash","opening_overdraft") for r in journal_rows)
    journal_cash=None
    cash_source="business_profile"
    if journal_rows:
        from apps.api.services.finance_ledger import trial_balance,major
        try:
            journal_cash=Decimal(major(trial_balance(journal_rows,business.currency).get("cash",0),business.currency))
            if opening_recorded:cash=journal_cash;cash_source="journal_with_recorded_opening_balance"
        except ValueError:issues.append("invalid_journal_cash_balance")
    if cash is None or not isfinite(cash):
        issues.append("invalid_business_cash_balance")
        cash = Decimal(0)
    for customer in customers:
        try:
            customer_total += _money(customer.mrr, "customer.mrr",scale)
        except ValueError:
            issues.append(f"invalid_customer_mrr:{customer.id}")
    for expense in expenses:
        try:
            expense_total += monthly_expense_decimal(expense,scale)
        except ValueError:
            issues.append(f"invalid_expense_period_or_amount:{expense.id}")
    for invoice in invoices:
        # The invoice status is authoritative; a past due date alone is not
        # proof that the receivable is still unpaid.
        if invoice.status == "overdue":
            overdue_count += 1
            try:
                if invoice.id in by_invoice:
                    from apps.api.services.finance_ledger import receivable,major
                    rows=by_invoice[invoice.id]
                    if any(r.base_currency!=business.currency for r in rows):raise ValueError("Ledger currency mismatch")
                    overdue_total += _money(major(receivable(rows),business.currency),"invoice.balance",scale)
                else:
                    from apps.api.services.finance_ledger import legacy_balance
                    overdue_total += _money(legacy_balance(db,business_id,invoice), "invoice.amount",scale)
            except ValueError:
                issues.append(f"invalid_overdue_invoice_amount:{invoice.id}")

    mrr = float(customer_total.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP))
    monthly_burn = float(expense_total.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP))
    overdue = float(overdue_total.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP))
    runway, runway_status, net_burn = runway_from_records(cash, expense_total, customer_total,scale)
    configured = bool(customers or invoices or expenses or cash or journal_rows)
    if issues:
        # Partial figures are not a valid basis for a positive health claim.
        runway, runway_status = None, "needs_review"
    elif not configured:
        runway_status = "unconfigured"

    updated = [getattr(record, "updated_at", None) for record in
               [business, *customers, *invoices, *expenses]]
    timestamps = [timestamp for timestamp in updated if isinstance(timestamp, datetime)]
    last_updated = max(timestamps).isoformat() if timestamps else None
    source_records = {
        "active_customer_ids": sorted(c.id for c in customers),
        "expense_ids": sorted(e.id for e in expenses),
        "invoice_ids": sorted(i.id for i in invoices),
    }
    return {
        "mrr": mrr,
        "exact_amounts": {"mrr":str(customer_total),"monthly_burn":str(expense_total),"cash_balance":str(cash),"overdue_receivables":str(overdue_total)},
        "monthly_burn": monthly_burn,
        "net_burn": net_burn,
        "is_profitable": net_burn < 0 if not issues else None,
        "runway_months": runway,
        "runway_status": runway_status,
        "cash_balance": float(round(cash, scale)),
        "profile_cash_balance": str(profile_cash) if profile_cash is not None and isfinite(profile_cash) else None,
        "journal_cash_balance": str(journal_cash) if journal_cash is not None else None,
        "journal_opening_balance_recorded": opening_recorded,
        "overdue_receivables_amount": overdue,
        "overdue_invoices_count": overdue_count,
        "active_customers_count": len(customers),
        "financial_data_status": (
            "needs_review" if issues else "recorded" if configured else "unconfigured"
        ),
        "financial_data_issues": sorted(issues),
        "financial_data_updated_at": last_updated,
        "financial_snapshot_generated_at": datetime.utcnow().isoformat(),
        "financial_data_verified": False,
        "financial_record_ids": source_records,
        "financial_sources": {
            "mrr": "active_customer_records",
            "monthly_burn": "recurring_expense_records",
            "cash_balance": cash_source,
            "overdue_receivables": "overdue_invoice_records",
        },
        "financial_provenance": {
            "cash_balance": "recorded_journal_not_independently_verified" if opening_recorded and journal_cash is not None else "user_recorded_unreconciled",
            "mrr": "user_recorded_unreconciled",
            "monthly_burn": "user_recorded_unreconciled",
            "overdue_receivables": "invoice_status_unreconciled",
            "currency": business.currency or "USD",
            "independent_ledger_reconciliation": False,
        },
        "expense_period_policy": "annual_divided_by_12; one_off_excluded; unknown_flagged_and_excluded",
    }
