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
            "mrr": c.mrr, "status": c.status,
            # A legacy hard-coded health_score default is not source-backed.
            "health_score": None,
        } for c in customers[:max_rows]],
        "leads": [{
            "id": l.id, "name": l.name, "company": l.company,
            "pipeline_stage": l.pipeline_stage, "source": l.source,
            "estimated_value": l.estimated_value,
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
