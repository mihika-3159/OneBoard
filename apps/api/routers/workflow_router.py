from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from apps.api.core.database import get_db
from apps.api.models.workflow import WorkflowDefinition, WorkflowRun, ApprovalRequest
from apps.api.services.workflow_engine import workflow_engine
from apps.api.services.natural_language_builder import natural_language_builder
from apps.api.services.seed_data import DEMO_BUSINESS_ID

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])

class WorkflowCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    category: str = "Operations"
    trigger_type: str = "manual"
    trigger_config: Dict[str, Any] = {}
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]

class PromptGenerationRequest(BaseModel):
    prompt: str

class TeachProcessRequest(BaseModel):
    description: str
    examples: Optional[str] = None

class ApprovalActionRequest(BaseModel):
    action: str # "approve", "reject"
    notes: Optional[str] = None

@router.get("")
def list_workflows(db: Session = Depends(get_db)):
    return db.query(WorkflowDefinition).filter(WorkflowDefinition.business_id == DEMO_BUSINESS_ID).all()

@router.post("")
def create_workflow(req: WorkflowCreateRequest, db: Session = Depends(get_db)):
    validation = workflow_engine.validate_workflow({"nodes": req.nodes, "edges": req.edges})
    if not validation.get("is_valid"):
        raise HTTPException(status_code=400, detail=validation.get("error"))

    wf = WorkflowDefinition(
        business_id=DEMO_BUSINESS_ID,
        name=req.name,
        description=req.description,
        category=req.category,
        trigger_type=req.trigger_type,
        trigger_config=req.trigger_config,
        nodes=req.nodes,
        edges=req.edges,
        is_valid=True
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf

@router.post("/{workflow_id}/execute")
def execute_workflow(workflow_id: str, dry_run: bool = False, db: Session = Depends(get_db)):
    try:
        run = workflow_engine.execute_workflow(
            db=db,
            business_id=DEMO_BUSINESS_ID,
            workflow_id=workflow_id,
            dry_run=dry_run
        )
        return run
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/runs")
def list_runs(db: Session = Depends(get_db)):
    return db.query(WorkflowRun).filter(WorkflowRun.business_id == DEMO_BUSINESS_ID).order_by(WorkflowRun.started_at.desc()).all()

@router.post("/generate")
async def generate_from_prompt(req: PromptGenerationRequest):
    generated = await natural_language_builder.generate_workflow_from_prompt(req.prompt)
    return generated

@router.post("/teach-process")
async def teach_process(req: TeachProcessRequest):
    return await natural_language_builder.teach_a_process(req.description, req.examples)

@router.get("/approvals")
def get_pending_approvals(db: Session = Depends(get_db)):
    return db.query(ApprovalRequest).filter(
        ApprovalRequest.business_id == DEMO_BUSINESS_ID,
        ApprovalRequest.status == "pending"
    ).all()

@router.post("/approvals/{request_id}/action")
def resolve_approval(request_id: str, req: ApprovalActionRequest, db: Session = Depends(get_db)):
    approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if req.action == "approve" and approval.workflow_run_id:
        run = workflow_engine.approve_and_resume_run(db, approval.workflow_run_id, request_id)
        return {"status": "approved", "run": run}
    else:
        approval.status = "rejected"
        approval.reviewer_notes = req.notes
        db.commit()
        return {"status": "rejected", "request_id": request_id}

@router.get("/templates")
def get_workflow_templates():
    return [
        {"id": "t1", "name": "Weekly Financial Review & Burn Tracking", "category": "Finance", "description": "Compiles MRR, cash balance, and burn rate, identifying variances."},
        {"id": "t2", "name": "Invoice Overdue Follow-up Sequence", "category": "Finance", "description": "Identifies past-due invoices and drafts reminders with human approval."},
        {"id": "t3", "name": "Customer Support SLA Triage", "category": "Support", "description": "Tags urgent technical tickets and suggests resolutions based on past documentation."},
        {"id": "t4", "name": "Customer Onboarding Health Check", "category": "Customer Success", "description": "Audits account telemetry 7 days after signup to prevent early stall."},
        {"id": "t5", "name": "Marketing Campaign Attribution Review", "category": "Growth", "description": "Monitors CAC against target unit economics and flags discrepancies."},
        {"id": "t6", "name": "Commitment & Contract Deliverables Monitor", "category": "Operations", "description": "Tracks deliverables promised in contracts against sprint velocity."},
        {"id": "t7", "name": "Pricing Policy Consistency Auditor", "category": "Operations", "description": "Audits quotes, sheets, and contracts for mismatched tier pricing."},
        {"id": "t8", "name": "Executive Council Weekly Agenda Builder", "category": "Executive", "description": "Aggregates key metrics and outstanding hazards for council deliberation."}
    ]
