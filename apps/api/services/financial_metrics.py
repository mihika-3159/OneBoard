"""Tenant-scoped financial calculations shared by dashboard and executive council.

Amounts are derived from recorded customer MRR, recurring expenses, invoices
and the business cash balance. Demo fixture amounts are never substituted.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy.orm import Session

from apps.api.models.business import Business
from apps.api.models.entities import Customer, Expense, Invoice


def monthly_expense_amount(expense: Expense) -> float:
    """Convert explicitly annual expenses to monthly; exclude one-off costs.

    Unknown billing periods are treated as monthly for compatibility with
    historical records, rather than silently inventing a new billing period.
    """
    period = (expense.billing_period or "monthly").strip().lower()
    amount = float(expense.amount or 0.0)
    if period == "annual":
        return amount / 12.0
    if period in ("one-off", "one_time", "one-time"):
        return 0.0
    return amount


def runway_from_records(cash: float, monthly_burn: float, mrr: float) -> tuple[float | None, str, float]:
    """Return months, status and signed net burn without an invented 999-month runway."""
    net_burn = round(monthly_burn - mrr, 2)
    if net_burn < 0:
        return None, "profitable", net_burn
    if net_burn == 0:
        return None, "breakeven", net_burn
    if cash <= 0:
        return 0.0, "critical_depleted", net_burn
    months = round(cash / net_burn, 1)
    return months, ("healthy" if months >= 12 else "warning" if months >= 6 else "critical"), net_burn


def calculate_business_financials(db: Session, business_id: str) -> Dict[str, Any]:
    """Compute a single consistent snapshot scoped to one business."""
    business = db.query(Business).filter(Business.id == business_id).first()
    if business is None:
        raise ValueError("Business not found")

    customers = db.query(Customer).filter(
        Customer.business_id == business_id, Customer.status == "active"
    ).all()
    invoices = db.query(Invoice).filter(Invoice.business_id == business_id).all()
    expenses = db.query(Expense).filter(Expense.business_id == business_id).all()

    mrr = round(sum(float(c.mrr or 0.0) for c in customers), 2)
    monthly_burn = round(sum(monthly_expense_amount(e) for e in expenses), 2)
    cash = float(business.current_cash_balance or 0.0)
    overdue = round(sum(float(i.amount or 0.0) for i in invoices if i.status == "overdue"), 2)
    runway, runway_status, net_burn = runway_from_records(cash, monthly_burn, mrr)
    configured = bool(customers or invoices or expenses or cash)
    if not configured:
        runway_status = "unconfigured"

    updated = [getattr(record, "updated_at", None) for record in [business, *customers, *invoices, *expenses]]
    timestamps = [timestamp for timestamp in updated if isinstance(timestamp, datetime)]
    last_updated = max(timestamps).isoformat() if timestamps else None

    return {
        "mrr": mrr,
        "monthly_burn": monthly_burn,
        "net_burn": net_burn,
        "is_profitable": net_burn < 0,
        "runway_months": runway,
        "runway_status": runway_status,
        "cash_balance": round(cash, 2),
        "overdue_receivables_amount": overdue,
        "overdue_invoices_count": sum(i.status == "overdue" for i in invoices),
        "active_customers_count": len(customers),
        "financial_data_status": "recorded" if configured else "unconfigured",
        "financial_data_updated_at": last_updated,
        "financial_sources": {
            "mrr": "active_customer_records",
            "monthly_burn": "recurring_expense_records",
            "cash_balance": "business_profile",
            "overdue_receivables": "overdue_invoice_records",
        },
        "expense_period_policy": "annual_divided_by_12; one_off_excluded; unknown_treated_as_monthly",
    }
