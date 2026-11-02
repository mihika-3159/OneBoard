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
    accounts = db.query(IntegrationAccount).filter(
        IntegrationAccount.business_id == current_user.business_id
    ).all()
    # Never return provider configuration: it may contain credentials.
    # Legacy seeded mocks were stored as "connected" without live provider access.
    return [
        {
            "id": acc.id,
            "connector_type": acc.connector_type,
            "name": acc.name,
            "status": (
                "sandbox_ready" if acc.is_mock and acc.status == "connected"
                else "unavailable" if not acc.is_mock and acc.status == "connected"
                else acc.status
            ),
            "is_mock": bool(acc.is_mock),
            "granted_scopes": acc.granted_scopes,
            "last_sync": acc.last_sync,
            "records_synced": acc.records_synced,
            "error_message": acc.error_message,
        }
        for acc in accounts
    ]

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

    # This repository currently has only local/demo adapters. There is no
    # authenticated provider sync implementation for live accounts. Never
    # fabricate a successful refresh or advance last_sync for one.
    if not acc.is_mock:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Live provider synchronization is not implemented. No data was synced."
        )

    acc.last_sync = datetime.utcnow()
    acc.status = "sandbox_synced"
    db.commit()

    return {
        "status": acc.status,
        "integration": acc.name,
        "provider": acc.connector_type,
        "synced_at": acc.last_sync.isoformat(),
        "is_simulated": True,
        "note": "Sandbox refresh only. No external provider was contacted."
    }

@router.post("/import-chat")
def import_chat_conversation(
    req: ChatImportRequest,
    current_user: User = Depends(get_current_user)
):
    return chat_import_adapter.parse_chat_export(req.conversation_text)

@router.get("/crm/contacts")
def get_crm_contacts(current_user: User = Depends(get_current_user)):
    return {
        "is_simulated": True,
        "source": "demo_crm_adapter",
        "contacts": demo_crm.get_contacts()
    }

@router.get("/finance/ledger")
def get_finance_ledger(current_user: User = Depends(get_current_user)):
    return {
        "is_simulated": True,
        "source": "demo_finance_adapter",
        "summary": demo_finance.get_summary()
    }

@router.get("/email/outbox")
def get_email_outbox(current_user: User = Depends(get_current_user)):
    return {
        "is_simulated": True,
        "channel": "sandbox_email_outbox",
        "outbox": demo_email.outbox
    }

@router.get("/github/status")
def get_github_status(current_user: User = Depends(get_current_user)):
    return {
        "is_simulated": True,
        "source": "local_mock_github_adapter",
        **github_adapter.get_repo_status()
    }
