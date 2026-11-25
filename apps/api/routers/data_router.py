from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from apps.api.core.database import get_db
from apps.api.core.auth import require_founder_role
from apps.api.models.business import User
from apps.api.services import data_lifecycle as lifecycle
from apps.api.models.operations import DataRetentionPolicy

router=APIRouter(prefix="/api/data",tags=["Workspace Data"])

def _owner(db,user):
    try:
        return lifecycle.owner(db,user)
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc

@router.get("/export")
def export_manifest(current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    _owner(db,current_user)
    return {"tables":lifecycle.export_tables(),"secrets_excluded":True,"snapshot_consistent":False}

@router.get("/export-snapshot")
def export_snapshot(current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    from fastapi.responses import Response
    from apps.api.core.config import settings
    from apps.api.services.tenant_resource_budget import consume_tenant_budget
    _owner(db,current_user)
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db,current_user.business_id,"data_export")
    try:
        return Response(content=lifecycle.export_snapshot(db,current_user),media_type="application/json",
                        headers={"Content-Disposition":"attachment; filename=oneboard-workspace.json","Cache-Control":"no-store"})
    except ValueError as exc:
        raise HTTPException(status_code=413,detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc

@router.get("/export/{table}")
def export_page(table:str,offset:int=Query(0,ge=0,le=1000000),limit:int=Query(50,ge=1,le=100),
                current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    _owner(db,current_user)
    try:
        return lifecycle.export_page(db,current_user.business_id,table,offset,limit)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc

class RetentionRequest(BaseModel):
    document_days:int|None=Field(default=None,ge=30,le=3650,strict=True)
    resolved_alert_days:int|None=Field(default=None,ge=30,le=3650,strict=True)
    expired_session_days:int|None=Field(default=None,ge=30,le=3650,strict=True)
    completed_sync_days:int|None=Field(default=None,ge=30,le=3650,strict=True)
    resolved_conflict_days:int|None=Field(default=None,ge=30,le=3650,strict=True)
    completed_draft_days:int|None=Field(default=None,ge=30,le=3650,strict=True)
    performance_sample_days:int|None=Field(default=None,ge=30,le=3650,strict=True)

@router.get("/retention")
def get_retention(current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    _owner(db,current_user)
    row=db.get(DataRetentionPolicy,current_user.business_id)
    return {field:getattr(row,field) if row else None for field in lifecycle.RETENTION_FIELDS}

@router.put("/retention")
def update_retention(req:RetentionRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    _owner(db,current_user)
    return lifecycle.set_retention(db,current_user.business_id,req.document_days,req.resolved_alert_days,req.expired_session_days,req.completed_sync_days,req.resolved_conflict_days,req.completed_draft_days,req.performance_sample_days)

@router.delete("/documents/{document_id}")
def delete_document(document_id:str,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    _owner(db,current_user)
    count=lifecycle.delete_documents(db,current_user.business_id,[document_id])
    if not count:
        db.rollback()
        raise HTTPException(status_code=404,detail="Document missing or inaccessible")
    db.commit()
    return {"deleted":True,"backup_copies_deleted":False}

class DeleteRequest(BaseModel):
    confirmation:str=Field(min_length=8,max_length=80)
    password:str=Field(min_length=1,max_length=1024,repr=False)
    mfa_code:str|None=Field(default=None,max_length=64,repr=False)

@router.post("/delete-workspace")
def delete_workspace(req:DeleteRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    from apps.api.core.auth import verify_password
    _owner(db,current_user)
    from apps.api.core.config import settings
    from apps.api.services.tenant_resource_budget import consume_tenant_budget
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db,current_user.business_id,"workspace_delete")
    from apps.api.core.tenant_context import password_verifier
    from apps.api.services.account_security import verify_factor
    if not verify_password(req.password,password_verifier(db,current_user)) or not verify_factor(db,current_user,req.mfa_code):
        raise HTTPException(status_code=403,detail="Password verification failed")
    try:
        return lifecycle.delete_workspace(db,current_user,req.confirmation)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422,detail=str(exc)) from exc


from fastapi import Request
from fastapi.responses import Response
from apps.api.services import portable_archive as portable
from apps.api.models.operations import PortableArchive

def portable_owner(db,user):
    _owner(db,user)
    if db.info.get("oneboard_api_key"):raise HTTPException(403,"Interactive owner session required")
def portable_error(db,exc):
    db.rollback()
    raise HTTPException(422,str(exc) if isinstance(exc,ValueError) else "Portable archive request rejected") from None
@router.post("/portable/export")
def capture_portable(current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    from apps.api.core.config import settings
    from apps.api.services.tenant_resource_budget import consume_tenant_budget
    portable_owner(db,current_user)
    if settings.ONEBOARD_PRODUCTION_MODE:consume_tenant_budget(db,current_user.business_id,"data_export")
    try:return portable.capture(db,current_user)
    except (ValueError,PermissionError) as exc:portable_error(db,exc)
@router.get("/portable")
def list_portable(current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    from datetime import datetime
    portable_owner(db,current_user)
    rows=db.query(PortableArchive).filter(PortableArchive.business_id==current_user.business_id,PortableArchive.expires_at>datetime.utcnow()).order_by(PortableArchive.created_at.desc()).limit(4).all()
    return {"archives":[portable.manifest_public(row) for row in rows]}
@router.get("/portable/{archive_id}")
def portable_progress(archive_id:str,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    portable_owner(db,current_user)
    try:return portable.progress(db,current_user.business_id,archive_id)
    except ValueError as exc:portable_error(db,exc)
@router.get("/portable/{archive_id}/pages/{number}")
def portable_download(archive_id:str,number:int,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    portable_owner(db,current_user)
    try:content,checksum=portable.download(db,current_user.business_id,archive_id,number)
    except ValueError as exc:portable_error(db,exc)
    return Response(content,media_type="application/json",headers={"X-Archive-SHA256":checksum,"Content-Disposition":f'attachment; filename="page-{number:04d}.json"'})
@router.delete("/portable/{archive_id}")
def portable_delete(archive_id:str,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    portable_owner(db,current_user)
    try:return portable.discard(db,current_user.business_id,archive_id)
    except ValueError as exc:portable_error(db,exc)
async def bounded_json(request,limit):
    import json
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit:raise HTTPException(413,"Portable request exceeds byte limit")
    try:return json.loads(raw)
    except (ValueError,RecursionError):raise HTTPException(422,"Invalid portable JSON") from None
@router.post("/portable/import")
async def begin_portable_import(request:Request,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    portable_owner(db,current_user)
    manifest=await bounded_json(request,2*1024*1024)
    try:return portable.begin_import(db,current_user,manifest)
    except ValueError as exc:portable_error(db,exc)
@router.put("/portable/{archive_id}/pages/{number}")
async def upload_portable_page(archive_id:str,number:int,request:Request,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    portable_owner(db,current_user)
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>portable.MAX_PAGE:raise HTTPException(413,"Portable page exceeds byte limit")
    try:return portable.upload(db,current_user.business_id,archive_id,number,raw.decode("utf-8"))
    except (ValueError,UnicodeError) as exc:portable_error(db,exc)
class RestoreRequest(DeleteRequest):
    archive_id:str=Field(min_length=1,max_length=36)
@router.post("/portable/restore")
def restore_portable(req:RestoreRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    from apps.api.core.auth import verify_password
    from apps.api.core.tenant_context import password_verifier
    from apps.api.services.account_security import verify_factor
    from apps.api.core.config import settings
    from apps.api.services.tenant_resource_budget import consume_tenant_budget
    portable_owner(db,current_user)
    if settings.ONEBOARD_PRODUCTION_MODE:consume_tenant_budget(db,current_user.business_id,"workspace_delete")
    if not verify_password(req.password,password_verifier(db,current_user)) or not verify_factor(db,current_user,req.mfa_code):raise HTTPException(403,"Password verification failed")
    try:return portable.restore(db,current_user,req.archive_id,req.confirmation)
    except ValueError as exc:portable_error(db,exc)


@router.get("/collections/{collection}")
def browse_collection(collection:str,cursor:str|None=None,limit:int=Query(50,ge=1,le=100),current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    from apps.api.services.storage_maintenance import collection_page
    try:return collection_page(db,current_user.business_id,collection,cursor,limit)
    except ValueError as exc:portable_error(db,exc)
