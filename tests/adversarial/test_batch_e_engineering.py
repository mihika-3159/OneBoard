"""Batch E durable scheduling, isolation, retention and retrieval regressions."""
import hashlib
import json
import random
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session,sessionmaker
from apps.api.core.database import Base
from apps.api.core.config import settings
from apps.api.models.business import Business,User,UserSession
from apps.api.models.memory import MemoryDocument,MemoryChunk
from apps.api.models.operations import AlertSnapshot,SemanticVector,WorkflowSchedule,SchedulerCursor
from apps.api.models.workflow import WorkflowDefinition,WorkflowRun
from apps.api.services import workflow_schedule,semantic_index,data_lifecycle
from apps.api.services.workflow_engine import workflow_engine
from apps.api.services.memory_engine import memory_engine

@pytest.fixture
def db(tmp_path):
    import apps.api.models.goals_tasks,apps.api.models.entities,apps.api.models.agent_council
    import apps.api.models.decision_evidence,apps.api.models.integrations
    engine=create_engine("sqlite:///"+str(tmp_path/"disposable.sqlite"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()

def epoch(value):
    return datetime.fromisoformat(value).timestamp()

def test_daily_iana_dst_gap_and_fold_once():
    gap=workflow_schedule.next_slot("30 2 * * *","America/New_York",epoch("2026-03-07T08:00:00+00:00"))
    assert gap==epoch("2026-03-09T06:30:00+00:00")
    fold=workflow_schedule.next_slot("30 1 * * *","America/New_York",epoch("2026-11-01T04:00:00+00:00"))
    assert fold==epoch("2026-11-01T05:30:00+00:00")
    assert workflow_schedule.next_slot("30 1 * * *","America/New_York",fold)==epoch("2026-11-02T06:30:00+00:00")
    assert workflow_schedule.next_slot("0 9 * * fri","Asia/Dubai",epoch("2026-11-25T00:00:00+00:00"))==epoch("2026-11-27T05:00:00+00:00")

@pytest.mark.parametrize("cron,zone",[("* * * * *","UTC"),("0 25 * * *","UTC"),("0 9 * * 0","UTC"),("0 9 * * *","Not/AZone")])
def test_invalid_or_unbounded_schedules_rejected(cron,zone):
    with pytest.raises(ValueError):
        workflow_schedule.next_slot(cron,zone,0)

def make_workflow(db,tenant,wid):
    db.add(WorkflowDefinition(id=wid,business_id=tenant,name="Synthetic",nodes=[{"id":"start","type":"trigger","data":{}}],edges=[],is_active=True,is_valid=True))
    db.commit()

def test_missed_slots_coalesce_and_never_duplicate(db):
    make_workflow(db,"a","wa")
    make_workflow(db,"b","wb")
    with pytest.raises(ValueError):
        workflow_schedule.configure(db,"a","wb","0 9 * * *","UTC",True,0)
    first=workflow_schedule.configure(db,"a","wa","0 9 * * *","UTC",True,0)
    due=first["next_due_at"]
    assert workflow_schedule.run_due(db,"b",now=due+2*86400)==0
    assert workflow_schedule.run_due(db,"a",now=due+2*86400)==1
    schedule=db.get(WorkflowSchedule,"wa")
    assert schedule.coalesced and schedule.last_status=="completed" and schedule.next_due_at>due+2*86400
    assert workflow_schedule.run_due(db,"a",now=due+2*86400)==0
    assert db.query(WorkflowRun).count()==1

def test_uncertain_committed_run_is_not_dispatched_again(db,monkeypatch):
    make_workflow(db,"a","wa")
    due=workflow_schedule.configure(db,"a","wa","0 9 * * *","UTC",True,0)["next_due_at"]
    key="scheduled_"+hashlib.sha256(f"a:wa:{due:.0f}".encode()).hexdigest()
    db.add(WorkflowRun(business_id="a",workflow_id="wa",workflow_name="Synthetic",idempotency_key=key,status="running",verification_details={"dry_run":False}))
    db.commit()
    monkeypatch.setattr(workflow_engine,"_execute_steps",lambda *a,**kw:pytest.fail("Uncertain checkpoint replayed"))
    assert workflow_schedule.run_due(db,"a",now=due)==1
    row=db.get(WorkflowSchedule,"wa")
    assert not row.enabled and row.last_status=="running"
    assert db.query(WorkflowRun).count()==1

def test_tenant_worker_failure_does_not_starve_next_tenant(db,monkeypatch):
    import apps.api.services.scheduler_service as module
    db.add_all([Business(id="a",name="A"),Business(id="b",name="B")])
    db.commit()
    monkeypatch.setattr(module,"SessionLocal",sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(settings,"ONEBOARD_PRODUCTION_MODE",False)
    service=module.SchedulerService()
    seen=[]
    def refresh(tenant,apply_policy=False):
        seen.append(tenant)
        if tenant=="a": raise RuntimeError("synthetic failure")
    monkeypatch.setattr(service,"run_proactive_checks",refresh)
    monkeypatch.setattr(workflow_schedule,"run_due",lambda session,tenant:seen.append("schedule:"+tenant))
    assert service.run_tenant_jobs()==1
    assert seen==["a","schedule:a","b","schedule:b"]

def test_snapshot_export_and_opt_in_retention(db):
    for tenant in ("a","b"):
        db.add(Business(id=tenant,name=tenant,owner_id=tenant+"owner"))
        db.add(User(id=tenant+"owner",business_id=tenant,email=tenant+"@example.test",name=tenant,hashed_password="fictional-password-hash"))
    db.commit()
    now=datetime.utcnow()
    db.add_all([AlertSnapshot(business_id=t,alert_key=k,payload={},is_active=active,resolved_at=now-timedelta(days=90))
        for t,k,active in [("a","old",False),("a","active",True),("b","private",False)]])
    db.add_all([UserSession(id=t+"session",business_id=t,user_id=t+"owner",expires_at=now-timedelta(days=90)) for t in ("a","b")])
    db.commit()
    actor=SimpleNamespace(id="aowner",business_id="a")
    result=json.loads(data_lifecycle.export_snapshot(db,actor))
    assert result["snapshot_consistent"] and result["secrets_excluded"]
    assert len(result["tables"]["users"])==1
    assert "hashed_password" not in result["tables"]["users"][0]
    assert "user_sessions" not in result["tables"]
    assert all(x["business_id"]=="a" for x in result["tables"]["alert_snapshots"])
    with pytest.raises(ValueError):
        data_lifecycle.export_snapshot(db,actor,max_rows=1)
    assert data_lifecycle.apply_retention(db,"a",now)==0
    data_lifecycle.set_retention(db,"a",None,30,30)
    assert data_lifecycle.apply_retention(db,"a",now)==2
    db.commit()
    assert {row.alert_key for row in db.query(AlertSnapshot)}=={"active","private"}
    assert {row.id for row in db.query(UserSession)}=={"bsession"}

@pytest.mark.asyncio
async def test_durable_index_cursor_rotates_past_unavailable_tenant(db,monkeypatch):
    db.add_all([Business(id="a",name="A"),Business(id="b",name="B")])
    db.commit()
    for tenant in ("a","b"):
        memory_engine.add_document_with_chunks(db,tenant,tenant,tenant+" text")
    calls=[]
    async def embed(content,model):
        calls.append(content)
        return None if content.startswith("a") else [1.,.2]
    fake=SimpleNamespace(get_model_for_task=lambda task:"nomic-embed-text",genuine_embedding=embed)
    monkeypatch.setattr(semantic_index,"OllamaGateway",lambda:fake)
    assert (await semantic_index.scheduled_index(db))["indexed"]==0
    assert (await semantic_index.scheduled_index(db))["indexed"]==1
    assert calls==["a text","b text"]
    assert db.get(SchedulerCursor,"semantic_backfill").last_tenant=="b"

@pytest.mark.asyncio
async def test_multiprobe_recovers_near_band_without_exact_collision(db,monkeypatch):
    rng=random.Random(94)
    query=[rng.gauss(0,1) for _ in range(32)]
    bands=semantic_index.signatures(query)
    near=None
    for _ in range(20000):
        candidate=[x+rng.gauss(0,.65) for x in query]
        cb=semantic_index.signatures(candidate)
        if all(a!=b for a,b in zip(bands,cb)) and any((a^b).bit_count()==1 for a,b in zip(bands,cb)):
            near=candidate
            break
    assert near is not None
    doc=memory_engine.add_document_with_chunks(db,"a","near synonym","synthetic near semantic content")
    chunk=db.query(MemoryChunk).filter_by(document_id=doc.id).one()
    model=semantic_index.ollama_gateway.get_model_for_task("embedding")
    signatures=semantic_index.signatures(near)
    db.add(SemanticVector(chunk_id=chunk.id,business_id="a",model=model,dimension=32,vector=near,band0=signatures[0],band1=signatures[1],band2=signatures[2],band3=signatures[3]))
    db.commit()
    monkeypatch.setattr(semantic_index.ollama_gateway,"genuine_embedding",AsyncMock(return_value=query))
    result=await semantic_index.retrieve(db,"a","query",5)
    assert result[0]["document_id"]==doc.id
    assert await semantic_index.retrieve(db,"b","query",5)==[]


def test_history_scan_finds_removed_secret_without_printing_value(tmp_path):
    import subprocess
    from scripts.check_tracked_secrets import history_scan
    def git(*args):
        return subprocess.check_output(["git",*args],cwd=tmp_path,stderr=subprocess.DEVNULL)
    git("init")
    git("config","user.name","Synthetic")
    git("config","user.email","synthetic@example.test")
    marker="ghp_"+"B"*36
    path=tmp_path/"removed.txt"
    path.write_text(marker)
    git("add","removed.txt")
    git("commit","-m","synthetic initial")
    git("rm","removed.txt")
    git("commit","-m","synthetic deletion")
    count,findings=history_scan(tmp_path)
    assert count>=1 and any(label=="GitHub token" for _,label in findings)
    assert marker not in repr(findings)
