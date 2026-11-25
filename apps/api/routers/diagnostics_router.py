"""Tenant-local operational counts; never expose credentials or global tenant data."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.core.auth import require_founder_role
from apps.api.core.database import get_db
from apps.api.models.business import User
from apps.api.models.operations import SideEffectOutbox, ScheduledJobLease, SemanticVector
from apps.api.models.memory import MemoryChunk
from apps.api.models.workflow import WorkflowRun

router=APIRouter(prefix="/api/diagnostics",tags=["Private diagnostics"])

@router.get("/operations")
def operations_diagnostics(user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    tenant=user.business_id
    monitor=db.get(ScheduledJobLease,"proactive_health_check")
    return {
        "monitor":{"last_success_epoch":monitor.last_success_at if monitor else None,
                   "next_due_epoch":monitor.next_due_at if monitor else None,
                   "scope":"shared_process_monitor_not_tenant_specific"},
        "local_draft_intents_pending":db.query(SideEffectOutbox).filter_by(business_id=tenant,state="pending").count(),
        "workflow_runs":db.query(WorkflowRun).filter_by(business_id=tenant).count(),
        "memory_chunks":db.query(MemoryChunk).filter_by(business_id=tenant).count(),
        "indexed_vectors":db.query(SemanticVector).filter_by(business_id=tenant).count(),
        "external_delivery_verified":False,
    }
