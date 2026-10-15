from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from apps.api.core.database import get_db
from apps.api.models.integrations import IntegrationAccount
from apps.api.services.integrations.demo_adapters import (
    demo_crm, demo_finance, demo_email, demo_calendar,
    github_adapter, notion_adapter, chat_import_adapter
)
from apps.api.services.seed_data import DEMO_BUSINESS_ID

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])

class ChatImportRequest(BaseModel):
    conversation_text: str

@router.get("")
def list_integrations(db: Session = Depends(get_db)):
    return db.query(IntegrationAccount).filter(IntegrationAccount.business_id == DEMO_BUSINESS_ID).all()

@router.post("/{integration_id}/sync")
def sync_integration(integration_id: str, db: Session = Depends(get_db)):
    acc = db.query(IntegrationAccount).filter(IntegrationAccount.id == integration_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Integration not found")

    acc.last_sync = datetime.utcnow()
    acc.status = "connected"
    db.commit()
    return {"status": "synced", "integration": acc.name, "synced_at": acc.last_sync.isoformat()}

@router.post("/import-chat")
def import_chat_conversation(req: ChatImportRequest):
    return chat_import_adapter.parse_chat_export(req.conversation_text)

@router.get("/crm/contacts")
def get_crm_contacts():
    return demo_crm.get_contacts()

@router.get("/finance/ledger")
def get_finance_ledger():
    return demo_finance.get_summary()

@router.get("/email/outbox")
def get_email_outbox():
    return demo_email.outbox

@router.get("/github/status")
def get_github_status():
    return github_adapter.get_repo_status()
