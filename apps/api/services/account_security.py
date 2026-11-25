"""Account security primitives. No network delivery, no raw secrets in exports."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from datetime import datetime,timedelta
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from apps.api.core.config import settings
from apps.api.models.business import AccountSecurity,SecurityEvent,UserSession
from apps.api.services.tenant_storage import _lock
from fastapi import HTTPException

SCOPES={"read","write"}
def _key():
    try: value=base64.b64decode(settings.ACCOUNT_SECURITY_KEY,validate=True)
    except (ValueError,TypeError): value=b""
    if len(value)!=32:
        raise ValueError("Account security encryption is not configured")
    return value

def _encrypt(user_id,purpose,value):
    nonce=secrets.token_bytes(12)
    return base64.b64encode(nonce+AESGCM(_key()).encrypt(nonce,value.encode(),(user_id+":"+purpose).encode())).decode()

def _decrypt(user_id,purpose,value):
    data=base64.b64decode(value,validate=True)
    return AESGCM(_key()).decrypt(data[:12],data[12:],(user_id+":"+purpose).encode()).decode()

def state(db,user,create=False):
    row=db.query(AccountSecurity).filter_by(user_id=user.id,business_id=user.business_id).first()
    if row is None and create:
        row=AccountSecurity(user_id=user.id,business_id=user.business_id,recovery_hashes=[])
        db.add(row)
        db.flush()
    return row

def _digest(code):
    return hashlib.sha256(code.encode()).hexdigest()

def _record(db,user,event):
    _lock(db,user.business_id)
    last=db.query(SecurityEvent).filter_by(business_id=user.business_id).order_by(SecurityEvent.sequence.desc()).first()
    prev=last.event_hash if last else "0"*64
    sequence=last.sequence+1 if last else 1
    now=datetime.utcnow()
    payload=[user.business_id,user.id,event,sequence,prev,now.isoformat()]
    digest=_digest(json.dumps(payload,separators=(",",":")))
    db.add(SecurityEvent(business_id=user.business_id,user_id=user.id,event=event,
        sequence=sequence,previous_hash=prev,event_hash=digest,created_at=now))
    db.flush()

def verify_chain(db,tenant):
    prev="0"*64
    for i,row in enumerate(db.query(SecurityEvent).filter_by(business_id=tenant).order_by(SecurityEvent.sequence).yield_per(100),1):
        payload=[tenant,row.user_id,row.event,i,prev,row.created_at.isoformat()]
        if row.sequence!=i or row.previous_hash!=prev or not hmac.compare_digest(row.event_hash,_digest(json.dumps(payload,separators=(",",":")))):
            return False
        prev=row.event_hash
    return True

def totp(secret,counter):
    key=base64.b32decode(secret,casefold=True)
    digest=hmac.new(key,struct.pack(">Q",counter),hashlib.sha1).digest()
    off=digest[-1]&15
    return f"{(int.from_bytes(digest[off:off+4],'big')&0x7fffffff)%1000000:06d}"

def _counter(secret,code,last=None,now=None):
    if not isinstance(code,str) or not re.fullmatch(r"[0-9]{6}",code):
        return None
    center=int((time.time() if now is None else now)//30)
    for n in (center,center-1,center+1):
        if n>=0 and (last is None or n>last) and hmac.compare_digest(totp(secret,n),code):
            return n
    return None

def _new_recovery(row):
    codes=["obrc_"+secrets.token_hex(24) for _ in range(8)]
    row.recovery_hashes=[_digest(x) for x in codes]
    return codes

def consume_recovery(row,code):
    if row is None or not isinstance(code,str) or not re.fullmatch(r"obrc_[a-f0-9]{48}",code):
        return False
    digest=_digest(code)
    hashes=row.recovery_hashes or []
    if not any(hmac.compare_digest(digest,x) for x in hashes):
        return False
    row.recovery_hashes=[x for x in hashes if not hmac.compare_digest(digest,x)]
    return True

def verify_factor(db,user,code,now=None):
    _lock(db,user.business_id)
    row=state(db,user)
    if not row or not row.mfa_ciphertext:
        return True
    if consume_recovery(row,code):
        return True
    try:
        n=_counter(_decrypt(user.id,"totp",row.mfa_ciphertext),code,row.last_totp_counter,now)
    except Exception:
        return False
    if n is None:
        return False
    row.last_totp_counter=n
    return True

def start_mfa(db,user):
    _lock(db,user.business_id)
    row=state(db,user,True)
    if row.mfa_ciphertext:
        raise ValueError("MFA already active")
    secret=base64.b32encode(secrets.token_bytes(20)).decode()
    row.pending_mfa_ciphertext=_encrypt(user.id,"pending-totp",secret)
    row.pending_mfa_expires=datetime.utcnow()+timedelta(minutes=10)
    _record(db,user,"mfa_enrollment_started")
    db.commit()
    return secret

def confirm_mfa(db,user,code,now=None):
    _lock(db,user.business_id)
    row=state(db,user)
    if not row or row.mfa_ciphertext or not row.pending_mfa_ciphertext or row.pending_mfa_expires<=datetime.utcnow():
        raise ValueError("No active MFA enrollment")
    secret=_decrypt(user.id,"pending-totp",row.pending_mfa_ciphertext)
    n=_counter(secret,code,now=now)
    if n is None: raise ValueError("Invalid verification code")
    row.mfa_ciphertext=_encrypt(user.id,"totp",secret)
    row.pending_mfa_ciphertext=row.pending_mfa_expires=None
    row.last_totp_counter=n
    codes=_new_recovery(row)
    _record(db,user,"mfa_enabled")
    db.commit()
    return codes

def rotate_recovery(db,user):
    _lock(db,user.business_id)
    row=state(db,user,True)
    codes=_new_recovery(row)
    _record(db,user,"recovery_codes_rotated")
    db.commit()
    return codes

def revoke_sessions(db,user):
    return db.query(UserSession).filter_by(user_id=user.id,business_id=user.business_id,is_revoked=False).update({"is_revoked":True},synchronize_session=False)

def reset_with_recovery(db,user,code,password):
    from apps.api.core.auth import hash_password
    _lock(db,user.business_id)
    row=state(db,user)
    if not consume_recovery(row,code):
        return False
    user.hashed_password=hash_password(password)
    user.api_key=None
    revoke_sessions(db,user)
    _record(db,user,"password_recovered")
    db.commit()
    return True

def stage_email_verification(db,user):
    """Only an approved delivery adapter may retrieve the encrypted code."""
    _lock(db,user.business_id)
    row=state(db,user,True)
    code=secrets.token_urlsafe(32)
    row.email_challenge_hash=_digest(code)
    row.email_challenge_ciphertext=_encrypt(user.id,"email-verify",code)
    row.email_challenge_expires=datetime.utcnow()+timedelta(minutes=30)
    _record(db,user,"email_verification_staged")
    db.commit()
    return {"status":"staged_no_delivery","email_sent":False}

def delivery_payload(row):
    if not row.email_challenge_ciphertext or row.email_challenge_expires<=datetime.utcnow():
        raise ValueError("No current verification challenge")
    return _decrypt(row.user_id,"email-verify",row.email_challenge_ciphertext)

def verify_email(db,user,code):
    _lock(db,user.business_id)
    row=state(db,user)
    if not row or not row.email_challenge_hash or row.email_challenge_expires<=datetime.utcnow() or not hmac.compare_digest(row.email_challenge_hash,_digest(code)):
        return False
    row.email_verified_at=datetime.utcnow()
    row.email_challenge_hash=row.email_challenge_ciphertext=row.email_challenge_expires=None
    _record(db,user,"email_verified")
    db.commit()
    return True

def check_api_key_permissions(db,user,request):
    row=state(db,user)
    path=getattr(getattr(request,"url",None),"path","")
    method=request.method
    if path.startswith("/api/auth/security/") or path=="/api/data/delete-workspace":
        raise HTTPException(403,"Interactive session required")
    if row and row.api_key_expires_at and row.api_key_expires_at<=datetime.utcnow():
        raise HTTPException(401,"API key expired")
    if row and row.api_key_scopes is not None:
        needed="read" if method in ("GET","HEAD","OPTIONS") else "write"
        if needed not in row.api_key_scopes:
            raise HTTPException(403,"API key scope denied")
