"""Synthetic real HTTP account-security regression; no live delivery."""
import base64
import time
from uuid import uuid4
from datetime import datetime,timedelta
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from apps.api.core.database import Base,get_db
from apps.api.core.config import settings
from apps.api.main import app
from apps.api.models.business import AccountSecurity,SecurityEvent,User,UserSession
from apps.api.services import account_security as sec

@pytest.fixture
def client(tmp_path,monkeypatch):
    from apps.api.core import auth
    monkeypatch.setattr(settings,"ACCOUNT_SECURITY_KEY",base64.b64encode(b"synthetic-key-32-bytes-for-tests!"[:32]).decode())
    monkeypatch.setattr(auth,"_DEMO_MODE",False)
    engine=create_engine("sqlite:///"+str(tmp_path/"security.sqlite"),connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    def override():
        with factory() as db:
            db.info["oneboard_request"]=True
            yield db
    app.dependency_overrides[get_db]=override
    try:
        with TestClient(app,raise_server_exceptions=True) as c:
            yield c,factory
    finally:
        app.dependency_overrides.pop(get_db,None)
        engine.dispose()

PASSWORD="Synthetic-strong-password-123!"
NEW="Synthetic-new-password-456!"
def register(c):
    email=uuid4().hex+"@example.test"
    c.cookies.clear()
    r=c.post("/api/auth/register",json={"name":"Founder","email":email,"password":PASSWORD,"business_name":"Security synthetic"})
    assert r.status_code==201,r.text
    data=r.json()
    c.cookies.clear()
    return email,data["user"]["id"],data["business"]["id"],{"Authorization":"Bearer "+data["token"]}
def post(c,path,headers=None,**payload):
    return c.post("/api/auth/security"+path,headers=headers,json=payload)
def login(c,email,password=PASSWORD,code=None):
    c.cookies.clear()
    r=c.post("/api/auth/login",json={"email":email,"password":password,"mfa_code":code})
    c.cookies.clear()
    return r

def test_mfa_replay_recovery_and_expired_old_keys(client,monkeypatch):
    c,factory=client
    email,uid,tenant,h=register(c)
    old=post(c,"/api-key",h,password=PASSWORD,scopes=["read"],expires_days=2)
    assert old.status_code==200,old.text
    key=old.json()["api_key"]
    assert c.get("/api/auth/me",headers={"X-API-Key":key}).status_code==200
    now=int(time.time())//30*30
    monkeypatch.setattr(sec.time,"time",lambda:now)
    start=post(c,"/mfa/start",h,password=PASSWORD)
    assert start.status_code==200,start.text
    seed=start.json()["secret"]
    first=sec.totp(seed,now//30)
    confirmed=post(c,"/mfa/confirm",h,code=first)
    assert confirmed.status_code==200,confirmed.text
    codes=confirmed.json()["recovery_codes"]
    assert len(codes)==8 and len(set(codes))==8
    with factory() as db:
        row=db.get(AccountSecurity,uid)
        assert seed not in row.mfa_ciphertext
        assert all(x not in row.recovery_hashes for x in codes)
    assert c.get("/api/auth/me",headers={"X-API-Key":key}).status_code==401
    assert login(c,email).status_code==401
    assert login(c,email,code=first).status_code==401
    next_code=sec.totp(seed,now//30+1)
    signed=login(c,email,code=next_code)
    assert signed.status_code==200,signed.text
    assert login(c,email,code=next_code).status_code==401
    recovery=post(c,"/recover",email=email,recovery_code=codes[0],new_password=NEW)
    assert recovery.status_code==200,recovery.text
    assert post(c,"/recover",email=email,recovery_code=codes[0],new_password=NEW).status_code==401
    assert c.get("/api/auth/me",headers={"Authorization":"Bearer "+signed.json()["token"]}).status_code==401
    recovered=login(c,email,password=NEW,code=codes[1])
    assert recovered.status_code==200,recovered.text

def test_scoped_key_session_revocation_and_member_role_changes(client):
    c,factory=client
    email,uid,tenant,h=register(c)
    key_response=post(c,"/api-key",h,password=PASSWORD,scopes=["read"],expires_days=1)
    assert key_response.status_code==200,key_response.text
    key={"X-API-Key":key_response.json()["api_key"]}
    assert c.get("/api/auth/me",headers=key).status_code==200
    assert c.post("/api/workflows",headers=key,json={"name":"Denied","nodes":[{"id":"x","type":"trigger"}],"edges":[]}).status_code==403
    assert c.get("/api/auth/security",headers=key).status_code==403
    with factory() as db:
        db.get(AccountSecurity,uid).api_key_expires_at=datetime.utcnow()-timedelta(seconds=1)
        db.commit()
    assert c.get("/api/auth/me",headers=key).status_code==401
    invite=post(c,"/members",h,password=PASSWORD,email=uuid4().hex+"@example.test",name="Member",role="member")
    assert invite.status_code==200,invite.text
    mid=invite.json()["id"]
    with factory() as db: member_email=db.get(User,mid).email
    assert post(c,"/recover",email=member_email,recovery_code=invite.json()["activation_recovery_code"],new_password=NEW).status_code==200
    member_login=login(c,member_email,password=NEW)
    assert member_login.status_code==200,member_login.text
    mh={"Authorization":"Bearer "+member_login.json()["token"]}
    assert c.get("/api/auth/security/members",headers=mh).status_code==403
    assert c.post("/api/workflows",headers=mh,json={"name":"Denied","nodes":[{"id":"x","type":"trigger"}],"edges":[]}).status_code==403
    changed=c.put("/api/auth/security/members/"+mid+"/role",headers=h,json={"role":"founder","password":PASSWORD})
    assert changed.status_code==200,changed.text
    assert c.get("/api/auth/me",headers=mh).status_code==401
    fresh=login(c,member_email,password=NEW)
    assert fresh.status_code==200
    new_mh={"Authorization":"Bearer "+fresh.json()["token"]}
    assert post(c,"/members/"+mid+"/revoke",h,password=PASSWORD).status_code==200
    assert c.get("/api/auth/me",headers=new_mh).status_code==401
    # Owner's previous sensitive operations consumed the five-attempt budget.
    assert c.get("/api/auth/security/sessions",headers=h).status_code==200
    with factory() as db:
        assert sec.verify_chain(db,tenant)
        first=db.query(SecurityEvent).filter_by(business_id=tenant).order_by(SecurityEvent.sequence).first()
        first.event="tampered"
        db.commit()
        assert not sec.verify_chain(db,tenant)

def test_email_proof_only_from_delivery_adapter_and_single_use(client):
    c,factory=client
    _,uid,tenant,h=register(c)
    staged=post(c,"/email/stage",h,password=PASSWORD)
    assert staged.status_code==200,staged.text
    assert staged.json()=={"status":"staged_no_delivery","email_sent":False}
    with factory() as db:
        row=db.get(AccountSecurity,uid)
        code=sec.delivery_payload(row)
        assert code not in row.email_challenge_ciphertext and code not in staged.text
    assert post(c,"/email/verify",h,code="wrong").status_code==422
    assert post(c,"/email/verify",h,code=code).status_code==200
    assert post(c,"/email/verify",h,code=code).status_code==422
    assert c.get("/api/auth/security",headers=h).json()["email_verified"] is True

def test_signing_key_rollover(monkeypatch):
    from apps.api.core import auth
    old=auth.SECRET_KEY
    token=auth.create_access_token("synthetic-user","synthetic-tenant")
    monkeypatch.setattr(auth,"SECRET_KEY","replacement-signing-key-for-synthetic-test-123")
    monkeypatch.setattr(settings,"AUTH_PREVIOUS_SECRET_KEY",old)
    assert auth.decode_access_token(token)["sub"]=="synthetic-user"
    monkeypatch.setattr(settings,"AUTH_PREVIOUS_SECRET_KEY","")
    with pytest.raises(ValueError): auth.decode_access_token(token)
