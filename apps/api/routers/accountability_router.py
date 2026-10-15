from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from apps.api.core.database import get_db
from apps.api.models.decision_evidence import Decision
from apps.api.services.accountability_engine import accountability_engine
from apps.api.services.seed_data import DEMO_BUSINESS_ID

router = APIRouter(prefix="/api/accountability", tags=["Accountability & Outcomes"])

class OutcomeVerificationRequest(BaseModel):
    decision_id: str
    metric_name: str
    actual_value: float
    notes: Optional[str] = None

@router.get("/decisions")
def get_accountability_decisions(db: Session = Depends(get_db)):
    return db.query(Decision).filter(Decision.business_id == DEMO_BUSINESS_ID).order_by(Decision.created_at.desc()).all()

@router.get("/scorecards")
def get_adviser_scorecards(db: Session = Depends(get_db)):
    return accountability_engine.get_scorecards(db, DEMO_BUSINESS_ID)

@router.post("/verify-outcome")
def verify_outcome(req: OutcomeVerificationRequest, db: Session = Depends(get_db)):
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
        raise HTTPException(status_code=400, detail=str(e))
