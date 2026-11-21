import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from apps.api.core.config import settings
from apps.api.core.database import get_db
from apps.api.core.auth import get_current_user
from apps.api.models.business import Business, User
from apps.api.models.entities import Customer, Product, Invoice, Expense
from apps.api.models.goals_tasks import Goal, Task
from apps.api.services.seed_data import seed_northstar_studio, DEMO_BUSINESS_ID
from apps.api.services.financial_metrics import calculate_business_financials

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
    if not is_demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo reset is disabled in production mode. Set ONEBOARD_DEMO_MODE=true for local development only."
        )

    if current_user.business_id != DEMO_BUSINESS_ID or current_user.role != "founder":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo reset is restricted to the demo workspace founder."
        )
    biz = seed_northstar_studio(db, reset=True)
    return {"status": "success", "message": "Demo environment reset to baseline.", "business": biz}

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
    if snapshot["financial_data_status"] == "unconfigured" or (snapshot["mrr"] == 0 and snapshot["monthly_burn"] == 0):
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
