"""Real, user-supplied CSV customer import. No external provider or OAuth.

Every row is validated before any mutation. A business-scoped idempotency key
and PostgreSQL advisory lock prevent duplicate inserts across API workers.
Uploaded data remains explicitly user-supplied and unreconciled.
"""
from __future__ import annotations
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import re
from sqlalchemy import text
from sqlalchemy.orm import Session
from apps.api.models.entities import Customer
from apps.api.models.operations import LocalCustomerImport

_ALLOWED = {"name", "company", "email", "mrr", "status"}
_STATES = {"active", "onboarding", "churn_risk", "churned"}
_MAX_ROWS = 250


def parse_customer_csv(csv_text: str) -> list[dict]:
    if not isinstance(csv_text, str) or not csv_text or len(csv_text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("CSV must be nonempty and at most 1 MiB")
    try:
        reader = csv.DictReader(io.StringIO(csv_text, newline=""), strict=True)
        headings = reader.fieldnames
        if not headings or len(headings) != len(set(headings)):
            raise ValueError("CSV requires unique column headers")
        if not {"name", "mrr"}.issubset(headings) or set(headings) - _ALLOWED:
            raise ValueError("CSV columns must be name,mrr plus optional company,email,status")
        records = []
        for row in reader:
            if len(records) >= _MAX_ROWS:
                raise ValueError("CSV exceeds 250 rows")
            if None in row:
                raise ValueError("CSV row has too many columns")
            if any(value is None for value in row.values()):
                raise ValueError("CSV row is incomplete")
            name = row["name"].strip()
            if not 1 <= len(name) <= 255:
                raise ValueError("Customer name must be 1-255 characters")
            try:
                number = Decimal(row["mrr"].strip())
                if not number.is_finite() or number < 0 or number > Decimal("100000000"):
                    raise ValueError("MRR must be a finite nonnegative number")
                if number.as_tuple().exponent < -2:
                    raise ValueError("MRR must have at most two decimal places")
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError("Invalid customer MRR") from exc
            status = (row.get("status") or "active").strip().lower()
            if status not in _STATES:
                raise ValueError("Unrecognized customer status")
            company = (row.get("company") or "").strip()
            email = (row.get("email") or "").strip()
            if len(company) > 255 or len(email) > 255 or ("\n" in email) or ("\r" in email):
                raise ValueError("Customer company or email is too long")
            if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                raise ValueError("Invalid customer email")
            records.append({
                "name": name, "mrr": number, "status": status,
                "company": company or None, "email": email or None,
            })
        if not records:
            raise ValueError("CSV must contain at least one data row")
        return records
    except csv.Error as exc:
        raise ValueError("Malformed CSV syntax") from exc


def import_customer_csv(
    db: Session, business_id: str, csv_text: str,
    idempotency_key: str, source_name: str = "User CSV", dry_run: bool = True
) -> dict:
    if not business_id:
        raise ValueError("Business context is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", idempotency_key or ""):
        raise ValueError("Invalid import idempotency key")
    if not 1 <= len(source_name) <= 100:
        raise ValueError("Source name must be 1-100 characters")
    parsed = parse_customer_csv(csv_text)
    digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    if dry_run:
        return {
            "status": "preview", "is_simulated": False,
            "source": "user_supplied_csv_unverified",
            "rows_validated": len(parsed),
            "sample": [{**{key: row[key] for key in ("name", "status")},"mrr":float(row["mrr"])} for row in parsed[:3]],
            "written": False,
        }
    if db.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(
            hashlib.sha256((business_id + ":csv:" + idempotency_key).encode()).digest()[:8],
            "big", signed=True,
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    previous = db.query(LocalCustomerImport).filter(
        LocalCustomerImport.business_id == business_id,
        LocalCustomerImport.idempotency_key == idempotency_key,
    ).first()
    if previous:
        if previous.content_sha256 != digest or previous.source_name != source_name:
            raise ValueError("Import key already used for different CSV content")
        return {
            "status": "already_imported", "is_simulated": False,
            "source": "user_supplied_csv_unverified",
            "rows_imported": previous.row_count,
            "customer_ids": previous.customer_ids,
            "written": False,
        }
    from apps.api.services.tenant_storage import _lock
    from apps.api.services.workflow_events import customer_created
    _lock(db,business_id)
    ids = []
    for row in parsed:
        customer = Customer(
            business_id=business_id, name=row["name"], mrr=row["mrr"],
            company=row["company"], email=row["email"], status=row["status"],
            custom_notes="User-supplied CSV import; not independently reconciled",
        )
        db.add(customer)
        db.flush()
        ids.append(customer.id)
        customer_created(db,business_id,customer)
    batch = LocalCustomerImport(
        business_id=business_id, idempotency_key=idempotency_key,
        content_sha256=digest, source_name=source_name,
        row_count=len(ids), customer_ids=ids,
    )
    db.add(batch)
    db.commit()
    return {
        "status": "imported", "source": "user_supplied_csv_unverified",
        "is_simulated": False, "written": True,
        "rows_imported": len(ids), "customer_ids": ids,
    }
