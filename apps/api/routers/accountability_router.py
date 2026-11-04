from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from apps.api.core.database import get_db
from apps.api.core.auth import get_current_user, enforce_tenant_boundary
from apps.api.models.business import User
from apps.api.models.decision_evidence import Decision
from apps.api.services.accountability_engine import accountability_engine

router = APIRouter(prefix="/api/accountability", tags=["Accountability & Outcomes"])

class OutcomeVerificationRequest(BaseModel):
    decision_id: str
    metric_name: str
    actual_value: float
    notes: Optional[str] = None

@router.get("/decisions")
def get_accountability_decisions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Decision).filter(
        Decision.business_id == current_user.business_id
    ).order_by(Decision.created_at.desc()).all()

@router.get("/scorecards")
def get_adviser_scorecards(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return accountability_engine.get_scorecards(db, current_user.business_id)

@router.post("/verify-outcome")
def verify_outcome(
    req: OutcomeVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    decision = db.query(Decision).filter(Decision.id == req.decision_id).first()
    if not decision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision record not found")

    enforce_tenant_boundary(decision.business_id, current_user)

    try:
        res = accountability_engine.record_actual_outcome(
            db=db,
            decision_id=req.decision_id,
            metric_name=req.metric_name,
            actual_value=req.actual_value,
            outcome_notes=req.notes
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
