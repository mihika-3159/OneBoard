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

class ProviderCredentialRequest(BaseModel):
    provider: str = Field(max_length=30)
    scopes: list[str] = Field(min_length=1,max_length=8)
    token: str = Field(min_length=1,max_length=4096,repr=False)
    expires_at: datetime

class ProviderIntentRequest(BaseModel):
    provider: str = Field(max_length=30)
    scope: str = Field(max_length=100)
    idempotency_key: str = Field(min_length=8,max_length=128)

@router.post("/providers/credential")
def save_provider_credential(req: ProviderCredentialRequest,current_user: User = Depends(require_founder_role),
                             db: Session = Depends(get_db)):
    from apps.api.services.provider_staging import store_credential
    from apps.api.services.data_lifecycle import owner
    try:
        owner(db,current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db,current_user.business_id,"customer_import")
    try:
        return store_credential(db,current_user.business_id,**req.model_dump())
    except ValueError:
        db.rollback()
        raise HTTPException(status_code=422,detail="Invalid provider credential or encryption configuration") from None

@router.delete("/providers/credential/{provider}")
def remove_provider_credential(provider:str,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    from apps.api.services.provider_staging import revoke_credential
    from apps.api.services.data_lifecycle import owner
    try:
        owner(db,current_user)
        return revoke_credential(db,current_user.business_id,provider)
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post("/providers/intent")
def stage_provider_intent(req: ProviderIntentRequest,current_user: User = Depends(require_founder_role),
                          db: Session = Depends(get_db)):
    from apps.api.services.provider_staging import stage_intent
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db,current_user.business_id,"customer_import")
    try:
        return stage_intent(db,current_user.business_id,req.provider,req.scope,req.idempotency_key)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422,detail=str(exc)) from exc

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


# Batch L: explicit operator-configured live adapter lifecycle.
from fastapi import Request
from fastapi.responses import RedirectResponse
from apps.api.services.integrations import provider_runtime as runtime
from apps.api.services.integrations.provider_transport import CAPABILITIES,configuration
from apps.api.models.operations import (ProviderConnection,ProviderSyncJob,ProviderRecord,ProviderRecordConflict,ProviderDelivery)
from apps.api.services.data_lifecycle import owner
from apps.api.core.database import scope_tenant_session

def live_owner(db,user):
    if db.info.get('oneboard_api_key'):raise HTTPException(403,'Interactive owner session required')
    try:owner(db,user)
    except PermissionError:raise HTTPException(403,"Workspace owner required") from None
    if settings.ONEBOARD_PRODUCTION_MODE:consume_tenant_budget(db,user.business_id,"customer_import")

def live_error(db):
    db.rollback()
    raise HTTPException(422,"Provider request rejected; inspect integration diagnostics") from None

@router.get("/providers/live")
def live_providers(current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    rows={r.provider:r for r in db.query(ProviderConnection).filter_by(business_id=current_user.business_id).all()}
    result=[]
    for provider,(scopes,actions) in CAPABILITIES.items():
        try:configuration(provider);configured=True
        except ValueError:configured=False
        info=runtime.public(rows[provider]) if provider in rows else {"provider":provider,"state":"disconnected","scopes":[]}
        result.append({**info,"external_adapter_configured":configured,"supported_scopes":sorted(scopes),"supported_actions":actions,"adapter_contract":"normalized_https_adapter"})
    return {"providers":result}

class OAuthBegin(BaseModel):
    provider:str=Field(max_length=30)
    scopes:list[str]=Field(min_length=1,max_length=16)
@router.post("/providers/oauth/start")
def oauth_start(req:OAuthBegin,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    live_owner(db,current_user)
    try:return runtime.start_authorization(db,current_user.business_id,current_user.id,req.provider,req.scopes)
    except ValueError:live_error(db)

@router.get("/providers/oauth/callback")
def oauth_callback(state:str,code:str|None=None,error:str|None=None,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    # Actor-bound, single-use state is CSRF protection for the OAuth redirect.
    live_owner(db,current_user)
    result="failed"
    try:
        runtime.complete_authorization(db,current_user.business_id,current_user.id,state,code,denied=error is not None)
        result="connected"
    except ValueError:db.rollback()
    return RedirectResponse("/?provider_oauth="+result,status_code=303)

class ProviderName(BaseModel):
    provider:str=Field(max_length=30)
@router.post("/providers/live/disconnect")
def live_disconnect(req:ProviderName,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    live_owner(db,current_user)
    try:return runtime.disconnect(db,current_user.business_id,req.provider)
    except ValueError:live_error(db)

@router.post("/providers/live/rotate")
def live_rotate(current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    live_owner(db,current_user)
    try:return runtime.rotate_keys(db,current_user.business_id)
    except ValueError:live_error(db)

class SyncRequest(BaseModel):
    provider:str=Field(max_length=30)
    request_key:str=Field(min_length=8,max_length=128)
@router.post("/providers/live/sync")
def live_sync(req:SyncRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    live_owner(db,current_user)
    try:return runtime.sync_public(runtime.enqueue(db,current_user.business_id,req.provider,req.request_key))
    except ValueError:live_error(db)

@router.post("/providers/live/sync/{job_id}/retry")
def live_retry(job_id:str,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    live_owner(db,current_user)
    try:return runtime.retry_sync(db,current_user.business_id,job_id)
    except ValueError:live_error(db)

@router.get("/providers/live/{provider}/diagnostics")
def live_diagnostics(provider:str,offset:int=0,current_user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    tenant=current_user.business_id
    if not 0<=offset<=20000:raise HTTPException(422,"Invalid page offset")
    try:row=runtime.connection(db,tenant,provider)
    except ValueError:raise HTTPException(404,"Provider connection unavailable") from None
    def rows(model,order,limit=100):
        return db.query(model).filter_by(business_id=tenant,connection_id=row.id).order_by(order).offset(offset).limit(limit+1).all()
    jobs=rows(ProviderSyncJob,ProviderSyncJob.created_at.desc())
    records=rows(ProviderRecord,ProviderRecord.id)
    conflicts=rows(ProviderRecordConflict,ProviderRecordConflict.created_at.desc())
    actions=rows(ProviderDelivery,ProviderDelivery.created_at.desc())
    return {"connection":runtime.public(row),"jobs":[runtime.sync_public(j) for j in jobs[:100]],
        "records":[{"id":r.id,"remote_id":r.remote_id,"revision":r.revision,"payload":r.payload,"source_hash":r.payload_hash} for r in records[:100]],
        "conflicts":[{"id":c.id,"record_id":c.record_id,"state":c.state,"incoming_revision":c.incoming_revision,"incoming_payload":c.incoming_payload} for c in conflicts[:100]],
        "deliveries":[runtime.delivery_public(a) for a in actions[:100]],
        "next_offset":offset+100 if any(len(x)>100 for x in (jobs,records,conflicts,actions)) else None}

class ResolveProviderConflict(BaseModel):
    choice:str=Field(max_length=30)
@router.post("/providers/live/conflicts/{conflict_id}/resolve")
def live_resolve(conflict_id:str,req:ResolveProviderConflict,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    live_owner(db,current_user)
    try:return runtime.resolve_conflict(db,current_user.business_id,conflict_id,req.choice)
    except ValueError:live_error(db)

class DeliveryRequest(BaseModel):
    provider:str=Field(max_length=30)
    action:str=Field(max_length=50)
    payload:dict
    request_key:str=Field(min_length=8,max_length=128)
    confirmation:str=Field(max_length=100)
@router.post("/providers/live/actions")
def live_action(req:DeliveryRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    live_owner(db,current_user)
    try:return runtime.approve_action(db,current_user.business_id,current_user.id,**req.model_dump())
    except ValueError:live_error(db)

@router.post("/providers/live/actions/{action_id}/reconcile")
def live_reconcile(action_id:str,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    live_owner(db,current_user)
    try:return runtime.reconcile_delivery(db,current_user.business_id,action_id)
    except ValueError:live_error(db)

@router.post("/providers/live/actions/{action_id}/cancel")
def live_cancel(action_id:str,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    live_owner(db,current_user)
    try:return runtime.cancel_action(db,current_user.business_id,action_id)
    except ValueError:live_error(db)

@router.post("/providers/webhook/{provider}/{tenant}/{connection_id}")
async def live_webhook(provider:str,tenant:str,connection_id:str,request:Request,db:Session=Depends(get_db)):
    import re
    if len(provider)>30 or not re.fullmatch(r"[A-Za-z0-9_-]{1,36}",tenant) or not re.fullmatch(r"[A-Za-z0-9_-]{1,36}",connection_id):
        raise HTTPException(401,"Invalid webhook")
    timestamps=request.headers.getlist("x-oneboard-timestamp");signatures=request.headers.getlist("x-oneboard-signature")
    if len(timestamps)!=1 or len(signatures)!=1:raise HTTPException(401,"Invalid webhook")
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>32768:raise HTTPException(413,"Webhook exceeds limit")
    try:runtime.webhook_signature(provider,tenant,connection_id,timestamps[0],bytes(body),signatures[0])
    except ValueError:raise HTTPException(401,"Invalid webhook") from None
    db.info["oneboard_worker"]=True
    scope_tenant_session(db,tenant)
    try:return runtime.accept_webhook(db,tenant,provider,connection_id,bytes(body))
    except ValueError:live_error(db)
