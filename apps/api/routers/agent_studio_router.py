from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from apps.api.core.database import get_db
from apps.api.core.auth import get_current_user, enforce_tenant_boundary
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
    system_prompt: str
    selected_model: str = "qwen2.5:7b"
    allowed_tools: List[str] = []
    requires_approval_for: List[str] = []
    max_steps: int = 5

class AgentGenerateRequest(BaseModel):
    prompt: str

class AgentTestRequest(BaseModel):
    test_input: str

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = CustomAgent(
        business_id=current_user.business_id,
        name=req.name,
        role_title=req.role_title,
        department=req.department,
        description=req.description,
        system_prompt=req.system_prompt,
        selected_model=req.selected_model,
        allowed_tools=req.allowed_tools,
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
):
    return await natural_language_builder.generate_agent_from_prompt(req.prompt)

@router.post("/{agent_id}/test")
async def test_agent(
    agent_id: str,
    req: AgentTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(CustomAgent).filter(CustomAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    enforce_tenant_boundary(agent.business_id, current_user)

    res = await ollama_gateway.chat_complete(
        messages=[{"role": "user", "content": req.test_input}],
        system_prompt=agent.system_prompt,
        model=agent.selected_model
    )
    return {
        "agent_name": agent.name,
        "input": req.test_input,
        "output": res.get("content"),
        "model_used": res.get("model"),
        "simulated": res.get("simulated", False),
        "inference_engine": "offline_simulated" if res.get("simulated") else "local_ollama"
    }

@router.post("/{agent_id}/toggle-status")
def toggle_agent_status(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(CustomAgent).filter(CustomAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    enforce_tenant_boundary(agent.business_id, current_user)

    agent.status = "paused" if agent.status == "active" else "active"
    db.commit()
    return {"id": agent.id, "status": agent.status}
