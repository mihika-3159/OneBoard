"""Interactive account controls; no external delivery."""
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from apps.api.core.auth import (get_current_user,verify_password,hash_password,generate_api_key,hash_api_key,
    clear_auth_cookies,check_login_throttle,record_failed_login)
from apps.api.core.database import get_db,scope_tenant_session
from apps.api.models.business import User,UserSession,Business,BusinessMembership,SecurityEvent
from apps.api.services import account_security as security

router=APIRouter(prefix="/api/auth/security",tags=["Account security"])

class Reauth(BaseModel):
    password:str=Field(min_length=1,max_length=1024,repr=False)
    mfa_code:str|None=Field(default=None,max_length=64,repr=False)
class Code(BaseModel):
    code:str=Field(min_length=1,max_length=128,repr=False)
class Recovery(BaseModel):
    email:str=Field(min_length=3,max_length=255)
    recovery_code:str=Field(min_length=1,max_length=64,repr=False)
    new_password:str=Field(min_length=12,max_length=1024,repr=False)
class NewKey(Reauth):
    scopes:list[str]=Field(min_length=1,max_length=2)
    expires_days:int=Field(ge=1,le=90,strict=True)
class Member(Reauth):
    email:str=Field(min_length=3,max_length=255)
    name:str=Field(min_length=1,max_length=255)
    role:str=Field(default="member",max_length=20)
class RoleChange(Reauth):
    role:str=Field(max_length=20)

def _interactive(db):
    if db.info.get("oneboard_api_key"):
        raise HTTPException(403,"Interactive session required")
def _charge(db,key):
    check_login_throttle(key,db)
    record_failed_login(key,db)
def _reauth(db,user,req):
    _interactive(db)
    _charge(db,"account-security:"+user.id)
    if not verify_password(req.password,user.hashed_password) or not security.verify_factor(db,user,req.mfa_code):
        db.rollback()
        raise HTTPException(401,"Reauthentication failed")
def _owner(db,user):
    if not db.query(Business.id).filter_by(id=user.business_id,owner_id=user.id).first():
        raise HTTPException(403,"Workspace owner required")
def _safe_action(db,fn):
    try: return fn()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422,str(exc)) from None

@router.get("")
def status(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _interactive(db)
    row=security.state(db,user)
    return {"mfa_enabled":bool(row and row.mfa_ciphertext),
            "recovery_codes_remaining":len(row.recovery_hashes or []) if row else 0,
            "email_verified":bool(row and row.email_verified_at),"email_delivery_enabled":False,
            "api_key_scopes":row.api_key_scopes if row else None,"api_key_expires_at":row.api_key_expires_at if row else None}

@router.post("/mfa/start")
def start_mfa(req:Reauth,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    return {"secret":_safe_action(db,lambda:security.start_mfa(db,user)),"expires_in_seconds":600}

@router.post("/mfa/confirm")
def confirm_mfa(req:Code,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _interactive(db)
    _charge(db,"account-security:"+user.id)
    return {"recovery_codes":_safe_action(db,lambda:security.confirm_mfa(db,user,req.code))}

@router.post("/mfa/disable")
def disable_mfa(req:Reauth,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    return _safe_action(db,lambda:security.disable_mfa(db,user))

@router.post("/recovery-codes")
def rotate_codes(req:Reauth,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    return {"recovery_codes":security.rotate_recovery(db,user)}

@router.post("/recover")
def recover(req:Recovery,request:Request,response:Response,db:Session=Depends(get_db)):
    email=req.email.strip().lower()
    source=request.client.host if request.client else "unknown"
    from apps.api.core.config import settings
    if settings.ONEBOARD_PRODUCTION_MODE:
        _charge(db,"global-auth-admission")
    _charge(db,"account-recovery-source:"+source)
    _charge(db,"account-recovery:"+email)
    from apps.api.core.tenant_context import restricted,lookup
    if restricted(db):
        found=lookup(db,"email",email)
        if not found: raise HTTPException(401,"Recovery failed")
        db.info["oneboard_exclusive_lifecycle"]=True
        scope_tenant_session(db,found.tenant)
        user=db.query(User).filter_by(id=found.uid,business_id=found.tenant,is_active=True).first()
    else:
        user=db.query(User).filter_by(email=email,is_active=True).first()
    if not user: raise HTTPException(401,"Recovery failed")
    from apps.api.core.auth import _require_active_membership
    try: _require_active_membership(user,db)
    except HTTPException: raise HTTPException(401,"Recovery failed") from None
    db.info["oneboard_exclusive_lifecycle"]=True
    scope_tenant_session(db,user.business_id)
    if not security.reset_with_recovery(db,user,req.recovery_code,req.new_password):
        db.rollback()
        raise HTTPException(401,"Recovery failed")
    clear_auth_cookies(response)
    return {"password_reset":True,"sessions_revoked":True,"api_key_revoked":True}

@router.post("/email/stage")
def stage_email(req:Reauth,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    return _safe_action(db,lambda:security.stage_email_verification(db,user))

@router.post("/email/verify")
def verify_email(req:Code,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _interactive(db)
    _charge(db,"account-security:"+user.id)
    if not security.verify_email(db,user,req.code):
        db.rollback()
        raise HTTPException(422,"Verification challenge invalid or expired")
    return {"email_verified":True}

@router.get("/sessions")
def sessions(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _interactive(db)
    rows=db.query(UserSession).filter_by(user_id=user.id,business_id=user.business_id,is_revoked=False).filter(UserSession.expires_at>datetime.utcnow()).order_by(UserSession.created_at.desc()).limit(100).all()
    return [{"id":r.id,"created_at":r.created_at,"expires_at":r.expires_at} for r in rows]

@router.post("/sessions/revoke-all")
def revoke_all(req:Reauth,response:Response,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    count=security.revoke_sessions(db,user)
    security._record(db,user,"all_sessions_revoked")
    db.commit()
    clear_auth_cookies(response)
    return {"revoked":count}

@router.post("/sessions/{session_id}/revoke")
def revoke_session(session_id:str,req:Reauth,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    row=db.query(UserSession).filter_by(id=session_id,user_id=user.id,business_id=user.business_id).first()
    if not row: raise HTTPException(404,"Session not found")
    row.is_revoked=True
    security._record(db,user,"session_revoked")
    db.commit()
    return {"revoked":True}

@router.post("/api-key")
def rotate_api_key(req:NewKey,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    if not set(req.scopes)<=security.SCOPES or len(req.scopes)!=len(set(req.scopes)):
        raise HTTPException(422,"Invalid API key scopes")
    row=security.state(db,user,True)
    key=generate_api_key()
    user.api_key=hash_api_key(key)
    row.api_key_scopes=sorted(req.scopes)
    row.api_key_expires_at=datetime.utcnow()+timedelta(days=req.expires_days)
    security._record(db,user,"api_key_rotated")
    result={"api_key":key,"scopes":row.api_key_scopes,"expires_at":row.api_key_expires_at}
    db.commit()
    return result

@router.post("/api-key/revoke")
def revoke_api_key(req:Reauth,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    user.api_key=None
    security._record(db,user,"api_key_revoked")
    db.commit()
    return {"revoked":True}

@router.get("/members")
def members(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _interactive(db)
    _owner(db,user)
    return [{"id":m.id,"name":m.name,"email":m.email,"role":m.role,"active":m.is_active} for m in db.query(User).filter_by(business_id=user.business_id).order_by(User.id).limit(200).all()]

@router.post("/members")
def create_member(req:Member,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    _owner(db,user)
    if req.role not in ("member","founder") or "@" not in req.email:
        raise HTTPException(422,"Invalid member role or email")
    email=req.email.strip().lower()
    from apps.api.core.tenant_context import restricted,lookup
    if (lookup(db,"email",email) if restricted(db) else db.query(User.id).filter_by(email=email).first()):
        raise HTTPException(409,"Account already exists")
    import secrets
    member=User(email=email,name=req.name.strip(),role=req.role,business_id=user.business_id,
                hashed_password=hash_password(secrets.token_urlsafe(48)),is_active=True,api_key=None)
    db.add(member)
    db.flush()
    db.add(BusinessMembership(user_id=member.id,business_id=user.business_id,role=req.role))
    row=security.state(db,member,True)
    codes=security._new_recovery(row)
    row.recovery_hashes=row.recovery_hashes[:1]
    security._record(db,user,"member_created")
    result={"id":member.id,"activation_recovery_code":codes[0],"delivery_verified":False}
    db.commit()
    return result

@router.put("/members/{member_id}/role")
def member_role(member_id:str,req:RoleChange,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    _owner(db,user)
    if member_id==user.id or req.role not in ("member","founder"):
        raise HTTPException(422,"Owner role cannot be changed")
    member=db.query(User).filter_by(id=member_id,business_id=user.business_id).first()
    membership=db.query(BusinessMembership).filter_by(user_id=member_id,business_id=user.business_id).first()
    if not member or not membership: raise HTTPException(404,"Member not found")
    member.role=membership.role=req.role
    member.api_key=None
    security.revoke_sessions(db,member)
    security._record(db,user,"member_role_changed")
    db.commit()
    return {"updated":True}

@router.post("/members/{member_id}/revoke")
def revoke_member(member_id:str,req:Reauth,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _reauth(db,user,req)
    _owner(db,user)
    if member_id==user.id: raise HTTPException(422,"Owner cannot revoke own membership")
    member=db.query(User).filter_by(id=member_id,business_id=user.business_id).first()
    if not member: raise HTTPException(404,"Member not found")
    member.is_active=False
    member.api_key=None
    security.revoke_sessions(db,member)
    db.query(BusinessMembership).filter_by(user_id=member.id,business_id=user.business_id).delete()
    security._record(db,user,"member_revoked")
    db.commit()
    return {"revoked":True}

@router.get("/audit")
def audit(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _interactive(db)
    _owner(db,user)
    rows=db.query(SecurityEvent).filter_by(business_id=user.business_id).order_by(SecurityEvent.sequence.desc()).limit(100).all()
    return {"chain_valid":security.verify_chain(db,user.business_id),"externally_anchored":False,
            "events":[{"sequence":r.sequence,"user_id":r.user_id,"event":r.event,"event_hash":r.event_hash,"created_at":r.created_at} for r in rows]}
