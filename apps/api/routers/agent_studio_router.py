from apps.api.services.inference_stream import stream_or_wait
from apps.api.services import agent_runtime
from apps.api.models.agent_council import AgentRun
from fastapi import Request, APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from apps.api.services.inference_budget import inference_tenant
from apps.api.services.untrusted_content import DATA_BOUNDARY, quoted_data
from typing import List, Optional
from apps.api.core.database import get_db
from apps.api.core.config import settings
from apps.api.services.tenant_resource_budget import consume_tenant_budget
from apps.api.core.auth import get_current_user, enforce_tenant_boundary, require_founder_role
from apps.api.models.business import User
from apps.api.models.workflow import CustomAgent
from apps.api.services.natural_language_builder import natural_language_builder
from apps.api.services.ollama_gateway import ollama_gateway

router = APIRouter(prefix="/api/agents", tags=["Agent Studio"])

class AgentCreateRequest(BaseModel):
    name: str
    role_title: str
    department: str = "Operations"
    description: Optional[str] = None
    system_prompt: str = Field(min_length=1,max_length=8000)
    selected_model: str = "qwen2.5:7b"
    allowed_tools: List[str] = []
    allowed_memory_collections: List[str] = Field(default_factory=list, max_length=50)
    requires_approval_for: List[str] = []
    max_steps: int = Field(default=5,ge=1,le=25)

class AgentGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1,max_length=8000)

class AgentTestRequest(BaseModel):
    test_input: str = Field(min_length=1,max_length=8000)
    cache_text: bool = False

@router.get("")
def list_agents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(CustomAgent).filter(
        CustomAgent.business_id == current_user.business_id
    ).all()

@router.post("")
def create_agent(
    req: AgentCreateRequest,
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db)
):
    if settings.ONEBOARD_PRODUCTION_MODE:
        from apps.api.services.tenant_storage import check_resource
        check_resource(db, current_user.business_id, "agent")
    agent = CustomAgent(
        business_id=current_user.business_id,
        name=req.name,
        role_title=req.role_title,
        department=req.department,
        description=req.description,
        system_prompt=req.system_prompt,
        selected_model=req.selected_model,
        allowed_tools=req.allowed_tools,
        allowed_memory_collections=req.allowed_memory_collections,
        requires_approval_for=req.requires_approval_for,
        max_steps=req.max_steps,
        status="active"
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent

@router.post("/generate")
async def generate_agent_config(
    req: AgentGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "agent_generate")
    async def work():
        with inference_tenant(current_user.business_id):
            return await natural_language_builder.generate_agent_from_prompt(req.prompt)
    return await stream_or_wait(request, work)

@router.post("/{agent_id}/test")
async def test_agent(
    agent_id: str,
    req: AgentTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    agent = db.query(CustomAgent).filter(CustomAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    enforce_tenant_boundary(agent.business_id, current_user)

    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "agent_test")
    async def work():
        with inference_tenant(current_user.business_id):
            res = await ollama_gateway.chat_complete(
                messages=[{"role": "user", "content": quoted_data("agent_configuration",agent.system_prompt)+"\n"+quoted_data("test_input",req.test_input)}],
                system_prompt="You are a text-only OneBoard sandbox. "+DATA_BOUNDARY,
                model=agent.selected_model,
                **({"cache_text": True} if req.cache_text else {})
            )
        return {
            "agent_name": agent.name,
            "tool_execution_enabled": False,
            "granted_tools": [],
            "input": req.test_input,
            "output": res.get("content"),
            "model_used": res.get("model"),
            "simulated": res.get("simulated", False),
            "inference_engine": "offline_simulated" if res.get("simulated") else res.get("provider_protocol", "local_ollama"),
            "cache_hit": bool(res.get("cache_hit"))
        }
    return await stream_or_wait(request, work, provider_stream=not req.cache_text)


@router.post("/{agent_id}/toggle-status")
def toggle_agent_status(
    agent_id: str,
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db)
):
    agent = db.query(CustomAgent).filter(CustomAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    enforce_tenant_boundary(agent.business_id, current_user)

    agent.status = "paused" if agent.status == "active" else "active"
    db.commit()
    return {"id": agent.id, "status": agent.status}


class RuntimeStep(BaseModel):
    agent_id: str = Field(min_length=1, max_length=36)
    tool: str = Field(min_length=1, max_length=50)
    document_id: str | None = Field(default=None, max_length=36)


class RuntimeStart(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    steps: list[RuntimeStep] = Field(min_length=1, max_length=12)


@router.post("/{agent_id}/runs")
def start_agent_run(agent_id: str, req: RuntimeStart, current_user: User = Depends(require_founder_role), db: Session = Depends(get_db)):
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "agent_run")
    try:
        return agent_runtime.serialize(agent_runtime.plan_run(db, current_user.business_id, agent_id, req.goal,
            [s.model_dump() for s in req.steps], req.idempotency_key))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs")
def list_agent_runs(current_user: User = Depends(require_founder_role), db: Session = Depends(get_db)):
    rows = db.query(AgentRun.id).filter_by(business_id=current_user.business_id, approval_state="runtime_read_only")\
        .order_by(AgentRun.created_at.desc()).limit(50).all()
    return [agent_runtime.serialize(agent_runtime.expire_or_recover(db, current_user.business_id, row[0])) for row in rows]


@router.get("/runs/{run_id}")
def get_agent_run(run_id: str, current_user: User = Depends(require_founder_role), db: Session = Depends(get_db)):
    run = agent_runtime.expire_or_recover(db, current_user.business_id, run_id)
    if not run:
        raise HTTPException(404, "Run unavailable")
    return agent_runtime.serialize(run)


@router.post("/runs/{run_id}/advance")
async def advance_agent_run(run_id: str, current_user: User = Depends(require_founder_role), db: Session = Depends(get_db), request: Request = None):
    if not agent_runtime.get_run(db, current_user.business_id, run_id):
        raise HTTPException(404, "Run unavailable")
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "agent_run")
    async def work():
        run = await agent_runtime.advance(db, current_user.business_id, run_id)
        return agent_runtime.serialize(run)
    return await stream_or_wait(request, work, provider_stream=False)


@router.post("/runs/{run_id}/cancel")
def cancel_agent_run(run_id: str, current_user: User = Depends(require_founder_role), db: Session = Depends(get_db)):
    run = agent_runtime.cancel(db, current_user.business_id, run_id)
    if not run:
        raise HTTPException(404, "Run unavailable")
    return agent_runtime.serialize(run)
