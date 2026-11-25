from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
from apps.api.core.config import settings
from apps.api.services.tenant_resource_budget import consume_tenant_budget
from apps.api.core.database import get_db
from apps.api.core.auth import get_current_user, enforce_tenant_boundary, require_founder_role
from apps.api.models.business import User
from apps.api.models.workflow import WorkflowDefinition, WorkflowRun, ApprovalRequest
from apps.api.services.workflow_engine import workflow_engine
from apps.api.services.natural_language_builder import natural_language_builder

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
    prompt: str = Field(min_length=1, max_length=8000)

class TeachProcessRequest(BaseModel):
    description: str = Field(min_length=1, max_length=8000)
    examples: Optional[str] = Field(default=None, max_length=16000)

class ApprovalActionRequest(BaseModel):
    action: Literal["approve", "reject"]
    notes: Optional[str] = None

@router.get("")
def list_workflows(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(WorkflowDefinition).filter(
        WorkflowDefinition.business_id == current_user.business_id
    ).all()

@router.post("")
def create_workflow(
    req: WorkflowCreateRequest,
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db)
):
    validation = workflow_engine.validate_workflow({"nodes": req.nodes, "edges": req.edges})
    if not validation.get("is_valid"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=validation.get("error"))

    if settings.ONEBOARD_PRODUCTION_MODE:
        from apps.api.services.tenant_storage import check_resource
        check_resource(db, current_user.business_id, "workflow")
    wf = WorkflowDefinition(
        business_id=current_user.business_id,
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

class ScheduleRequest(BaseModel):
    cron: str = Field(min_length=9,max_length=40)
    timezone: str = Field(min_length=1,max_length=64)
    enabled: bool = True

@router.put("/{workflow_id}/schedule")
def configure_schedule(workflow_id: str, req: ScheduleRequest,
                       current_user: User=Depends(require_founder_role),db: Session=Depends(get_db)):
    from apps.api.services.workflow_schedule import configure
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db,current_user.business_id,"workflow_generate")
    try:
        return configure(db,current_user.business_id,workflow_id,req.cron,req.timezone,req.enabled)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get("/schedules")
def list_schedules(current_user: User=Depends(get_current_user),db: Session=Depends(get_db)):
    from apps.api.models.operations import WorkflowSchedule
    from apps.api.services.workflow_schedule import serialize
    return [serialize(row) for row in db.query(WorkflowSchedule).filter_by(business_id=current_user.business_id).limit(200).all()]

@router.post("/{workflow_id}/execute")
def execute_workflow(
    workflow_id: str,
    dry_run: bool = False,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db)
):
    wf = db.query(WorkflowDefinition).filter(WorkflowDefinition.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    enforce_tenant_boundary(wf.business_id, current_user)
    if settings.ONEBOARD_PRODUCTION_MODE and not dry_run and not idempotency_key:
        raise HTTPException(
            status_code=428,
            detail="A stable Idempotency-Key is required for production workflow execution.",
        )

    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "workflow_execute")
    try:
        run = workflow_engine.execute_workflow(
            db=db,
            business_id=current_user.business_id,
            workflow_id=workflow_id,
            dry_run=dry_run,
            idempotency_key=idempotency_key
        )
        return run
    except (PermissionError, ValueError) as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN if isinstance(pe, PermissionError) else status.HTTP_400_BAD_REQUEST, detail=str(pe))
    except Exception:
        logger.exception("Unexpected workflow execution error")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Workflow execution failed; inspect server logs")

@router.post("/runs/reconcile-interrupted")
def reconcile_interrupted_runs(
    older_than_seconds: int = 900,
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db),
):
    """Quarantine stale, uncertain executions without automatic replay."""
    try:
        count = workflow_engine.reconcile_interrupted_runs(
            db, current_user.business_id, older_than_seconds=older_than_seconds
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"paused_runs": count, "automatic_replay": False}


@router.get("/runs")
def list_runs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(WorkflowRun).filter(
        WorkflowRun.business_id == current_user.business_id
    ).order_by(WorkflowRun.started_at.desc()).all()

@router.post("/generate")
async def generate_from_prompt(
    req: PromptGenerationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "workflow_generate")
    generated = await natural_language_builder.generate_workflow_from_prompt(req.prompt)
    return generated

@router.post("/teach-process")
async def teach_process(
    req: TeachProcessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "workflow_generate")
    return await natural_language_builder.teach_a_process(req.description, req.examples)

@router.get("/outbox")
def list_local_outbox(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from apps.api.models.operations import SideEffectOutbox
    rows = db.query(SideEffectOutbox).filter(
        SideEffectOutbox.business_id == current_user.business_id
    ).order_by(SideEffectOutbox.created_at.desc()).limit(100).all()
    return [{"id": row.id, "run_id": row.run_id, "step_id": row.step_id,
             "kind": row.kind, "state": row.state, "delivered": False}
            for row in rows]


@router.get("/approvals")
def get_pending_approvals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(ApprovalRequest).filter(
        ApprovalRequest.business_id == current_user.business_id,
        ApprovalRequest.status == "pending"
    ).all()

@router.post("/approvals/{request_id}/action")
def resolve_approval(
    request_id: str,
    req: ApprovalActionRequest,
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db)
):
    approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    enforce_tenant_boundary(approval.business_id, current_user)
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval already resolved")

    if req.action == "approve":
        if not approval.workflow_run_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Approval is not associated with a workflow run"
            )
        try:
            run = workflow_engine.approve_and_resume_run(
                db=db,
                run_id=approval.workflow_run_id,
                request_id=request_id,
                business_id=current_user.business_id
            )
            return {"status": "approved", "run": run}
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc)
            ) from exc

    # Rejecting a workflow gate must terminate its run, not strand it in
    # awaiting_approval. Claim the pending request and run in one transaction.
    run = None
    if approval.workflow_run_id:
        run = db.query(WorkflowRun).filter(
            WorkflowRun.id == approval.workflow_run_id,
            WorkflowRun.business_id == current_user.business_id,
        ).first()
        if (
            not run
            or run.status != "awaiting_approval"
            or run.current_step_id != (approval.payload or {}).get("step_id")
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approval checkpoint is no longer pending"
            )

    now = datetime.utcnow()
    claimed = db.query(ApprovalRequest).filter(
        ApprovalRequest.id == request_id,
        ApprovalRequest.business_id == current_user.business_id,
        ApprovalRequest.status == "pending",
    ).update(
        {"status": "rejected", "reviewer_notes": req.notes, "reviewed_at": now},
        synchronize_session=False,
    )
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval already resolved")
    if run:
        run_claimed = db.query(WorkflowRun).filter(
            WorkflowRun.id == run.id,
            WorkflowRun.business_id == current_user.business_id,
            WorkflowRun.status == "awaiting_approval",
        ).update(
            {
                "status": "failed",
                "error_message": "Founder rejected workflow approval",
                "completed_at": now,
                "verified_success": False,
            },
            synchronize_session=False,
        )
        if run_claimed != 1:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run already resolved")
        results = dict(run.step_results or {})
        results[run.current_step_id] = {
            "status": "rejected", "request_id": request_id, "timestamp": now.isoformat()
        }
        db.query(WorkflowRun).filter(WorkflowRun.id == run.id).update(
            {"step_results": results}, synchronize_session=False
        )
    db.commit()
    return {"status": "rejected", "request_id": request_id}


@router.get("/templates")
def get_workflow_templates(current_user: User = Depends(get_current_user)):
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
