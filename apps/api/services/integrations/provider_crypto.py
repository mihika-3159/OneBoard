"""Versioned AEAD envelopes, bound to tenant, purpose, and immutable record identity."""
import base64,json,re,secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from apps.api.core.config import settings

def keyring():
    keys=settings.PROVIDER_ENCRYPTION_KEYS
    active=settings.PROVIDER_ACTIVE_KEY_ID
    if not active or active not in keys or not 1<=len(keys)<=16:
        raise ValueError("Provider encryption keyring unavailable")
    out={}
    for kid,encoded in keys.items():
        try:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}",kid):raise ValueError()
            raw=base64.b64decode(encoded,validate=True)
            if len(raw)!=32:raise ValueError()
        except (ValueError,TypeError):raise ValueError("Invalid provider encryption keyring") from None
        out[kid]=raw
    return active,out

def aad(tenant,identity,purpose):
    return json.dumps([tenant,identity,purpose],separators=(",",":")).encode()

def seal(value,tenant,identity,purpose):
    active,keys=keyring()
    nonce=secrets.token_bytes(12)
    raw=json.dumps(value,separators=(",",":"),ensure_ascii=False).encode()
    if len(raw)>24000:raise ValueError("Credential envelope too large")
    return active+"."+base64.b64encode(nonce+AESGCM(keys[active]).encrypt(nonce,raw,aad(tenant,identity,purpose))).decode()

def unseal(envelope,tenant,identity,purpose):
    try:
        _,keys=keyring()
        kid,encoded=envelope.split(".",1)
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)<28 or len(raw)>25000:raise ValueError()
        return json.loads(AESGCM(keys[kid]).decrypt(raw[:12],raw[12:],aad(tenant,identity,purpose)))
    except (ValueError,TypeError,AttributeError,KeyError,InvalidTag,UnicodeError):
        raise ValueError("Provider credential cannot be decrypted") from None

def rotate(envelope,tenant,identity,purpose):
    active,_=keyring()
    value=unseal(envelope,tenant,identity,purpose)
    return envelope if envelope.startswith(active+".") else seal(value,tenant,identity,purpose)
