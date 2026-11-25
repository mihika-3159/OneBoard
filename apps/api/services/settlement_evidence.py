"""Append-only user-reported settlement evidence, not bank verification."""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
from sqlalchemy import text
from apps.api.models.business import Business
from apps.api.models.entities import Invoice
from apps.api.models.operations import SettlementEvidence
from apps.api.services.financial_reconciliation import money
from apps.api.services.tenant_storage import _lock

def record_settlement(db, tenant, *, invoice_id, source_reference, source_sha256,
                      amount, currency, fx_rate, fx_source, settled_on, period):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", source_reference):
        raise ValueError("Invalid source reference")
    if not re.fullmatch(r"[a-f0-9]{64}", source_sha256):
        raise ValueError("A source SHA-256 digest is required")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Currency must be a three-letter code")
    when = date.fromisoformat(settled_on)
    if when.isoformat() != settled_on or when > date.today() or period != settled_on[:7]:
        raise ValueError("Settlement date and accounting period must agree")
    original = money(amount)
    if original <= 0:
        raise ValueError("Settlement must be positive")
    try:
        rate = Decimal(str(fx_rate))
        if not rate.is_finite() or not Decimal("0.00000001") <= rate <= Decimal("100000000") or rate.as_tuple().exponent < -8:
            raise ValueError("Invalid FX rate")
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid FX rate") from exc
    _lock(db, tenant)
    business = db.query(Business).filter_by(id=tenant).first()
    invoice = db.query(Invoice).filter_by(id=invoice_id,business_id=tenant).first()
    if business is None or invoice is None:
        raise ValueError("Invoice missing or inaccessible")
    base = (business.currency or "").upper()
    if not re.fullmatch(r"[A-Z]{3}", base):
        raise ValueError("Business base currency is not configured")
    if currency == base:
        if rate != 1 or fx_source != "same_currency":
            raise ValueError("Same-currency settlement requires rate 1 and same_currency source")
    elif not fx_source.strip() or fx_source == "same_currency" or len(fx_source)>200:
        raise ValueError("Cross-currency settlement requires an explicit FX source")
    converted = (original * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if converted <= 0:
        raise ValueError("Settlement rounds to zero")
    payload = [invoice_id,source_sha256,str(original),currency,base,str(rate.normalize()),fx_source,settled_on,period]
    digest = hashlib.sha256(json.dumps(payload,separators=(",",":")).encode()).hexdigest()
    old = db.query(SettlementEvidence).filter_by(business_id=tenant,source_reference=source_reference).first()
    if old:
        if old.request_sha256 != digest:
            raise ValueError("Source reference already used with different settlement")
        return old
    existing = db.query(SettlementEvidence).filter_by(business_id=tenant,invoice_id=invoice_id).all()
    if any(row.base_currency != base for row in existing):
        raise ValueError("Invoice settlement currency history is inconsistent")
    if sum((Decimal(row.base_amount) for row in existing),Decimal(0)) + converted > money(invoice.amount):
        raise ValueError("Recorded settlement exceeds invoice amount")
    row = SettlementEvidence(business_id=tenant,invoice_id=invoice_id,
        source_reference=source_reference,source_sha256=source_sha256,request_sha256=digest,
        currency=currency,original_amount=str(original),base_currency=base,
        fx_rate=str(rate.normalize()),fx_source=fx_source,base_amount=str(converted),
        settled_on=settled_on,period=period)
    db.add(row)
    db.commit()
    return row

def serialize(row):
    return {"id":row.id,"invoice_id":row.invoice_id,"source_reference":row.source_reference,
            "source_sha256":row.source_sha256,"original_amount":row.original_amount,
            "currency":row.currency,"base_currency":row.base_currency,"fx_rate":row.fx_rate,
            "fx_source":row.fx_source,"base_amount":row.base_amount,"settled_on":row.settled_on,
            "period":row.period,"provenance":"user_reported_unverified","bank_settlement_verified":False}

def period_summary(db,tenant,period):
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])",period):
        raise ValueError("Accounting period must be YYYY-MM")
    rows=db.query(SettlementEvidence).filter_by(business_id=tenant,period=period).all()
    totals={}
    for row in rows:
        totals[row.base_currency]=totals.get(row.base_currency,Decimal(0))+Decimal(row.base_amount)
    return {"period":period,"totals_by_currency":{k:str(v) for k,v in totals.items()},
            "records":[serialize(row) for row in rows[:500]],"record_count":len(rows),
            "truncated":len(rows)>500,"bank_settlement_verified":False}
