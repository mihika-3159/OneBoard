"""Signed scope, separate from database login credential."""
import base64
import hashlib
import hmac
from sqlalchemy import text
from sqlalchemy.orm import Session
from apps.api.core.config import settings

def restricted(db):
    return isinstance(db,Session) and db.get_bind().dialect.name=="postgresql" and settings.ONEBOARD_PRODUCTION_MODE

def context_key():
    try: key=base64.b64decode(settings.TENANT_CONTEXT_KEY,validate=True)
    except (ValueError,TypeError): key=b""
    if len(key)!=32: raise ValueError("Tenant context key must be separately provisioned")
    return key

def apply_context(connection,tenant):
    connection.execute(text("SELECT set_config('oneboard.tenant',:tenant,true)"),{"tenant":tenant})
    if settings.TENANT_CONTEXT_KEY:
        pid,tx=connection.execute(text("SELECT pg_backend_pid(),txid_current()")).one()
        proof=hmac.new(context_key(),f"{tenant}:{pid}:{tx}".encode(),hashlib.sha256).hexdigest()
        connection.execute(text("SELECT set_config('oneboard.proof',:proof,true)"),{"proof":proof})

def lookup(db,kind,value):
    if kind not in ("email","key"): raise ValueError("Invalid directory lookup")
    return db.execute(text(f"SELECT uid,tenant FROM public.ob_lookup_{kind}(:value)"),{"value":value}).first()

def tenant_ids(db,after="",limit=1000):
    from apps.api.models.business import Business
    if restricted(db):
        return [r[0] for r in db.execute(text("SELECT * FROM public.ob_tenant_ids(:after,:limit)"),{"after":after,"limit":limit})]
    return [r[0] for r in db.query(Business.id).filter(Business.id>after).order_by(Business.id).limit(limit).all()]


def password_verifier(db,user):
    if restricted(db):
        return db.execute(text("SELECT public.ob_password_verifier(:uid)"),{"uid":user.id}).scalar_one()
    return user.hashed_password
