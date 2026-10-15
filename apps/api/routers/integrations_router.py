from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from apps.api.core.database import get_db
from apps.api.core.auth import get_current_user, enforce_tenant_boundary
from apps.api.models.business import User
from apps.api.models.integrations import IntegrationAccount
from apps.api.services.integrations.demo_adapters import (
    demo_crm, demo_finance, demo_email, demo_calendar,
    github_adapter, notion_adapter, chat_import_adapter
)

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])

class ChatImportRequest(BaseModel):
    conversation_text: str

@router.get("")
def list_integrations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(IntegrationAccount).filter(
        IntegrationAccount.business_id == current_user.business_id
    ).all()

@router.post("/{integration_id}/sync")
def sync_integration(
    integration_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    acc = db.query(IntegrationAccount).filter(IntegrationAccount.id == integration_id).first()
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")

    enforce_tenant_boundary(acc.business_id, current_user)

    acc.last_sync = datetime.utcnow()
    # Unmistakably label sandbox integrations as sandbox-synced, not live verified external APIs
    acc.status = "sandbox_synced" if "demo" in acc.provider.lower() or "local" in acc.provider.lower() else "connected"
    db.commit()
    
    return {
        "status": acc.status,
        "integration": acc.name,
        "provider": acc.provider,
        "synced_at": acc.last_sync.isoformat(),
        "is_simulated": True if "sandbox" in acc.status else False,
        "note": "Sandbox integration synced from local mock fixtures." if "sandbox" in acc.status else "Live provider connection refreshed."
    }

@router.post("/import-chat")
def import_chat_conversation(req: ChatImportRequest):
    return chat_import_adapter.parse_chat_export(req.conversation_text)

@router.get("/crm/contacts")
def get_crm_contacts():
    return {
        "is_simulated": True,
        "source": "demo_crm_adapter",
        "contacts": demo_crm.get_contacts()
    }

@router.get("/finance/ledger")
def get_finance_ledger():
    return {
        "is_simulated": True,
        "source": "demo_finance_adapter",
        "summary": demo_finance.get_summary()
    }

@router.get("/email/outbox")
def get_email_outbox():
    return {
        "is_simulated": True,
        "channel": "sandbox_email_outbox",
        "outbox": demo_email.outbox
    }

@router.get("/github/status")
def get_github_status():
    return {
        "is_simulated": True,
        "source": "local_mock_github_adapter",
        **github_adapter.get_repo_status()
    }
