from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from apps.api.core.database import get_db
from apps.api.models.agent_council import CouncilMeeting
from apps.api.services.council_engine import council_engine, COUNCIL_ROLES
from apps.api.services.seed_data import DEMO_BUSINESS_ID

router = APIRouter(prefix="/api/council", tags=["AI Executive Council"])

class DeliberationRequest(BaseModel):
    title: str
    meeting_type: str = "weekly_executive_review"
    topic: str
    selected_advisers: Optional[List[str]] = None

class ApprovalRequestPayload(BaseModel):
    decision_notes: Optional[str] = None

@router.get("/roles")
def get_council_roles():
    return [
        {"name": k, **v} for k, v in COUNCIL_ROLES.items()
    ]

@router.get("/meetings")
def get_council_meetings(db: Session = Depends(get_db)):
    return db.query(CouncilMeeting).filter(CouncilMeeting.business_id == DEMO_BUSINESS_ID).order_by(CouncilMeeting.created_at.desc()).all()

@router.post("/deliberate")
async def convene_council_meeting(req: DeliberationRequest, db: Session = Depends(get_db)):
    meeting = await council_engine.conduct_deliberation(
        db=db,
        business_id=DEMO_BUSINESS_ID,
        title=req.title,
        meeting_type=req.meeting_type,
        topic=req.topic,
        selected_advisers=req.selected_advisers
    )
    return meeting

@router.post("/meetings/{meeting_id}/approve")
def approve_meeting(meeting_id: str, payload: ApprovalRequestPayload, db: Session = Depends(get_db)):
    try:
        decision = council_engine.approve_meeting_decision(
            db=db,
            business_id=DEMO_BUSINESS_ID,
            meeting_id=meeting_id,
            decision_notes=payload.decision_notes
        )
        return {"status": "success", "decision": decision}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
