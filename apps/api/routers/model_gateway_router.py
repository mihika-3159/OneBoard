from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
import time
from apps.api.core.database import get_db
from apps.api.services.tenant_resource_budget import consume_tenant_budget
from apps.api.core.config import settings
from apps.api.core.auth import get_current_user, require_founder_role
from apps.api.models.business import User, Business
from apps.api.services.ollama_gateway import ollama_gateway
from apps.api.models.entities import Commitment
from apps.api.models.goals_tasks import Task
from apps.api.services.financial_metrics import calculate_business_financials

router = APIRouter(prefix="/api/ai", tags=["Centralized Model Gateway"])

class SwitchProfileRequest(BaseModel):
    profile: str # lightweight, balanced, high_quality

class FounderCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=8000)

def _business_model_profile(db: Session, business_id: str) -> str:
    """Read a tenant's persisted profile, without modifying global gateway state."""
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    preferences = business.founder_preferences or {}
    profile = preferences.get("model_profile") if isinstance(preferences, dict) else None
    return profile if profile in settings.MODEL_PROFILES else settings.DEFAULT_MODEL_PROFILE


@router.get("/status")
async def get_gateway_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    health = await ollama_gateway.check_health()
    profile = _business_model_profile(db, current_user.business_id)
    requested = ollama_gateway.get_model_for_task(profile=profile)
    installed = requested in health.get("available_models", [])
    # A reachable daemon with a *different* downloaded model cannot execute
    # this tenant's selected profile. Do not advertise inference as ready.
    health["active_profile"] = profile
    health["profile_details"] = settings.MODEL_PROFILES[profile]
    health["requested_model"] = requested
    health["requested_model_installed"] = bool(installed)
    health["inference_available"] = bool(
        health.get("status") == "connected" and installed
    )
    if health.get("status") == "connected" and not installed:
        health["message"] = (
            "The selected profile model is not installed. "
            "Real inference is unavailable for this workspace."
        )
    return health


@router.post("/profile")
def switch_model_profile(
    req: SwitchProfileRequest,
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db)
):
    """Persist model preferences per business, never in process-global state."""
    if req.profile not in settings.MODEL_PROFILES:
        raise HTTPException(status_code=422, detail="Unsupported model profile")
    business = db.query(Business).filter(Business.id == current_user.business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    business.founder_preferences = {**(business.founder_preferences or {}), "model_profile": req.profile}
    db.commit()
    return {
        "status": "success",
        "active_profile": req.profile,
        "profile_details": settings.MODEL_PROFILES[req.profile]
    }

@router.post("/benchmark")
async def benchmark_gateway(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Run a latency benchmark against the Ollama gateway. Requires authentication."""
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "ai_benchmark")
    profile = _business_model_profile(db, current_user.business_id)
    start = time.time()
    res = await ollama_gateway.chat_complete(
        messages=[{"role": "user", "content": "Benchmark test: Return status OK."}],
        system_prompt="Return brief benchmark acknowledgment.",
        model=ollama_gateway.get_model_for_task(profile=profile)
    )
    total_time = round((time.time() - start) * 1000, 2)
    is_simulated = res.get("simulated", False)
    
    return {
        "status": "simulated_fallback" if is_simulated else "passed",
        "inference_available": not is_simulated,
        "fallback_reason": res.get("fallback_reason") if is_simulated else None,
        "active_profile": profile,
        "total_latency_ms": total_time,
        "model": res.get("model"),
        "simulated": is_simulated,
        "inference_engine": "offline_simulated" if is_simulated else "local_ollama",
        "gateway_url": ollama_gateway.base_url
    }

@router.post("/command")
async def handle_founder_command(
    req: FounderCommandRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Founder Command Center: Direct conversational interaction backed by structured business facts."""
    biz_id = current_user.business_id
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, biz_id, "ai_command")
    biz = db.query(Business).filter(Business.id == biz_id).first()
    commitments = db.query(Commitment).filter(Commitment.business_id == biz_id).all()
    tasks = db.query(Task).filter(Task.business_id == biz_id, Task.status != "done").all()

    financials = calculate_business_financials(db, biz_id)
    total_mrr = financials["mrr"]
    critical_commitments = [c for c in commitments if c.risk_level == "critical"]

    biz_name = biz.name if biz else "Your Enterprise"
    cash_val = financials["cash_balance"]
    runway_val = financials['runway_months']
    runway_description = f'{runway_val} months' if runway_val is not None else financials['runway_status']

    data_status = financials["financial_data_status"]
    verified = financials["financial_data_verified"]
    currency = biz.currency if biz and biz.currency else "USD"
    if data_status == "needs_review":
        financial_context = (
            "Financial data require correction: at least one tenant record "
            "is invalid or has an unknown reporting period. All partially "
            "calculated amounts are withheld. Do not estimate runway, "
            "cash health or revenue until records are corrected.\n"
        )
    elif data_status == "unconfigured":
        financial_context = (
            "Financial data have not been configured. No revenue, "
            "cash balance or runway can be inferred.\n"
        )
    else:
        financial_context = (
            f"- User-recorded monthly recurring revenue: {currency} {total_mrr:,.2f} "
            f"across {financials['active_customers_count']} active customer records\n"
            f"- User-recorded cash runway estimate: {runway_description} "
            f"(cash balance: {currency} {cash_val:,.2f})\n"
            f"- User-recorded overdue invoices: {financials['overdue_invoices_count']} "
            f"(amount: {currency} {financials['overdue_receivables_amount']:,.2f})\n"
        )

    context = (
        f"You are the Executive AI Operating System for {biz_name}.\n"
        "Company information below comes from the authenticated business database. "
        "Financial values are self-recorded, not independently reconciled, "
        "and must never be called audited or bank-verified.\n"
        f"Financial record status: {data_status}; independently verified: {verified}.\n"
        f"{financial_context}"
        f"- Critical commitments: {len(critical_commitments)} "
        f"(e.g. {critical_commitments[0].title if critical_commitments else 'None'})\n"
        f"- Pending tasks: {len(tasks)}\n"
        f"Founder question: {req.command}\n"
        "Respond with supported facts and proportionate next steps. "
        "Do not invent provider syncs, bank reconciliations, clients, or "
        "financial health when the underlying records are incomplete."
    )

    profile = _business_model_profile(db, biz_id)
    res = await ollama_gateway.chat_complete(
        messages=[{"role": "user", "content": context}],
        system_prompt="You are OneBoard Founder Command Center.",
        model=ollama_gateway.get_model_for_task(profile=profile)
    )
    is_simulated = res.get("simulated", False)
    
    return {
        "command": req.command,
        "response": res.get("content"),
        "model": res.get("model"),
        "simulated": is_simulated,
        "fallback_reason": res.get("fallback_reason") if is_simulated else None,
        "inference_engine": "offline_simulated" if is_simulated else "local_ollama",
        "business_state_summary": {
            "mrr": total_mrr if data_status == "recorded" else None,
            "overdue_receivables": (
                financials["overdue_receivables_amount"]
                if data_status == "recorded" else None
            ),
            "pending_commitments": len(critical_commitments),
            "financial_data_status": data_status,
            "financial_data_verified": verified,
            "financial_data_issues_count": len(financials["financial_data_issues"]),
            "currency": currency,
        }
    }
