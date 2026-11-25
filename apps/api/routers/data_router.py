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

@router.get("/retention")
def get_retention(current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    _owner(db,current_user)
    row=db.get(DataRetentionPolicy,current_user.business_id)
    return {"document_days":row.document_days if row else None}

@router.put("/retention")
def update_retention(req:RetentionRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    _owner(db,current_user)
    return lifecycle.set_retention(db,current_user.business_id,req.document_days)

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

@router.post("/delete-workspace")
def delete_workspace(req:DeleteRequest,current_user:User=Depends(require_founder_role),db:Session=Depends(get_db)):
    from apps.api.core.auth import verify_password
    _owner(db,current_user)
    from apps.api.core.config import settings
    from apps.api.services.tenant_resource_budget import consume_tenant_budget
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db,current_user.business_id,"workspace_delete")
    if not verify_password(req.password,current_user.hashed_password):
        raise HTTPException(status_code=403,detail="Password verification failed")
    try:
        return lifecycle.delete_workspace(db,current_user,req.confirmation)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422,detail=str(exc)) from exc
