from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from apps.api.core.database import get_db
from apps.api.core.auth import get_current_user, enforce_tenant_boundary
from apps.api.models.business import User
from apps.api.models.agent_council import CouncilMeeting
from apps.api.services.council_engine import council_engine, COUNCIL_ROLES

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
def get_council_meetings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(CouncilMeeting).filter(
        CouncilMeeting.business_id == current_user.business_id
    ).order_by(CouncilMeeting.created_at.desc()).all()

@router.post("/deliberate")
async def convene_council_meeting(
    req: DeliberationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    meeting = await council_engine.conduct_deliberation(
        db=db,
        business_id=current_user.business_id,
        title=req.title,
        meeting_type=req.meeting_type,
        topic=req.topic,
        selected_advisers=req.selected_advisers
    )
    return meeting

@router.post("/meetings/{meeting_id}/approve")
def approve_meeting(
    meeting_id: str,
    payload: ApprovalRequestPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    meeting = db.query(CouncilMeeting).filter(CouncilMeeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    enforce_tenant_boundary(meeting.business_id, current_user)

    try:
        decision = council_engine.approve_meeting_decision(
            db=db,
            business_id=current_user.business_id,
            meeting_id=meeting_id,
            decision_notes=payload.decision_notes
        )
        return {"status": "success", "decision": decision}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
