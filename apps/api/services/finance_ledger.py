"""Tenant-scoped append-only double-entry journal, exact currency units and close controls.

A balanced journal is an internal accounting record, not an authenticated bank feed.
Existing invoices enter the ledger only by explicit founder recognition; no fabricated
opening balance or historical revenue is inferred.
"""
from datetime import date,datetime
from decimal import Decimal,ROUND_HALF_UP
import hashlib,json,re
from sqlalchemy import func
from apps.api.core.money import decimal_value
from apps.api.models.business import Business
from apps.api.models.entities import Invoice,Expense
from apps.api.models.operations import JournalEntry,AccountingClose,BankStatementLine,SettlementEvidence
from apps.api.services.tenant_storage import _lock

# Explicit supported ISO currency precision; unsupported currencies fail closed.
SCALES={**dict.fromkeys("AED USD EUR GBP CAD SGD INR AUD NZD CHF CNY HKD SAR QAR ZAR SEK NOK DKK MXN BRL PLN TRY ILS THB MYR PHP IDR TWD".split(),2),
        **dict.fromkeys("JPY KRW VND CLP ISK XAF XOF".split(),0),
        **dict.fromkeys("KWD BHD OMR JOD TND".split(),3)}
ACCOUNTS={
 "invoice_issue":("receivables","revenue"),
 "opening_invoice":("receivables","opening_equity"),
 "payment":("cash","receivables"),
 "refund":("receivables","cash"),
 "credit":("sales_returns","receivables"),
 "debit_adjustment":("receivables","revenue"),
 "credit_reversal":("receivables","sales_returns"),
 "expense":("operating_expense","cash"),
 "cogs":("cost_of_sales","cash"),
 "acquisition":("acquisition_expense","cash"),
 "opening_cash":("cash","opening_equity"),
 "opening_overdraft":("opening_equity","cash"),
 "capital":("cash","capital"),
 "distribution":("capital","cash"),
}
INVOICE_KINDS={"invoice_issue","opening_invoice","payment","refund","credit","debit_adjustment","credit_reversal"}
RECOGNITION={"invoice_issue","opening_invoice"}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode()).hexdigest()

def period_key(value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])",value) or value.startswith("0000"):
        raise ValueError("Accounting period must be YYYY-MM")
    return value

def date_key(value):
    try:d=date.fromisoformat(value)
    except (ValueError,TypeError):raise ValueError("Booking date must be YYYY-MM-DD") from None
    if d.isoformat()!=value or d>date.today():raise ValueError("Booking date cannot be future or malformed")
    return value

def precision(currency):
    if currency not in SCALES:raise ValueError("Unsupported accounting currency")
    return SCALES[currency]

def minor(value,currency,signed=False):
    d=decimal_value(value);scale=10**precision(currency)
    if not signed and d<=0:raise ValueError("Amount must be positive")
    if d*scale!=(d*scale).to_integral_value():raise ValueError("Amount exceeds currency precision")
    return int(d*scale)

def major(value,currency):
    return format(Decimal(value).scaleb(-precision(currency)),f".{precision(currency)}f")

def fx_amount(amount,currency,base,rate,source):
    original=minor(amount,currency)
    rate=decimal_value(rate)
    if rate<=0 or rate>Decimal("100000000") or rate!=rate.quantize(Decimal("0.00000001")):raise ValueError("Invalid FX rate")
    if not isinstance(source,str) or not 1<=len(source.strip())<=200:raise ValueError("FX source required")
    if currency==base and (rate!=1 or source!="same_currency"):raise ValueError("Same currency requires rate 1")
    if currency!=base and source=="same_currency":raise ValueError("Foreign currency needs a dated FX source")
    converted=(Decimal(original).scaleb(-precision(currency))*rate*10**precision(base)).quantize(Decimal(1),rounding=ROUND_HALF_UP)
    if not 0<converted<=Decimal("100000000000")*10**precision(base):raise ValueError("Converted amount out of bounds")
    return original,int(converted),str(rate.normalize())

def workspace(db,tenant):
    row=db.query(Business).filter_by(id=tenant).first()
    if not row:raise ValueError("Workspace unavailable")
    precision(row.currency)
    return row

def ensure_open(db,tenant,period):
    if db.query(AccountingClose.id).filter(AccountingClose.business_id==tenant,AccountingClose.period>=period).first():raise ValueError("Accounting period is closed or precedes a closed period")

def serialize(row):
    return {"id":row.id,"reference":row.reference,"kind":row.kind,"invoice_id":row.invoice_id,"related_entry_id":row.related_entry_id,
      "invoice_minor_delta":row.invoice_minor_delta,"carrying_minor":row.carrying_minor,
      "debit_account":row.debit_account,"credit_account":row.credit_account,"currency":row.currency,"amount":major(row.original_minor,row.currency),
      "base_currency":row.base_currency,"base_amount":major(row.base_minor,row.base_currency),"fx_rate":row.fx_rate,"fx_source":row.fx_source,
      "booked_on":row.booked_on,"period":row.period,"evidence_sha256":row.evidence_hash,"actor_id":row.actor_id,
      "provenance":"user_recorded_not_bank_verified","recorded_at":row.recorded_at.isoformat()}

def invoice_entries(db,tenant,invoice_id):
    return db.query(JournalEntry).filter_by(business_id=tenant,invoice_id=invoice_id).order_by(JournalEntry.booked_on,JournalEntry.id).all()

def receivable(entries):
    return sum((r.base_minor if r.debit_account=="receivables" else -r.base_minor if r.credit_account=="receivables" else 0) for r in entries)

def invoice_balance(db,tenant,invoice):
    """Legacy records remain explicitly unreconciled; enrolled invoices use the journal."""
    rows=invoice_entries(db,tenant,invoice.id)
    if rows:
        base=rows[0].base_currency
        if any(r.base_currency!=base for r in rows):raise ValueError("Invoice currency history is inconsistent")
        return Decimal(major(receivable(rows),base))
    return legacy_balance(db,tenant,invoice)


def legacy_balance_from_records(invoice,settlements,currency):
    amount=decimal_value(invoice.amount)
    if amount<0:raise ValueError("invoice.amount must be nonnegative")
    if invoice.status=="paid":return Decimal(0)
    if not settlements:return amount
    if any(r.base_currency!=currency for r in settlements):raise ValueError("Legacy settlement currency mismatch")
    paid=sum((decimal_value(r.base_amount) for r in settlements),Decimal(0))
    if paid<0 or paid>amount:raise ValueError("Legacy settlement exceeds invoice amount")
    return amount-paid

def legacy_balance(db,tenant,invoice):
    settlements=db.query(SettlementEvidence).filter_by(business_id=tenant,invoice_id=invoice.id).all()
    return legacy_balance_from_records(invoice,settlements,workspace(db,tenant).currency if settlements else None)

def allocation(total,prior,adding,full):
    """Cumulative allocation removes split-payment/refund rounding drift."""
    def rounded(n):return int((Decimal(total)*n/full).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    return rounded(prior+adding)-rounded(prior)

def post(db,tenant,actor,*,reference,kind,amount,currency,fx_rate,fx_source,booked_on,evidence_text,invoice_id=None,related_entry_id=None,commit=True):
    if kind not in ACCOUNTS and kind!="fx_revaluation":raise ValueError("Unsupported journal transaction")
    if not isinstance(reference,str) or reference.startswith("fx:") or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}",reference):raise ValueError("Invalid reference")
    if not actor:raise ValueError("Actor required")
    if not isinstance(evidence_text,str) or not 1<=len(evidence_text.encode("utf-8"))<=262144 or not evidence_text.strip():raise ValueError("Evidence is required")
    booked_on=date_key(booked_on);period=booked_on[:7]
    _lock(db,tenant)
    biz=workspace(db,tenant);base=biz.currency
    original,converted,rate=fx_amount(amount,currency,base,fx_rate,fx_source)
    evidence_hash=hashlib.sha256(evidence_text.encode()).hexdigest()
    request=digest([kind,invoice_id,related_entry_id,original,currency,converted,base,rate,fx_source,booked_on,evidence_hash])
    existing=db.query(JournalEntry).filter_by(business_id=tenant,reference=reference).first()
    if existing:
        if existing.request_hash!=request:raise ValueError("Journal reference already used with different transaction")
        return existing
    ensure_open(db,tenant,period)
    if db.query(JournalEntry).filter_by(business_id=tenant).count()>=20000:raise ValueError("Journal capacity reached")
    # A currency switch must be implemented as an explicit migration, never a mixed base sum.
    if db.query(JournalEntry.id).filter(JournalEntry.business_id==tenant,JournalEntry.base_currency!=base).first():raise ValueError("Ledger base currency changed; migration required")
    invoice=None;entries=[];delta=None;carrying=None;fx_difference=0
    if kind in INVOICE_KINDS or kind=="fx_revaluation":
        invoice=db.query(Invoice).filter_by(business_id=tenant,id=invoice_id).first()
        if not invoice or invoice.status in ("draft","cancelled"):raise ValueError("Invoice missing, draft or cancelled")
        entries=invoice_entries(db,tenant,invoice_id)
        if kind in RECOGNITION:
            if entries or invoice.status=="paid" or related_entry_id:raise ValueError("Invoice already recognized or historically paid")
            legacy=db.query(SettlementEvidence.id).filter_by(business_id=tenant,invoice_id=invoice_id).first()
            if legacy and kind!="opening_invoice":raise ValueError("Legacy settlement history requires opening-balance recognition")
            target=legacy_balance(db,tenant,invoice) if kind=="opening_invoice" else decimal_value(invoice.amount)
            if converted!=minor(target,base):raise ValueError("Recognition must equal recorded outstanding base invoice amount")
            if kind=="opening_invoice" and currency!=base:raise ValueError("Legacy opening invoices use recorded base currency")
            delta=original;carrying=converted
        else:
            origin=next((r for r in entries if r.kind in RECOGNITION),None)
            if origin is None:raise ValueError("Recognize the invoice first")
            if booked_on<max(r.booked_on for r in entries):raise ValueError("Invoice transactions must be posted chronologically")
            denomination=origin.currency;foreign=denomination!=base
            if foreign and currency!=denomination:raise ValueError("Foreign invoice transactions must use its original denomination")
            balance=receivable(entries)
            units=sum(r.invoice_minor_delta or 0 for r in entries) if foreign else balance
            applied=original if foreign else converted
            if kind=="fx_revaluation":
                if not foreign or related_entry_id or original!=units or units<=0:raise ValueError("Revalue the full outstanding foreign invoice amount")
                delta=0;carrying=0;fx_difference=converted-balance
                if not fx_difference:raise ValueError("Revaluation would not change carrying value")
            elif kind in ("payment","credit"):
                if applied>units:raise ValueError("Transaction exceeds outstanding receivable")
                delta=-applied
                carrying=allocation(balance,0,applied,units) if foreign else converted
                fx_difference=converted-carrying
                if related_entry_id:raise ValueError("Unexpected reversal reference")
            elif kind=="debit_adjustment":
                if related_entry_id:raise ValueError("Unexpected reversal reference")
                delta=applied;carrying=converted
            elif kind in ("refund","credit_reversal"):
                expected="payment" if kind=="refund" else "credit"
                parent=next((r for r in entries if r.id==related_entry_id and r.kind==expected),None)
                if not parent or parent.currency!=currency or parent.fx_rate!=rate:raise ValueError("Reversal requires original entry currency and FX rate")
                prior=[r for r in entries if r.related_entry_id==parent.id and r.kind==kind]
                prior_original=sum(r.original_minor for r in prior)
                if prior_original+original>parent.original_minor:raise ValueError("Reversal exceeds original transaction")
                converted=allocation(parent.base_minor,prior_original,original,parent.original_minor)
                carrying=allocation(parent.carrying_minor if parent.carrying_minor is not None else parent.base_minor,prior_original,original,parent.original_minor)
                if converted<=0:raise ValueError("Reversal rounds to zero; reverse a larger amount")
                delta=original if foreign else carrying
                fx_difference=carrying-converted
    elif invoice_id or related_entry_id:raise ValueError("Unexpected invoice or reversal reference")
    if kind in ("opening_cash","opening_overdraft"):
        if db.query(JournalEntry.id).filter(JournalEntry.business_id==tenant,JournalEntry.kind.in_(["opening_cash","opening_overdraft"])).first():raise ValueError("Opening cash already recorded")
        if currency!=base:raise ValueError("Opening cash must use base currency")
    extra=None
    if kind=="fx_revaluation":
        debit,credit=("receivables","unrealized_fx_gain") if fx_difference>0 else ("unrealized_fx_loss","receivables")
        booked_minor=abs(fx_difference)
    else:
        debit,credit=ACCOUNTS[kind];booked_minor=converted
    row=JournalEntry(business_id=tenant,reference=reference,request_hash=request,kind=kind,invoice_id=invoice_id,
        related_entry_id=related_entry_id,invoice_minor_delta=delta,carrying_minor=carrying,debit_account=debit,credit_account=credit,
        currency=currency,original_minor=original,base_currency=base,base_minor=booked_minor,fx_rate=rate,fx_source=fx_source,
        booked_on=booked_on,period=period,evidence_hash=evidence_hash,actor_id=actor)
    db.add(row);db.flush()
    if kind!="fx_revaluation" and fx_difference:
        if db.query(JournalEntry).filter_by(business_id=tenant).count()>=20000:raise ValueError("Journal capacity reached")
        debit,credit=("receivables","fx_gain") if fx_difference>0 else ("fx_loss","receivables")
        extra=JournalEntry(business_id=tenant,reference="fx:"+row.id,request_hash=digest([row.id,fx_difference]),kind="fx_difference",
            invoice_id=invoice_id,related_entry_id=row.id,invoice_minor_delta=0,carrying_minor=0,debit_account=debit,credit_account=credit,
            currency=base,original_minor=abs(fx_difference),base_currency=base,base_minor=abs(fx_difference),fx_rate="1",
            fx_source="same_currency",booked_on=booked_on,period=period,evidence_hash=evidence_hash,actor_id=actor)
        db.add(extra);db.flush()
    if invoice:
        remaining=receivable(entries+[row]+([extra] if extra else []))
        if remaining<0:raise ValueError("Negative receivable")
        foreign=next((r for r in entries+[row] if r.kind in RECOGNITION),row).currency!=base
        outstanding_units=sum(r.invoice_minor_delta or 0 for r in entries+[row])
        if remaining==0 and (not foreign or outstanding_units==0):invoice.status="paid";invoice.paid_at=datetime.utcnow()
        else:
            invoice.status="overdue" if invoice.due_date.date()<date.today() else "sent"
            invoice.paid_at=None
    if commit:db.commit()
    return row

def trial_balance(rows,base):
    balances={}
    for row in rows:
        if row.base_currency!=base or row.base_minor<=0 or row.debit_account==row.credit_account:raise ValueError("Invalid journal entry")
        for account,sign in ((row.debit_account,1),(row.credit_account,-1)):
            balances[account]=balances.get(account,0)+sign*row.base_minor
    if sum(balances.values())!=0:raise ValueError("Unbalanced journal")
    return balances

def statement(db,tenant,period):
    period=period_key(period);biz=workspace(db,tenant)
    rows=db.query(JournalEntry).filter_by(business_id=tenant,period=period).order_by(JournalEntry.booked_on,JournalEntry.id).all()
    all_rows=db.query(JournalEntry).filter(JournalEntry.business_id==tenant,JournalEntry.period<=period).order_by(JournalEntry.booked_on,JournalEntry.id).all()
    balances=trial_balance(rows,biz.currency);cumulative=trial_balance(all_rows,biz.currency)
    cash_lines=db.query(BankStatementLine).filter_by(business_id=tenant,period=period).all()
    cash_entries=[r for r in rows if "cash" in (r.debit_account,r.credit_account) and r.kind not in ("opening_cash","opening_overdraft")]
    matched={r.journal_id for r in cash_lines if r.journal_id}
    bank_manifest=[{"id":r.id,"account":r.account,"reference":r.reference,"date":r.booked_on,"currency":r.currency,"signed_minor":r.signed_minor,"source_hash":r.source_hash,"journal_id":r.journal_id} for r in sorted(cash_lines,key=lambda r:r.id)]
    foreign=[]
    by_invoice={}
    for row in all_rows:
        if row.invoice_id:by_invoice.setdefault(row.invoice_id,[]).append(row)
    for invoice_id,entries in sorted(by_invoice.items()):
        origin=next((r for r in entries if r.kind in RECOGNITION),None)
        if origin and origin.currency!=biz.currency:
            units=sum(r.invoice_minor_delta or 0 for r in entries)
            if units>0:
                last=max((r.booked_on for r in entries if r.kind=="fx_revaluation"),default=None)
                foreign.append({"invoice_id":invoice_id,"currency":origin.currency,"outstanding":major(units,origin.currency),"carrying_amount":major(receivable(entries),biz.currency),"last_revaluation":last})
    revenue=-balances.get("revenue",0)-balances.get("sales_returns",0)
    cogs=balances.get("cost_of_sales",0)
    operating=balances.get("operating_expense",0)+balances.get("acquisition_expense",0)
    realized_fx=-balances.get("fx_gain",0)-balances.get("fx_loss",0)
    unrealized_fx=-balances.get("unrealized_fx_gain",0)-balances.get("unrealized_fx_loss",0)
    return {"period":period,"currency":biz.currency,"entry_count":len(rows),
      "trial_balance":{k:major(v,biz.currency) for k,v in sorted(balances.items())},
      "closing_balances":{k:major(v,biz.currency) for k,v in sorted(cumulative.items())},
      "acquisition_expense":major(balances.get("acquisition_expense",0),biz.currency),"revenue":major(revenue,biz.currency),"cost_of_sales":major(cogs,biz.currency),"operating_expenses":major(operating,biz.currency),
      "gross_profit":major(revenue-cogs,biz.currency),"operating_result":major(revenue-cogs-operating,biz.currency),
      "realized_fx_result":major(realized_fx,biz.currency),"unrealized_fx_result":major(unrealized_fx,biz.currency),
      "net_result":major(revenue-cogs-operating+realized_fx+unrealized_fx,biz.currency),
      "cash_balance":major(cumulative.get("cash",0),biz.currency),
      "gross_margin_pct":str((Decimal(revenue-cogs)*100/revenue).quantize(Decimal("0.01"))) if revenue>0 else None,
      "unmatched_bank_lines":sum(not r.journal_id for r in cash_lines),
      "unmatched_cash_entries":sum(r.id not in matched for r in cash_entries),
      "source_entry_ids":[r.id for r in rows],"source_digest":digest([serialize(r) for r in all_rows]),
      "bank_line_ids":[r["id"] for r in bank_manifest],"bank_match_digest":digest(bank_manifest),
      "foreign_receivables":foreign,"fx_revaluation_policy":"Founder-supplied dated rates; no independent FX or period-end valuation certification",
      "bank_verified":False,"basis":"recorded_journal_not_independent_audit"}

def close_period(db,tenant,actor,period,confirmation):
    period=period_key(period)
    if confirmation!="CLOSE "+period:raise ValueError("Exact close confirmation required")
    if period>=date.today().isoformat()[:7]:raise ValueError("Only completed months may close")
    _lock(db,tenant)
    old=db.query(AccountingClose).filter_by(business_id=tenant,period=period).first()
    if old:return serialize_close(old)
    if db.query(AccountingClose.id).filter(AccountingClose.business_id==tenant,AccountingClose.period>period).first():raise ValueError("Cannot close before an already closed later period")
    closed={r[0] for r in db.query(AccountingClose.period).filter_by(business_id=tenant).all()}
    older={r[0] for r in db.query(JournalEntry.period).filter(JournalEntry.business_id==tenant,JournalEntry.period<period).distinct().all()}
    older.update(r[0] for r in db.query(BankStatementLine.period).filter(BankStatementLine.business_id==tenant,BankStatementLine.period<period).distinct().all())
    if older-closed:raise ValueError("Close earlier journal or statement periods first")
    snapshot=statement(db,tenant,period)
    if not snapshot["entry_count"] and not closed:raise ValueError("An initial journal period requires recorded activity or opening balances")
    if snapshot["unmatched_bank_lines"] or snapshot["unmatched_cash_entries"]:raise ValueError("Reconcile all statement and cash entries before close")
    row=AccountingClose(business_id=tenant,period=period,snapshot=snapshot,snapshot_hash=digest(snapshot),actor_id=actor)
    db.add(row);db.commit()
    return serialize_close(row)

def serialize_close(row):
    if digest(row.snapshot)!=row.snapshot_hash:raise ValueError("Closed snapshot integrity failure")
    return {"id":row.id,"period":row.period,"snapshot":row.snapshot,"snapshot_sha256":row.snapshot_hash,
      "closed_at":row.closed_at.isoformat(),"closed_by":row.actor_id,"bank_verified":False}
