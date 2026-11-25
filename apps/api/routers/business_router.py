import os
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from apps.api.core.config import settings
from apps.api.core.database import get_db
from apps.api.services.tenant_resource_budget import consume_tenant_budget
from apps.api.core.auth import get_current_user, require_founder_role
from apps.api.models.business import Business, User
from apps.api.models.entities import Customer, Product, Invoice, Expense, Commitment, Lead
from apps.api.models.goals_tasks import Goal, Task
from apps.api.services.seed_data import seed_northstar_studio, DEMO_BUSINESS_ID
from apps.api.services.financial_metrics import calculate_business_financials
from apps.api.services.financial_reconciliation import reconcile_financial_evidence

router = APIRouter(prefix="/api/business", tags=["Business"])

def compute_financial_health_score(runway_months: float, is_profitable: bool, overdue_ratio: float, active_customers: int) -> int:
    """Computes a grounded 0-100 composite operational health score."""
    score = 0
    # 1. Runway component (max 35 pts)
    if is_profitable or runway_months >= 12.0:
        score += 35
    elif runway_months >= 6.0:
        score += 25
    elif runway_months >= 3.0:
        score += 15
    else:
        score += 5

    # 2. Profitability / Margin component (max 35 pts)
    if is_profitable:
        score += 35
    else:
        score += 15

    # 3. Collections & Receivables Health (max 15 pts)
    if overdue_ratio <= 0.05:
        score += 15
    elif overdue_ratio <= 0.20:
        score += 10
    else:
        score += 3

    # 4. Customer Base Diversity (max 15 pts)
    if active_customers >= 20:
        score += 15
    elif active_customers >= 5:
        score += 10
    else:
        score += 5

    return min(max(score, 0), 100)

@router.get("")
def get_business_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    biz = db.query(Business).filter(Business.id == current_user.business_id).first()
    if not biz:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business profile not found")
    return biz

@router.post("/seed-demo")
def reset_demo(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reset the demo dataset. Strictly guarded to development demo mode and demo founder."""
    is_demo_mode = (
        os.environ.get("ONEBOARD_DEMO_MODE", "").lower() in ("1", "true", "yes")
        or settings.ONEBOARD_DEMO_MODE
    )
    if settings.ONEBOARD_PRODUCTION_MODE or not is_demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo reset is restricted to explicit non-production local demo mode."
        )

    if current_user.business_id != DEMO_BUSINESS_ID or current_user.role != "founder":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo reset is restricted to the demo workspace founder."
        )
    biz = seed_northstar_studio(db, reset=True)
    return {"status": "success", "message": "Demo environment reset to baseline.", "business": biz}

class FinancialReconciliationRequest(BaseModel):
    evidence_csv: str = Field(min_length=1, max_length=262144)
    source_label: str = Field(default="Supplied statement", min_length=1, max_length=100)


@router.post("/financial/reconcile")
def reconcile_financial_records(
    req: FinancialReconciliationRequest,
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db),
):
    """Compare user-provided evidence, without bank verification claims."""
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "financial_reconciliation")
    try:
        return reconcile_financial_evidence(
            db, current_user.business_id, req.evidence_csv, req.source_label
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class SettlementRequest(BaseModel):
    invoice_id: str = Field(min_length=1,max_length=36)
    source_reference: str = Field(min_length=8,max_length=128)
    source_sha256: str = Field(min_length=64,max_length=64)
    evidence_text: str = Field(min_length=1,max_length=262144,repr=False)
    amount: str = Field(min_length=1,max_length=32)
    currency: str = Field(min_length=3,max_length=3)
    fx_rate: str = Field(min_length=1,max_length=32)
    fx_source: str = Field(min_length=1,max_length=200)
    settled_on: str = Field(min_length=10,max_length=10)
    period: str = Field(min_length=7,max_length=7)

@router.post("/financial/settlements")
def add_settlement(req: SettlementRequest, current_user: User = Depends(require_founder_role),
                   db: Session = Depends(get_db)):
    from apps.api.services.settlement_evidence import record_settlement, serialize
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db,current_user.business_id,"financial_reconciliation")
    try:
        return serialize(record_settlement(db,current_user.business_id,**req.model_dump()))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get("/financial/settlements/{period}")
def settlement_summary(period: str,current_user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    from apps.api.services.settlement_evidence import period_summary
    try:
        return period_summary(db,current_user.business_id,period)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get("/operations")
def get_operations_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Actual tenant-owned operations. Never fabricate client counts or deadlines."""
    business_id = current_user.business_id
    biz = db.query(Business).filter(Business.id == business_id).first()
    if biz is None:
        raise HTTPException(status_code=404, detail="Business not found")
    max_rows = 100
    commitments = db.query(Commitment).filter(
        Commitment.business_id == business_id
    ).order_by(Commitment.deadline.asc(), Commitment.id.asc()).limit(max_rows + 1).all()
    customers = db.query(Customer).filter(
        Customer.business_id == business_id
    ).order_by(Customer.created_at.desc(), Customer.id.asc()).limit(max_rows + 1).all()
    leads = db.query(Lead).filter(
        Lead.business_id == business_id
    ).order_by(Lead.created_at.desc(), Lead.id.asc()).limit(max_rows + 1).all()
    return {
        "source": "tenant_application_records_unverified",
        "is_demo": bool(settings.ONEBOARD_DEMO_MODE and business_id == DEMO_BUSINESS_ID),
        "currency": biz.currency or "USD",
        "limits": {"per_category": max_rows, "truncated": {
            "commitments": len(commitments) > max_rows,
            "customers": len(customers) > max_rows,
            "leads": len(leads) > max_rows,
        }},
        "counts": {
            "commitments": db.query(Commitment).filter(Commitment.business_id == business_id).count(),
            "customers": db.query(Customer).filter(Customer.business_id == business_id).count(),
            "leads": db.query(Lead).filter(Lead.business_id == business_id).count(),
        },
        "commitments": [{
            "id": c.id, "title": c.title, "counterparty": c.counterparty,
            "description": c.description, "deadline": c.deadline.isoformat(),
            "status": c.status, "risk_level": c.risk_level,
            "evidence_source": c.evidence_source,
        } for c in commitments[:max_rows]],
        "customers": [{
            "id": c.id, "name": c.name, "company": c.company, "tier": c.tier,
            "mrr": float(c.mrr) if c.mrr is not None else None, "status": c.status,
            # A legacy hard-coded health_score default is not source-backed.
            "health_score": None,
        } for c in customers[:max_rows]],
        "leads": [{
            "id": l.id, "name": l.name, "company": l.company,
            "pipeline_stage": l.pipeline_stage, "source": l.source,
            "estimated_value": float(l.estimated_value) if l.estimated_value is not None else None,
        } for l in leads[:max_rows]],
    }


@router.get("/metrics")
def get_dashboard_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    biz_id = current_user.business_id
    biz = db.query(Business).filter(Business.id == biz_id).first()
    if not biz:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")

    snapshot = calculate_business_financials(db, biz_id)
    goals = db.query(Goal).filter(Goal.business_id == biz_id).all()
    tasks = db.query(Task).filter(Task.business_id == biz_id).all()

    # Do not assign a reassuring health score to an empty, unconfigured account.
    if snapshot["financial_data_status"] != "recorded" or (snapshot["mrr"] == 0 and snapshot["monthly_burn"] == 0):
        health_score = None
    else:
        overdue_ratio = (
            snapshot["overdue_receivables_amount"] / snapshot["mrr"]
            if snapshot["mrr"] > 0 else
            (1.0 if snapshot["overdue_receivables_amount"] > 0 else 0.0)
        )
        health_score = compute_financial_health_score(
            runway_months=snapshot["runway_months"] or 0.0,
            is_profitable=snapshot["net_burn"] <= 0,
            overdue_ratio=overdue_ratio,
            active_customers=snapshot["active_customers_count"],
        )

    return {
        **snapshot,
        "pending_tasks_count": len([task for task in tasks if task.status != "done"]),
        "goals_count": len(goals),
        "health_score": health_score,
        "tenant_id": biz_id,
    }


# Batch K: all financial mutations require founder permission and a tenant-scoped transaction.
from apps.api.services import finance_ledger as ledger, bank_reconciliation as bank, finance_forecasting as forecasts
from apps.api.models.operations import JournalEntry,AccountingClose,BankStatementLine,FinanceForecast
from apps.api.services.tenant_storage import _lock

class JournalRequest(BaseModel):
    reference:str=Field(min_length=8,max_length=128)
    kind:str=Field(min_length=1,max_length=24)
    amount:str=Field(min_length=1,max_length=32)
    currency:str=Field(min_length=3,max_length=3)
    fx_rate:str=Field(default="1",max_length=32)
    fx_source:str=Field(default="same_currency",max_length=200)
    booked_on:str=Field(min_length=10,max_length=10)
    evidence_text:str=Field(min_length=1,max_length=262144,repr=False)
    invoice_id:str|None=Field(default=None,max_length=36)
    related_entry_id:str|None=Field(default=None,max_length=36)

def finance_budget(db,user):
    if settings.ONEBOARD_PRODUCTION_MODE:consume_tenant_budget(db,user.business_id,"financial_reconciliation")

def invalid_finance(db,exc):
    db.rollback()
    raise HTTPException(422,str(exc)) from exc

@router.post("/financial/journal")
def journal_post(req:JournalRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    finance_budget(db,current_user)
    try:return ledger.serialize(ledger.post(db,current_user.business_id,current_user.id,**req.model_dump()))
    except ValueError as exc:invalid_finance(db,exc)

@router.get("/financial/journal")
def journal_list(period:str,offset:int=0,current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    try:ledger.period_key(period)
    except ValueError as exc:invalid_finance(db,exc)
    if not 0<=offset<=20000:raise HTTPException(422,"Invalid page offset")
    rows=db.query(JournalEntry).filter_by(business_id=current_user.business_id,period=period).order_by(JournalEntry.booked_on,JournalEntry.id).offset(offset).limit(101).all()
    return {"records":[ledger.serialize(r) for r in rows[:100]],"next_offset":offset+100 if len(rows)>100 else None}

@router.get("/financial/invoices")
def finance_invoices(current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    tenant=current_user.business_id;_lock(db,tenant)
    rows=db.query(Invoice).filter_by(business_id=tenant).order_by(Invoice.id).limit(501).all()
    return {"records":[{"id":r.id,"invoice_number":r.invoice_number,"customer_name":r.customer_name,"status":r.status,
        "amount":str(r.amount),"outstanding":str(ledger.invoice_balance(db,tenant,r)) if r.amount is not None else None,
        "enrolled":bool(ledger.invoice_entries(db,tenant,r.id))} for r in rows[:500]],"truncated":len(rows)>500}

class InvoiceCreateRequest(BaseModel):
    reference:str=Field(min_length=8,max_length=128)
    invoice_number:str=Field(min_length=1,max_length=50)
    customer_name:str=Field(min_length=1,max_length=255)
    amount:str=Field(min_length=1,max_length=32)
    booked_on:str=Field(min_length=10,max_length=10)
    due_date:str=Field(min_length=10,max_length=10)
    evidence_text:str=Field(min_length=1,max_length=262144,repr=False)

@router.post("/financial/invoices")
def finance_create_invoice(req:InvoiceCreateRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    from datetime import date,datetime
    from apps.api.core.money import cents
    tenant=current_user.business_id;finance_budget(db,current_user);_lock(db,tenant)
    try:
        biz=ledger.workspace(db,tenant);ledger.date_key(req.booked_on)
        due=date.fromisoformat(req.due_date)
        if due.isoformat()!=req.due_date or due.isoformat()<req.booked_on:raise ValueError("Invalid invoice due date")
        cents(req.amount)
        old=db.query(JournalEntry).filter_by(business_id=tenant,reference=req.reference).first()
        if old:
            inv=db.query(Invoice).filter_by(business_id=tenant,id=old.invoice_id).first()
            if not inv or inv.invoice_number!=req.invoice_number or inv.customer_name!=req.customer_name or inv.due_date.date()!=due:raise ValueError("Invoice request reference conflict")
        else:
            if db.query(Invoice.id).filter_by(business_id=tenant,invoice_number=req.invoice_number).first():raise ValueError("Invoice number already exists")
            inv=Invoice(business_id=tenant,invoice_number=req.invoice_number,customer_name=req.customer_name,
                amount=req.amount,status="sent",due_date=datetime.combine(due,datetime.min.time()))
            db.add(inv);db.flush()
        row=ledger.post(db,tenant,current_user.id,reference=req.reference,kind="invoice_issue",amount=req.amount,
            currency=biz.currency,fx_rate="1",fx_source="same_currency",booked_on=req.booked_on,evidence_text=req.evidence_text,invoice_id=inv.id)
        return ledger.serialize(row)
    except ValueError as exc:invalid_finance(db,exc)

@router.get("/financial/periods/{period}")
def financial_period(period:str,current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    tenant=current_user.business_id;_lock(db,tenant)
    try:
        ledger.period_key(period)
        row=db.query(AccountingClose).filter_by(business_id=tenant,period=period).first()
        return {"closed":bool(row),"statement":ledger.serialize_close(row)["snapshot"] if row else ledger.statement(db,tenant,period)}
    except ValueError as exc:invalid_finance(db,exc)

class CloseRequest(BaseModel):
    confirmation:str=Field(max_length=20)
@router.post("/financial/periods/{period}/close")
def financial_close(period:str,req:CloseRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    finance_budget(db,current_user)
    try:return ledger.close_period(db,current_user.business_id,current_user.id,period,req.confirmation)
    except ValueError as exc:invalid_finance(db,exc)

@router.get("/financial/trends")
def finance_trends(current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    rows=db.query(AccountingClose).filter_by(business_id=current_user.business_id).order_by(AccountingClose.period.desc()).limit(60).all()
    return {"periods":[ledger.serialize_close(r) for r in reversed(rows)],"basis":"immutable_closed_periods"}

class BankImportRequest(BaseModel):
    account:str=Field(min_length=1,max_length=80)
    csv_text:str=Field(min_length=1,max_length=262144,repr=False)
    preview:bool=True
@router.post("/financial/bank/import")
def bank_import(req:BankImportRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    finance_budget(db,current_user)
    try:return bank.import_lines(db,current_user.business_id,req.account,req.csv_text,req.preview)
    except ValueError as exc:invalid_finance(db,exc)

@router.get("/financial/bank")
def bank_list(period:str,current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    tenant=current_user.business_id
    try:ledger.period_key(period)
    except ValueError as exc:invalid_finance(db,exc)
    rows=db.query(BankStatementLine).filter_by(business_id=tenant,period=period).order_by(BankStatementLine.id).limit(501).all()
    return {"records":[bank.serialize(r) for r in rows[:500]],"truncated":len(rows)>500}

@router.get("/financial/bank/{line_id}/candidates")
def bank_candidates(line_id:str,current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    tenant=current_user.business_id;row=db.query(BankStatementLine).filter_by(business_id=tenant,id=line_id).first()
    if not row:raise HTTPException(404,"Bank line unavailable")
    return {"candidates":[ledger.serialize(r) for r in bank.candidates(db,tenant,row)]}

class MatchRequest(BaseModel):
    journal_id:str=Field(min_length=1,max_length=36)
@router.post("/financial/bank/{line_id}/match")
def bank_match(line_id:str,req:MatchRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    finance_budget(db,current_user)
    try:return bank.match(db,current_user.business_id,current_user.id,line_id,req.journal_id)
    except ValueError as exc:invalid_finance(db,exc)

class ScenarioAssumption(BaseModel):
    revenue_growth:str=Field(max_length=32)
    expense_growth:str=Field(max_length=32)
    collection_fraction:str=Field(max_length=32)
class ForecastRequest(BaseModel):
    baseline_period:str=Field(min_length=7,max_length=7)
    months:int=Field(ge=1,le=24,strict=True)
    low:ScenarioAssumption
    base:ScenarioAssumption
    high:ScenarioAssumption
@router.post("/financial/forecasts")
def forecast_create(req:ForecastRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    finance_budget(db,current_user)
    try:return forecasts.create(db,current_user.business_id,current_user.id,req.baseline_period,req.months,
        {k:getattr(req,k).model_dump() for k in ("low","base","high")})
    except ValueError as exc:invalid_finance(db,exc)

@router.get("/financial/forecasts")
def forecast_list(current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    rows=db.query(FinanceForecast).filter_by(business_id=current_user.business_id).order_by(FinanceForecast.created_at.desc()).limit(100).all()
    return {"forecasts":[forecasts.serialize(r) for r in rows]}

@router.post("/financial/forecasts/{forecast_id}/observe")
def forecast_observe(forecast_id:str,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    finance_budget(db,current_user)
    try:return forecasts.observe(db,current_user.business_id,current_user.id,forecast_id)
    except ValueError as exc:invalid_finance(db,exc)
