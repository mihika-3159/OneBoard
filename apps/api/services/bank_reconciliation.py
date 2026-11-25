"""Strict bank CSV ingestion and one-to-one reconciliation, no bank authentication."""
import csv,hashlib,io,re
from datetime import datetime
from apps.api.models.operations import BankStatementLine,JournalEntry
from apps.api.services.finance_ledger import minor,major,date_key,ensure_open,workspace
from apps.api.services.tenant_storage import _lock

HEADERS=["reference","date","currency","amount"]

def parse(csv_text):
    if not isinstance(csv_text,str) or not 1<=len(csv_text.encode("utf-8"))<=262144:raise ValueError("Bank CSV exceeds bounds")
    rows=[];seen=set()
    try:
        reader=csv.DictReader(io.StringIO(csv_text,newline=""),strict=True)
        if reader.fieldnames!=HEADERS:raise ValueError("Bank CSV must use reference,date,currency,amount")
        for row in reader:
            if len(rows)>=500 or None in row or any(v is None for v in row.values()):raise ValueError("Malformed or oversized bank CSV")
            ref=row["reference"]
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}",ref) or ref in seen:raise ValueError("Invalid or duplicate bank reference")
            seen.add(ref);date=date_key(row["date"]);currency=row["currency"];amount=minor(row["amount"],currency,signed=True)
            if amount==0:raise ValueError("Zero bank transaction")
            rows.append((ref,date,currency,amount))
    except csv.Error as exc:raise ValueError("Malformed bank CSV") from exc
    if not rows:raise ValueError("Empty bank CSV")
    return rows

def serialize(row):
    return {"id":row.id,"account":row.account,"reference":row.reference,"booked_on":row.booked_on,
            "period":row.period,"currency":row.currency,"signed_amount":major(row.signed_minor,row.currency),
            "source_sha256":row.source_hash,"journal_id":row.journal_id,"matched_by":row.matched_by,
            "matched_at":row.matched_at.isoformat() if row.matched_at else None,"bank_verified":False}

def import_lines(db,tenant,account,csv_text,preview=False):
    if not isinstance(account,str) or not re.fullmatch(r"[A-Za-z0-9 _.-]{1,80}",account):raise ValueError("Invalid bank account label")
    rows=parse(csv_text);source_hash=hashlib.sha256(csv_text.encode()).hexdigest()
    _lock(db,tenant);workspace(db,tenant)
    new=[];existing=[]
    for ref,date,currency,amount in rows:
        old=db.query(BankStatementLine).filter_by(business_id=tenant,account=account,reference=ref).first()
        if old:
            if (old.booked_on,old.currency,old.signed_minor)!=(date,currency,amount):raise ValueError("Bank reference conflicts with imported record")
            existing.append(old);continue
        ensure_open(db,tenant,date[:7])
        new.append(BankStatementLine(business_id=tenant,account=account,reference=ref,booked_on=date,period=date[:7],
            currency=currency,signed_minor=amount,source_hash=source_hash))
    if not preview:
        if db.query(BankStatementLine).filter_by(business_id=tenant).count()+len(new)>20000:raise ValueError("Bank statement capacity reached")
        db.add_all(new);db.commit()
    return {"preview":preview,"new":len(new),"duplicates":len(existing),"source_sha256":source_hash,
            "records":[serialize(row) for row in existing+new] if not preview else [],
            "bank_verified":False,"provenance":"user_supplied_statement_not_authenticated"}

def cash_sign(row):
    if row.kind in ("opening_cash","opening_overdraft"):return 0
    return 1 if row.debit_account=="cash" else -1 if row.credit_account=="cash" else 0

def candidates(db,tenant,line):
    rows=db.query(JournalEntry).filter_by(business_id=tenant,booked_on=line.booked_on,currency=line.currency,original_minor=abs(line.signed_minor)).all()
    used={r[0] for r in db.query(BankStatementLine.journal_id).filter(BankStatementLine.business_id==tenant,BankStatementLine.journal_id.isnot(None)).all()}
    return [row for row in rows if cash_sign(row)*row.original_minor==line.signed_minor and row.id not in used]

def match(db,tenant,actor,line_id,journal_id):
    _lock(db,tenant)
    row=db.query(BankStatementLine).filter_by(business_id=tenant,id=line_id).first()
    if not row:raise ValueError("Bank line unavailable")
    if row.journal_id==journal_id:return serialize(row)
    if row.journal_id:raise ValueError("Bank line already reconciled")
    ensure_open(db,tenant,row.period)
    entry=next((e for e in candidates(db,tenant,row) if e.id==journal_id),None)
    if not entry:raise ValueError("Journal entry unavailable or amount, currency, date or direction does not match")
    row.journal_id=entry.id;row.matched_by=actor;row.matched_at=datetime.utcnow();db.commit()
    return serialize(row)
