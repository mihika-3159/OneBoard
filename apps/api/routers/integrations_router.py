from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import datetime
from apps.api.core.database import get_db
from apps.api.services.tenant_resource_budget import consume_tenant_budget
from apps.api.core.config import settings
from apps.api.services.seed_data import DEMO_BUSINESS_ID
from apps.api.core.auth import get_current_user, enforce_tenant_boundary, require_founder_role
from apps.api.models.business import User
from apps.api.models.integrations import IntegrationAccount
from apps.api.services.customer_csv_import import import_customer_csv
from apps.api.services.integrations.demo_adapters import (
    demo_crm, demo_finance, demo_email, demo_calendar,
    github_adapter, notion_adapter, chat_import_adapter
)

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])

def _require_fixture_tenant(current_user: User) -> None:
    """Prevent static Northstar fixtures from masquerading as tenant records.

    A logged-in user of another business has no permission to read the
    demonstration contacts, mock ledger, or fictional GitHub repository,
    even in development. Production never exposes the fixtures at all.
    """
    if (settings.ONEBOARD_PRODUCTION_MODE
            or not settings.ONEBOARD_DEMO_MODE
            or current_user.business_id != DEMO_BUSINESS_ID):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The demonstration adapter is not available in this workspace.",
        )


class CustomerCSVImportRequest(BaseModel):
    csv_text: str = Field(min_length=1, max_length=1_048_576)
    idempotency_key: str = Field(min_length=8, max_length=128)
    source_name: str = Field(default="User CSV", min_length=1, max_length=100)
    dry_run: bool = True


@router.post("/local/customers/import")
def import_local_customers(
    req: CustomerCSVImportRequest,
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db),
):
    """Actual tenant-scoped CSV import; not a live CRM OAuth connection."""
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "customer_import")
    try:
        return import_customer_csv(
            db, current_user.business_id, req.csv_text, req.idempotency_key,
            source_name=req.source_name, dry_run=req.dry_run
        )
    except ValueError as exc:
        db.rollback()
        code = 409 if "already used" in str(exc) else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


class ChatImportRequest(BaseModel):
    conversation_text: str = Field(min_length=1, max_length=1_000_000)

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
    current_user: User = Depends(require_founder_role),
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
    _require_fixture_tenant(current_user)
    return {
        "is_simulated": True,
        "source": "demo_crm_adapter",
        "contacts": demo_crm.get_contacts()
    }

@router.get("/finance/ledger")
def get_finance_ledger(current_user: User = Depends(get_current_user)):
    _require_fixture_tenant(current_user)
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
        "outbox": demo_email.get_outbox(current_user.business_id)
    }

@router.get("/github/status")
def get_github_status(current_user: User = Depends(get_current_user)):
    _require_fixture_tenant(current_user)
    return {
        "is_simulated": True,
        "source": "local_mock_github_adapter",
        **github_adapter.get_repo_status()
    }
