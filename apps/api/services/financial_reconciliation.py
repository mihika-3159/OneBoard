"""Read-only, tenant-scoped comparison against user-provided financial evidence.

A CSV file is NOT an authenticated bank feed. This routine checks agreement
and provenance without mutating invoices, customer status or verified flags.
No raw evidence bytes are persisted, logged or sent to an LLM.
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import re
from sqlalchemy.orm import Session

from apps.api.models.business import Business
from apps.api.models.entities import Invoice, Expense
from apps.api.services.tenant_storage import _lock

_COLUMNS = ["record_type", "record_id", "amount", "currency", "as_of"]
_MAX_BYTES = 256 * 1024
_MAX_ROWS = 500


def money(value) -> Decimal:
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > Decimal("100000000000"):
            raise ValueError("Nonfinite, negative or excessive financial amount")
        if result.as_tuple().exponent < -2:
            raise ValueError("Evidence amounts cannot have more than 2 decimal places")
        return result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid financial evidence amount") from exc


def parse_evidence(csv_text: str) -> list[dict]:
    if not isinstance(csv_text, str) or not csv_text or len(csv_text.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("Evidence CSV must be 1 to 262144 UTF-8 bytes")
    try:
        reader = csv.DictReader(io.StringIO(csv_text, newline=""), strict=True)
        if reader.fieldnames != _COLUMNS:
            raise ValueError("Evidence CSV requires exact ordered columns: " + ",".join(_COLUMNS))
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for row in reader:
            if len(out) >= _MAX_ROWS:
                raise ValueError("Evidence CSV exceeds 500 rows")
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed or incomplete financial evidence row")
            kind, identity = row["record_type"].strip().lower(), row["record_id"].strip()
            if kind not in ("invoice", "expense", "cash"):
                raise ValueError("Unsupported evidence record type")
            if (not 1 <= len(identity) <= 36 or
                    not re.fullmatch(r"[a-zA-Z0-9_-]+", identity)):
                raise ValueError("Invalid evidence record identifier")
            if kind == "cash" and identity != "business":
                raise ValueError("Cash evidence must use record_id=business")
            if (kind, identity) in seen:
                raise ValueError("Duplicate evidence record in one source")
            seen.add((kind, identity))
            currency = row["currency"].strip().upper()
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise ValueError("Evidence currency must be an ISO-style 3-letter code")
            try:
                as_of = date.fromisoformat(row["as_of"].strip())
            except ValueError as exc:
                raise ValueError("Evidence date must be YYYY-MM-DD") from exc
            if as_of > date.today():
                raise ValueError("Evidence cannot be dated in the future")
            out.append({
                "type": kind, "id": identity, "amount": money(row["amount"].strip()),
                "currency": currency, "as_of": as_of.isoformat()
            })
        if not out:
            raise ValueError("Evidence CSV needs at least one record")
        return out
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Malformed evidence CSV") from exc


def reconcile_financial_evidence(
    db: Session, business_id: str, csv_text: str, source_label: str = "Supplied statement"
) -> dict:
    """Return discrepancies; never present a user-supplied file as verified."""
    if not business_id or not isinstance(source_label, str) or not 1 <= len(source_label) <= 100:
        raise ValueError("Tenant and source label are required")
    rows = parse_evidence(csv_text)
    _lock(db,business_id)
    business = db.query(Business).filter(Business.id == business_id).first()
    if business is None:
        raise ValueError("Business not found")
    currency = (business.currency or "").upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Business currency must be configured before reconciliation")
    invoices = {
        item.id: item for item in db.query(Invoice).filter(Invoice.business_id == business_id).all()
    }
    expenses = {
        item.id: item for item in db.query(Expense).filter(Expense.business_id == business_id).all()
    }
    counts = Counter(item.invoice_number for item in invoices.values())
    duplicate_invoice_numbers = sorted(
        number for number, count in counts.items() if count > 1
    )
    results: list[dict] = []
    for row in rows:
        kind, identity = row["type"], row["id"]
        found = (business if kind == "cash" else
                 invoices.get(identity) if kind == "invoice" else expenses.get(identity))
        # Unknown identifiers and other-tenant identifiers look identical.
        if found is None:
            status = "missing_or_inaccessible"
            expected = None
        elif row["currency"] != currency:
            status = "currency_mismatch"
            expected = None
        else:
            amount = (business.current_cash_balance if kind == "cash" else found.amount)
            try:
                expected = money(amount)
                status = "matched_recorded_amount" if expected == row["amount"] else "amount_mismatch"
            except ValueError:
                expected = None
                status = "invalid_application_record"
        results.append({
            "record_type": kind, "record_id": identity,
            "as_of": row["as_of"], "currency": row["currency"],
            "comparison": status,
            "expected_amount": str(expected) if expected is not None else None,
            "supplied_amount": str(row["amount"]),
        })
    disagreements = sum(x["comparison"] != "matched_recorded_amount" for x in results)
    return {
        "status": "needs_review" if disagreements or duplicate_invoice_numbers else "recorded_values_match_supplied_file",
        "rows_checked": len(results),
        "discrepancy_count": disagreements,
        "duplicate_invoice_numbers": duplicate_invoice_numbers,
        "results": results,
        "source_label": source_label,
        "source_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
        "source_type": "user_supplied_evidence_not_authenticated",
        "independently_verified": False,
        "bank_settlement_verified": False,
        "mutated_financial_records": False,
        "comparison_basis": "current_record_amount_not_historical_balance",
        "historical_period_verified": False,
        "warning": (
            "Matching amounts prove agreement with this uploaded file only. "
            "No bank identity, signature, transaction settlement or accounting audit was verified."
        ),
    }
