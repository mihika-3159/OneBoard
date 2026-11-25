"""Simulated HTTPS provider contracts; no real credentials or network."""
from datetime import datetime,timedelta
import base64,hashlib,hmac,json,time
from urllib.parse import urlsplit,parse_qs
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apps.api.core.config import settings
from apps.api.core.database import Base
from apps.api.models.business import Business,User
from apps.api.models.operations import (ProviderConnection,ProviderAuthorization,ProviderSyncJob,ProviderRecord,ProviderRecordConflict,ProviderDelivery,ProviderCredential)
from apps.api.services.integrations import provider_runtime as rt,provider_transport as transport,provider_crypto as crypto
from apps.api.services.provider_staging import store_credential,decrypt_stored_token

@pytest.fixture
def db(monkeypatch):
    import apps.api.models.entities,apps.api.models.goals_tasks,apps.api.models.agent_council
    import apps.api.models.memory,apps.api.models.workflow,apps.api.models.decision_evidence,apps.api.models.integrations
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings,"PROVIDER_ACTIVE_KEY_ID","v1")
    monkeypatch.setattr(settings,"PROVIDER_ENCRYPTION_KEYS",{"v1":base64.b64encode(b"1"*32).decode()})
    monkeypatch.setattr(settings,"PUBLIC_API_ORIGIN","https://oneboard.example")
    cfg={"enabled":True,"host":"adapter.example","client_id":"fixture-client","client_secret":"fixture-secret",
         "webhook_secret":"w"*32,**{n+"_url":"https://adapter.example/"+n for n in ("authorize","token","identity","sync","revoke","action","status")}}
    monkeypatch.setattr(settings,"PROVIDER_CONNECTORS",{p:dict(cfg) for p in transport.CAPABILITIES})
    with Session(engine) as db:
        db.add_all([Business(id="a",name="A",owner_id="actor"),Business(id="b",name="B",owner_id="other")])
        db.flush()
        db.add_all([User(id="actor",business_id="a",name="A",email="a@example.test",hashed_password="fixture"),
                    User(id="other",business_id="b",name="B",email="b@example.test",hashed_password="fixture")])
        db.commit()
        yield db
    engine.dispose()

class FakeProvider:
    def __init__(self,provider,scopes):
        self.provider=provider;self.scopes=scopes;self.calls=[];self.pages=[];self.deliveries={}
        self.challenge=None;self.refreshes=0;self.fail_delivery=False;self.fail_refresh=False;self.account="account-1";self.revoke_ok=True
    def response(self,request):
        path=request.url.path;self.calls.append(path)
        assert request.url.host=="adapter.example"
        if path=="/token":
            data=parse_qs(request.content.decode())
            assert data["client_id"]==["fixture-client"]
            if data["grant_type"]==["authorization_code"]:
                verifier=data["code_verifier"][0]
                assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")==self.challenge
                assert data["code"]==["fixture-code"]
            else:
                assert data["grant_type"]==["refresh_token"] and data["refresh_token"][0].startswith("refresh-")
                self.refreshes+=1
                if self.fail_refresh:return httpx.Response(503,json={})
            return httpx.Response(200,json={"token_type":"Bearer","access_token":"access-"+str(self.refreshes),
                "refresh_token":"refresh-"+str(self.refreshes),"scope":" ".join(self.scopes),"expires_in":3600})
        if path=="/identity":
            assert request.headers["Authorization"].startswith("Bearer access-")
            return httpx.Response(200,json={"account_id":self.account})
        if path=="/sync":
            assert request.headers["Authorization"].startswith("Bearer access-")
            data=json.loads(request.content);assert set(data["scopes"])==set(self.scopes)
            expected,result=self.pages.pop(0);assert data["cursor"]==expected
            if isinstance(result,int):return httpx.Response(result,headers={"Retry-After":"120"},json={})
            return httpx.Response(200,json=result)
        if path=="/revoke":return httpx.Response(200,json={"revoked":self.revoke_ok})
        if path=="/action":
            data=json.loads(request.content);key=data["idempotency_key"]
            self.deliveries[key]={"status":"confirmed","remote_reference":"receipt-1","idempotency_key":key}
            if self.fail_delivery:raise httpx.ReadTimeout("fixture timeout",request=request)
            return httpx.Response(200,json=self.deliveries[key])
        if path=="/status":
            key=json.loads(request.content)["idempotency_key"]
            return httpx.Response(200,json=self.deliveries.get(key,{"idempotency_key":key,"status":"not_found"}))
        raise AssertionError(path)

def fake(monkeypatch,provider,scopes):
    f=FakeProvider(provider,scopes)
    original=httpx.Client
    monkeypatch.setattr(transport.httpx,"Client",lambda **kwargs:original(transport=httpx.MockTransport(f.response),**kwargs))
    return f

def begin(db,provider,scopes,f):
    result=rt.start_authorization(db,"a","actor",provider,scopes)
    q=parse_qs(urlsplit(result["authorization_url"]).query)
    assert q["code_challenge_method"]==["S256"] and q["response_type"]==["code"]
    f.challenge=q["code_challenge"][0]
    return q["state"][0]

def connect(db,provider,scopes,f):
    state=begin(db,provider,scopes,f)
    connected=rt.complete_authorization(db,"a","actor",state,"fixture-code")
    assert connected["state"]=="connected"
    return rt.connection(db,"a",provider)

def page(cursor,records,more=False):
    return {"records":[{"id":i,"revision":r,"payload":p} for i,r,p in records],"next_cursor":cursor,"has_more":more}

@pytest.mark.parametrize("provider",list(transport.CAPABILITIES))
def test_seven_adapter_oauth_incremental_and_revocation_contracts(db,monkeypatch,provider):
    scopes=[next(s for s in sorted(transport.CAPABILITIES[provider][0]) if s.endswith(".read"))]
    f=fake(monkeypatch,provider,scopes)
    row=connect(db,provider,scopes,f);ident=row.id
    assert "access-0" not in row.encrypted_credentials
    assert crypto.unseal(row.encrypted_credentials,"a",row.id,rt.credential_purpose(row))["access_token"]=="access-0"
    f.pages=[(None,page("cursor-1",[("1","r1",{"name":"record-1"})],True)),
             ("cursor-1",page("cursor-2",[("1","r1",{"name":"record-1"}),("2","r1",{"name":"record-2"})]))]
    job=rt.enqueue(db,"a",provider,"request-1")
    assert rt.enqueue(db,"a",provider,"request-1").id==job.id
    assert rt.run_sync(db,"a")["state"]=="queued"
    db.expire_all()
    assert rt.run_sync(db,"a")["state"]=="succeeded"
    assert db.query(ProviderRecord).filter_by(connection_id=ident).count()==2
    assert rt.connection(db,"a",provider).checkpoint=="cursor-2"
    assert db.get(ProviderSyncJob,job.id).duplicates==1
    assert rt.run_sync(db,"b") is None
    f.pages=[("cursor-2",page("cursor-3",[("1","r2",{"name":"updated"})]))]
    rt.enqueue(db,"a",provider,"request-2");assert rt.run_sync(db,"a")["conflicts"]==1
    conflict=db.query(ProviderRecordConflict).one()
    assert db.query(ProviderRecord).filter_by(remote_id="1").one().payload=={"name":"record-1"}
    with pytest.raises(ValueError):rt.resolve_conflict(db,"b",conflict.id,"accept_incoming")
    db.rollback()
    rt.resolve_conflict(db,"a",conflict.id,"accept_incoming")
    assert db.query(ProviderRecord).filter_by(remote_id="1").one().payload=={"name":"updated"}
    result=rt.disconnect(db,"a",provider)
    assert result["remote_revocation_confirmed"] is True
    assert rt.connection(db,"a",provider).encrypted_credentials is None

def test_state_replay_actor_binding_expiration_and_scope_mismatch(db,monkeypatch):
    scopes=["repository.read"];f=fake(monkeypatch,"github",scopes)
    state=begin(db,"github",scopes,f)
    for tenant,actor in (("a","other"),("b","actor")):
        with pytest.raises(ValueError):rt.complete_authorization(db,tenant,actor,state,"fixture-code")
        db.rollback()
    rt.complete_authorization(db,"a","actor",state,"fixture-code")
    with pytest.raises(ValueError):rt.complete_authorization(db,"a","actor",state,"fixture-code")
    db.rollback()
    rt.disconnect(db,"a","github")
    state=begin(db,"github",scopes,f)
    auth=db.query(ProviderAuthorization).filter_by(state_hash=hashlib.sha256(state.encode()).hexdigest()).one()
    auth.expires_at=datetime.utcnow()-timedelta(seconds=1);db.commit()
    with pytest.raises(ValueError):rt.complete_authorization(db,"a","actor",state,"fixture-code")
    db.rollback()
    state=begin(db,"github",scopes,f);f.scopes=["issues.write"]
    with pytest.raises(ValueError,match="authorization failed"):rt.complete_authorization(db,"a","actor",state,"fixture-code")
    assert rt.connection(db,"a","github").state=="auth_required"

def test_refresh_backoff_and_atomic_checkpoint(db,monkeypatch):
    f=fake(monkeypatch,"crm",["contacts.read"]);row=connect(db,"crm",f.scopes,f)
    row.expires_at=datetime.utcnow()-timedelta(seconds=1);db.commit()
    f.pages=[(None,429),(None,page("next",[("x","r1",{"name":"X"})]))]
    job=rt.enqueue(db,"a","crm","retry-job")
    first=rt.run_sync(db,"a")
    assert first["state"]=="retry" and first["error_code"]=="rate_limited" and f.refreshes==1
    assert row.checkpoint is None and db.query(ProviderRecord).count()==0
    assert rt.run_sync(db,"a") is None
    job.next_attempt=datetime.utcnow()-timedelta(seconds=1);db.commit()
    assert rt.run_sync(db,"a")["state"]=="succeeded" and row.checkpoint=="next"
    row.expires_at=datetime.utcnow()-timedelta(seconds=1);db.commit();f.fail_refresh=True
    rt.enqueue(db,"a","crm","retry-job2")
    assert rt.run_sync(db,"a")["state"]=="failed" and row.state=="auth_required"
    assert f.refreshes==2

def test_key_rotation_and_legacy_ciphertext(db,monkeypatch):
    f=fake(monkeypatch,"github",["repository.read"]);row=connect(db,"github",f.scopes,f)
    old=row.encrypted_credentials
    with pytest.raises(ValueError):crypto.unseal(old,"b",row.id,rt.credential_purpose(row))
    monkeypatch.setattr(settings,"PROVIDER_TOKEN_KEY",base64.b64encode(b"l"*32).decode())
    monkeypatch.setattr(settings,"PROVIDER_ACTIVE_KEY_ID","")
    from datetime import timezone
    store_credential(db,"a","github",["repo:metadata:read"],"legacy-fixture",datetime.now(timezone.utc)+timedelta(hours=1))
    monkeypatch.setattr(settings,"PROVIDER_ENCRYPTION_KEYS",{"v1":base64.b64encode(b"1"*32).decode(),"v2":base64.b64encode(b"2"*32).decode()})
    monkeypatch.setattr(settings,"PROVIDER_ACTIVE_KEY_ID","v2")
    assert rt.rotate_keys(db,"a")["rotated"]==2
    assert row.encrypted_credentials.startswith("v2.")
    monkeypatch.setattr(settings,"PROVIDER_ENCRYPTION_KEYS",{"v2":base64.b64encode(b"2"*32).decode()})
    assert crypto.unseal(row.encrypted_credentials,"a",row.id,rt.credential_purpose(row))["access_token"]=="access-0"
    assert decrypt_stored_token(db.query(ProviderCredential).one())=="legacy-fixture"

def test_signed_webhook_replay_and_conflicting_event(db,monkeypatch):
    f=fake(monkeypatch,"calendar",["calendar.read"]);row=connect(db,"calendar",f.scopes,f)
    body=json.dumps({"event_id":"event-123","account_id":"account-1","type":"records.changed"}).encode();ts=str(int(time.time()))
    sig=hmac.new(b"w"*32,b"\n".join([b"calendar",b"a",row.id.encode(),ts.encode(),body]),hashlib.sha256).hexdigest()
    rt.webhook_signature("calendar","a",row.id,ts,body,sig)
    with pytest.raises(ValueError):rt.webhook_signature("calendar","b",row.id,ts,body,sig)
    with pytest.raises(ValueError):rt.webhook_signature("calendar","a",row.id,str(int(ts)-301),body,sig)
    assert rt.accept_webhook(db,"a","calendar",row.id,body)=={"accepted":True,"duplicate":False}
    assert rt.accept_webhook(db,"a","calendar",row.id,body)=={"accepted":True,"duplicate":True}
    assert db.query(ProviderSyncJob).count()==1
    with pytest.raises(ValueError):rt.accept_webhook(db,"a","calendar",row.id,body+b" ")
    db.rollback()

def test_uncertain_delivery_never_resends_and_requires_status(db,monkeypatch):
    f=fake(monkeypatch,"email",["mail.read","mail.send"]);row=connect(db,"email",f.scopes,f)
    payload={"recipient":"recipient@example.test","subject":"Fixture","body":"hello\nworld"}
    with pytest.raises(ValueError):rt.approve_action(db,"a","actor","email","email.send",payload,"send-key1","")
    db.rollback()
    action=rt.approve_action(db,"a","actor","email","email.send",payload,"send-key1","APPROVE email.send")
    assert action["state"]=="approved"
    f.fail_delivery=True
    assert rt.dispatch_one(db,"a")["state"]=="uncertain"
    assert rt.dispatch_one(db,"a") is None
    assert f.calls.count("/action")==1
    assert rt.reconcile_delivery(db,"a",action["id"])["state"]=="confirmed"
    assert f.calls.count("/action")==1 and f.calls.count("/status")==1
    with pytest.raises(ValueError):rt.reconcile_delivery(db,"b",action["id"])
    db.rollback()
    f.revoke_ok=False
    next_action=rt.approve_action(db,"a","actor","email","email.send",payload,"send-key2","APPROVE email.send")
    assert rt.disconnect(db,"a","email")["remote_revocation_confirmed"] is False
    assert db.get(ProviderDelivery,next_action["id"]).state=="cancelled"

def test_disabled_and_unsafe_endpoint_configuration(db,monkeypatch):
    monkeypatch.setattr(settings,"PROVIDER_CONNECTORS",{})
    with pytest.raises(ValueError,match="not configured"):rt.start_authorization(db,"a","actor","github",["repository.read"])
    assert db.query(ProviderConnection).count()==0
    with pytest.raises(ValueError):transport.endpoint("https://adapter.example.evil.test/token","adapter.example")
    with pytest.raises(ValueError):transport.endpoint("http://adapter.example/token","adapter.example")
    with pytest.raises(ValueError):transport.endpoint("https://adapter.example/token?secret=x","adapter.example")
