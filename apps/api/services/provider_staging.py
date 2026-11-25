"""Offline provider integration scaffolding: no network, no dispatch."""
import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from apps.api.core.config import settings
from apps.api.models.operations import ProviderCredential, ProviderIntent
from apps.api.services.tenant_storage import _lock

SCOPES={"github":{"repo:metadata:read","repo:contents:read"},
        "google":{"drive.metadata.readonly","calendar.readonly"},
        "notion":{"content.read"}}

def _key():
    try:
        key=base64.b64decode(settings.PROVIDER_TOKEN_KEY,validate=True)
    except (ValueError,TypeError) as exc:
        raise ValueError("Provider credential encryption is not configured") from exc
    if len(key)!=32:
        raise ValueError("Provider credential encryption is not configured")
    return key

def _aad(tenant,provider,scopes,expires_at):
    return json.dumps([tenant,provider,sorted(scopes),expires_at.isoformat()],separators=(",",":")).encode()

def encrypt_token(tenant,provider,scopes,expires_at,token):
    nonce=os.urandom(12)
    return base64.b64encode(nonce+AESGCM(_key()).encrypt(nonce,token.encode(),_aad(tenant,provider,scopes,expires_at))).decode()

def decrypt_token(row):
    if row.expires_at<=datetime.utcnow():
        raise ValueError("Provider credential expired")
    value=base64.b64decode(row.encrypted_token,validate=True)
    return AESGCM(_key()).decrypt(value[:12],value[12:],_aad(row.business_id,row.provider,row.scopes,row.expires_at)).decode()

def store_credential(db,tenant,provider,scopes,token,expires_at):
    if provider not in SCOPES or not scopes or len(scopes)!=len(set(scopes)) or not set(scopes)<=SCOPES[provider]:
        raise ValueError("Unsupported provider or requested read scope")
    if not isinstance(token,str) or not 1<=len(token)<=4096 or any(ord(c)<32 for c in token):
        raise ValueError("Invalid token")
    if expires_at.tzinfo is None:
        raise ValueError("Expiry requires timezone")
    expiry=expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    if expiry<=datetime.utcnow():
        raise ValueError("Provider credential expired")
    ciphertext=encrypt_token(tenant,provider,scopes,expiry,token)
    _lock(db,tenant)
    row=db.query(ProviderCredential).filter_by(business_id=tenant,provider=provider).first()
    if row is None:
        row=ProviderCredential(business_id=tenant,provider=provider)
        db.add(row)
    row.scopes=sorted(scopes)
    row.encrypted_token=ciphertext
    row.expires_at=expiry
    row.updated_at=datetime.utcnow()
    db.commit()
    return {"provider":provider,"requested_scopes":row.scopes,"expires_at":expiry.isoformat()+"Z",
            "status":"stored_unverified_no_dispatch","grants_verified":False}

def stage_intent(db,tenant,provider,scope,key):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}",key):
        raise ValueError("Invalid idempotency key")
    if provider not in SCOPES or scope not in SCOPES[provider]:
        raise ValueError("Unsupported provider scope")
    _lock(db,tenant)
    row=db.query(ProviderCredential).filter_by(business_id=tenant,provider=provider).first()
    if row is None or scope not in row.scopes or row.expires_at<=datetime.utcnow():
        raise ValueError("No current credential with requested scope")
    digest=hashlib.sha256(json.dumps([provider,scope],separators=(",",":")).encode()).hexdigest()
    old=db.query(ProviderIntent).filter_by(business_id=tenant,provider=provider,idempotency_key=key).first()
    if old and old.request_sha256!=digest:
        raise ValueError("Idempotency key already used with different intent")
    if not old:
        if db.query(ProviderIntent).filter_by(business_id=tenant).count()>=1000:
            raise ValueError("Tenant provider intent limit reached")
        old=ProviderIntent(business_id=tenant,provider=provider,idempotency_key=key,request_sha256=digest,scope=scope)
        db.add(old)
        db.commit()
    return {"id":old.id,"status":old.state,"provider":provider,"scope":scope,
            "provider_contacted":False,"grants_verified":False}


def revoke_credential(db,tenant,provider):
    if provider not in SCOPES:
        raise ValueError("Unsupported provider")
    _lock(db,tenant)
    removed=db.query(ProviderCredential).filter_by(business_id=tenant,provider=provider).delete()
    db.query(ProviderIntent).filter_by(business_id=tenant,provider=provider,state="staged_no_dispatch").update({"state":"cancelled_local"},synchronize_session=False)
    db.commit()
    return {"local_credential_removed":bool(removed),"remote_revocation_confirmed":False}
