from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import time
from apps.api.core.database import get_db
from apps.api.core.config import settings
from apps.api.services.ollama_gateway import ollama_gateway
from apps.api.services.seed_data import DEMO_BUSINESS_ID
from apps.api.models.business import Business
from apps.api.models.entities import Customer, Invoice, Commitment
from apps.api.models.goals_tasks import Task

router = APIRouter(prefix="/api/ai", tags=["Centralized Model Gateway"])

class SwitchProfileRequest(BaseModel):
    profile: str # lightweight, balanced, high_quality

class FounderCommandRequest(BaseModel):
    command: str

@router.get("/status")
async def get_gateway_status():
    return await ollama_gateway.check_health()

@router.post("/profile")
def switch_model_profile(req: SwitchProfileRequest):
    if req.profile in settings.MODEL_PROFILES:
        ollama_gateway.active_profile = req.profile
        return {
            "status": "success",
            "active_profile": req.profile,
            "profile_details": settings.MODEL_PROFILES[req.profile]
        }
    return {"status": "error", "message": f"Invalid profile: {req.profile}"}

@router.post("/benchmark")
async def benchmark_gateway():
    start = time.time()
    res = await ollama_gateway.chat_complete(
        messages=[{"role": "user", "content": "Benchmark test: Return status OK."}],
        system_prompt="Return brief benchmark acknowledgment."
    )
    total_time = round((time.time() - start) * 1000, 2)
    return {
        "status": "passed",
        "total_latency_ms": total_time,
        "model": res.get("model"),
        "simulated": res.get("simulated", False),
        "gateway_url": ollama_gateway.base_url
    }

@router.post("/command")
async def handle_founder_command(req: FounderCommandRequest, db: Session = Depends(get_db)):
    """Founder Command Center: Direct conversational interaction backed by structured business facts."""
    biz = db.query(Business).filter(Business.id == DEMO_BUSINESS_ID).first()
    customers = db.query(Customer).filter(Customer.business_id == DEMO_BUSINESS_ID).all()
    invoices = db.query(Invoice).filter(Invoice.business_id == DEMO_BUSINESS_ID).all()
    commitments = db.query(Commitment).filter(Commitment.business_id == DEMO_BUSINESS_ID).all()
    tasks = db.query(Task).filter(Task.business_id == DEMO_BUSINESS_ID, Task.status != "done").all()

    total_mrr = sum(c.mrr for c in customers if c.status == "active")
    overdue_invoices = [i for i in invoices if i.status == "overdue"]
    critical_commitments = [c for c in commitments if c.risk_level == "critical"]

    context = (
        f"You are the Executive AI Operating System for Northstar Studio.\n"
        f"Real Business Context:\n"
        f"- MRR: ${total_mrr:,.2f} across {len(customers)} customers\n"
        f"- Cash Runway: {biz.runway_months if biz else 7.2} months (Balance: ${biz.current_cash_balance if biz else 132840:,.2f})\n"
        f"- Overdue Invoices: {len(overdue_invoices)} totaling ${sum(i.amount for i in overdue_invoices):,.2f}\n"
        f"- Critical Commitments: {len(critical_commitments)} (e.g. {critical_commitments[0].title if critical_commitments else 'None'})\n"
        f"- Pending Tasks: {len(tasks)}\n"
        f"Founder Question: {req.command}\n"
        f"Respond concisely with concrete facts and recommended next steps."
    )

    res = await ollama_gateway.chat_complete(
        messages=[{"role": "user", "content": context}],
        system_prompt="You are OneBoard Founder Command Center."
    )
    return {
        "command": req.command,
        "response": res.get("content"),
        "model": res.get("model"),
        "simulated": res.get("simulated", False),
        "business_state_summary": {
            "mrr": total_mrr,
            "overdue_receivables": sum(i.amount for i in overdue_invoices),
            "pending_commitments": len(critical_commitments)
        }
    }
