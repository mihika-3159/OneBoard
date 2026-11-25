"""Portable logical archives, retention and bounded database storage."""
from datetime import datetime,timedelta
from types import SimpleNamespace
import hashlib,json,time
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine,select,insert,delete,func,event
from sqlalchemy.orm import Session
from apps.api.core.database import Base,engine_options
from apps.api.core.config import settings
from apps.api.models.business import Business,User,LoginThrottleState,AccountSecurity
from apps.api.models.entities import Customer,Invoice
from apps.api.models.goals_tasks import Task,Goal
from apps.api.models.integrations import IntegrationAccount,SyncHistory
from apps.api.models.operations import (PortableArchive,PortableArchivePage,ProviderConnection,ProviderSyncJob,
    ProviderRecordConflict,SideEffectOutbox,DatabasePerformanceSample,TenantResourceWindow,ScheduledJobLease,ProviderAuthorization)
from apps.api.services import portable_archive as portable,data_lifecycle as lifecycle,storage_maintenance as maintenance,tenant_storage as quota

@pytest.fixture
def db(tmp_path,monkeypatch):
    import apps.api.models.entities,apps.api.models.goals_tasks,apps.api.models.agent_council
    import apps.api.models.memory,apps.api.models.workflow,apps.api.models.decision_evidence,apps.api.models.integrations
    engine=create_engine("sqlite:///"+str(tmp_path/"archive.sqlite"))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings,"AUTH_SECRET_KEY","synthetic-signing-fixture-"*2)
    monkeypatch.setattr(settings,"PORTABLE_ARCHIVE_SIGNING_KEY","")
    with Session(engine,autoflush=False) as db:
        db.add_all([Business(id="a",name="A",owner_id="owner-a"),Business(id="b",name="B",owner_id="owner-b")]);db.flush()
        db.add_all([User(id="owner-a",business_id="a",name="A",email="a@example.test",hashed_password="fixture"),
                    User(id="owner-b",business_id="b",name="B",email="b@example.test",hashed_password="fixture")])
        db.commit()
        yield db
    engine.dispose()

def owner(tenant="a"):
    return SimpleNamespace(business_id=tenant,id="owner-"+tenant)

def stage(db,export):
    manifest=export["manifest"]
    result=portable.begin_import(db,owner(),manifest)
    for d in reversed(manifest["pages"]):
        content,checksum=portable.download(db,"a",export["id"],d["number"])
        assert checksum==d["sha256"]
        assert portable.upload(db,"a",result["id"],d["number"],content)["duplicate"] is False
        assert portable.upload(db,"a",result["id"],d["number"],content)["duplicate"] is True
    return result["id"]

def test_portable_capture_resume_restore_and_redaction(db):
    db.add_all([Customer(id="c1",business_id="a",name="Original",mrr="12.345"),
        Customer(id="foreign",business_id="b",name="Foreign confidential",mrr="99"),
        Goal(id="g1",business_id="a",title="Goal"),
        Task(id="t1",business_id="a",title="Task",goal_id="g1"),
        ProviderConnection(id="pc",business_id="a",provider="github",state="connected",scopes=["repository.read"],encrypted_credentials="credential-fixture",checkpoint="cursor-fixture")])
    db.commit()
    exp=portable.capture(db,owner())
    assert exp["manifest"]["consistent_snapshot"] and exp["manifest"]["secrets_excluded"]
    assert exp["row_count"]>=5
    pages=[portable.download(db,"a",exp["id"],i)[0] for i in range(exp["page_count"])]
    assert all("Foreign confidential" not in p and "credential-fixture" not in p and "cursor-fixture" not in p for p in pages)
    db.execute(delete(Task).where(Task.id=="t1"));db.execute(delete(Goal).where(Goal.id=="g1"));db.execute(delete(Customer).where(Customer.id=="c1"));db.execute(delete(ProviderConnection).where(ProviderConnection.id=="pc"));db.commit()
    assert [portable.download(db,"a",exp["id"],i)[0] for i in range(exp["page_count"])]==pages
    with pytest.raises(ValueError):portable.download(db,"b",exp["id"],0)
    with pytest.raises(ValueError):portable.begin_import(db,owner("b"),exp["manifest"])
    tampered={**exp["manifest"],"rows":exp["row_count"]+1}
    with pytest.raises(ValueError,match="signature"):portable.begin_import(db,owner(),tampered)
    imp=stage(db,exp)
    assert portable.progress(db,"a",imp)["state"]=="ready"
    restored=portable.restore(db,owner(),imp,"RESTORE a")
    assert restored["inserted"]==4 and restored["external_actions_replayed"] is False
    assert db.get(Customer,"c1").mrr==__import__("decimal").Decimal("12.345")
    assert db.get(Task,"t1").goal_id=="g1"
    provider=db.get(ProviderConnection,"pc")
    assert provider.state=="disconnected" and provider.encrypted_credentials is None and provider.checkpoint is None
    assert portable.restore(db,owner(),imp,"RESTORE a")["status"]=="already_applied"

def test_conflicting_restore_rolls_back_and_tampered_page_rejected(db):
    db.add_all([Customer(id="c1",business_id="a",name="Before",mrr=1),Task(id="t1",business_id="a",title="Before")]);db.commit()
    exp=portable.capture(db,owner())
    manifest=exp["manifest"]
    imp=portable.begin_import(db,owner(),manifest)["id"]
    content,_=portable.download(db,"a",exp["id"],0)
    with pytest.raises(ValueError,match="checksum"):portable.upload(db,"a",imp,0,content+" ")
    assert portable.progress(db,"a",imp)["page_count"]==0
    for d in manifest["pages"]:
        content,_=portable.download(db,"a",exp["id"],d["number"])
        portable.upload(db,"a",imp,d["number"],content)
    db.execute(delete(Customer).where(Customer.id=="c1"));db.get(Task,"t1").title="Changed after capture";db.commit()
    with pytest.raises(ValueError,match="never overwrites"):portable.restore(db,owner(),imp,"RESTORE a")
    assert db.get(Customer,"c1") is None
    assert db.get(Task,"t1").title=="Changed after capture"
    assert portable.progress(db,"a",imp)["state"]=="ready"

def test_large_portable_capture_exceeds_old_row_and_byte_ceiling(db):
    from apps.api.models.decision_evidence import Evidence
    payload="x"*1800
    for start in range(0,11000,500):
        db.execute(insert(Task.__table__),[{"id":f"task-{i:06d}","business_id":"a","title":"Synthetic task","description":payload} for i in range(start,start+500)])
        db.execute(insert(Evidence.__table__),[{"id":f"evidence-{i:06d}","business_id":"a","title":"Synthetic evidence","source_connector":"local_file","snippet":payload} for i in range(start,start+500)])
    db.commit()
    exp=portable.capture(db,owner())
    assert exp["row_count"]==22001 and exp["byte_count"]>32*1024*1024
    assert exp["page_count"]>20 and exp["page_count"]<=portable.MAX_PAGES
    manifest=exp["manifest"]
    assert sum(d["rows"] for d in manifest["pages"])==22001
    assert all(d["bytes"]<=portable.MAX_PAGE for d in manifest["pages"])
    for d in (manifest["pages"][0],manifest["pages"][-1]):
        content,checksum=portable.download(db,"a",exp["id"],d["number"])
        assert len(content.encode())==d["bytes"] and hashlib.sha256(content.encode()).hexdigest()==checksum

def test_keyset_pagination_tenant_binding_and_quota(db,monkeypatch):
    for i in range(17):db.add(Task(id=f"task-{i:03d}",business_id="a",title=str(i)))
    db.add(Task(id="task-foreign",business_id="b",title="Foreign"));db.commit()
    page=maintenance.collection_page(db,"a","tasks",limit=5)
    ids=[r["id"] for r in page["records"]]
    first=page["next_cursor"]
    with pytest.raises(ValueError):maintenance.collection_page(db,"b","tasks",first)
    with pytest.raises(ValueError):maintenance.collection_page(db,"a","goals",first)
    while page["next_cursor"]:
        page=maintenance.collection_page(db,"a","tasks",page["next_cursor"],5);ids.extend(r["id"] for r in page["records"])
    assert ids==[f"task-{i:03d}" for i in range(17)]
    monkeypatch.setitem(quota.ROW_LIMITS,"tasks",17)
    db.info["oneboard_enforce_quota"]=True
    db.add(Task(business_id="a",title="Too many"))
    with pytest.raises(HTTPException) as exc:db.flush()
    assert exc.value.status_code==429
    db.rollback()
    db.add(Task(business_id="b",title="Allowed"));db.commit()
    assert maintenance.quota_report(db,"b")["tasks"]["used"]==2

def test_retention_and_cleanup_preserve_replay_identities(db):
    old=datetime.utcnow()-timedelta(days=60)
    db.add_all([ProviderSyncJob(id="sync",business_id="a",connection_id="pc",generation=1,request_key="unique-sync",state="succeeded",finished_at=old,error_code="diagnostic"),
                ProviderSyncJob(id="active",business_id="a",connection_id="pc",generation=1,request_key="active-sync",state="queued",finished_at=old,error_code="preserve"),
                ProviderRecordConflict(id="conf",business_id="a",connection_id="pc",record_id="rec",incoming_revision="1",incoming_payload={"old":"payload"},incoming_hash="a"*64,state="keep_recorded",created_at=old),
                SideEffectOutbox(id="draft",business_id="a",run_id="run",step_id="step",kind="invoice_reminder_draft",payload={"sensitive":"old"},state="draft_ready",processed_at=old),
                TenantResourceWindow(business_id="a",resource="ai_command",attempt_count=1,window_started_at=time.time()-100000),
                TenantResourceWindow(business_id="b",resource="ai_command",attempt_count=1,window_started_at=time.time()-100000),
                ProviderAuthorization(state_hash="a"*64,business_id="a",connection_id="pc",actor_id="owner-a",generation=1,scopes=[],encrypted_verifier="fixture",expires_at=old),
                AccountSecurity(user_id="owner-a",business_id="a",pending_mfa_ciphertext="fixture",pending_mfa_expires=old),
                LoginThrottleState(identifier_hash="b"*64,attempt_count=2,window_started_at=time.time()-100000),
                LoginThrottleState(identifier_hash="c"*64,attempt_count=2,window_started_at=time.time()),
                ScheduledJobLease(job_key="stale-job",next_due_at=0,lease_until=time.time()-100000,owner_token="fixture",attempts=1)])
    db.commit()
    lifecycle.set_retention(db,"a",None,completed_sync_days=30,resolved_conflict_days=30,completed_draft_days=30)
    assert lifecycle.apply_retention(db,"a")==3;db.commit()
    assert db.get(ProviderSyncJob,"sync").request_key=="unique-sync" and db.get(ProviderSyncJob,"sync").error_code is None
    assert db.get(ProviderSyncJob,"active").error_code=="preserve"
    assert db.get(ProviderRecordConflict,"conf").incoming_hash=="a"*64 and db.get(ProviderRecordConflict,"conf").incoming_payload=={}
    assert db.get(SideEffectOutbox,"draft").payload=={}
    assert lifecycle.apply_retention(db,"a")==0;db.commit()
    assert maintenance.cleanup_tenant(db,"a")==3
    assert db.get(TenantResourceWindow,("b","ai_command")) is not None
    assert db.get(AccountSecurity,"owner-a").pending_mfa_ciphertext is None
    assert maintenance.cleanup_global(db)==2
    assert db.get(LoginThrottleState,"c"*64) is not None
    assert db.get(ScheduledJobLease,"stale-job").owner_token is None

def test_verified_deletion_removes_indirect_rows_and_archives(db):
    db.add_all([IntegrationAccount(id="ia",business_id="a",connector_type="github",name="A"),
        IntegrationAccount(id="ib",business_id="b",connector_type="github",name="B"),
        SyncHistory(id="sa",integration_id="ia"),SyncHistory(id="sb",integration_id="ib")]);db.commit()
    exp=portable.capture(db,owner())
    result=lifecycle.delete_workspace(db,owner(),"DELETE a")
    assert result["verified_remaining_rows"]==0 and result["deleted_counts"]["sync_history"]==1
    assert db.get(Business,"a") is None and db.get(User,"owner-a") is None
    assert db.get(Business,"b") is not None and db.get(SyncHistory,"sb") is not None
    assert db.get(SyncHistory,"sa") is None and db.get(PortableArchive,exp["id"]) is None
    assert db.query(PortableArchivePage).filter_by(business_id="a").count()==0

def test_bounded_pool_and_performance_regression_samples(db,monkeypatch):
    monkeypatch.setattr(settings,"DB_POOL_SIZE",3);monkeypatch.setattr(settings,"DB_MAX_OVERFLOW",2)
    assert engine_options("postgresql://localhost/db")["pool_size"]==3
    monkeypatch.setattr(settings,"DB_MAX_OVERFLOW",0)
    with pytest.raises(ValueError):engine_options("postgresql://localhost/db")
    assert maintenance.sample(db,"a") is True
    assert maintenance.sample(db,"a") is None
    old=datetime.utcnow()-timedelta(days=1)
    db.add_all([DatabasePerformanceSample(business_id="a",workload="custom",rows_examined=10,elapsed_ms=1,created_at=old),
                DatabasePerformanceSample(business_id="a",workload="custom",rows_examined=10,elapsed_ms=100,created_at=datetime.utcnow()),
                DatabasePerformanceSample(business_id="b",workload="foreign",rows_examined=10,elapsed_ms=100)])
    db.commit()
    report=maintenance.report(db,"a")["workloads"]
    assert report["custom"]["regression"] and "foreign" not in report
