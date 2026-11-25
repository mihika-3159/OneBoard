"""Reliability regression tests: no real customer data, external storage or deployment."""
import errno,hashlib,json,os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine,text
from fastapi.testclient import TestClient
from apps.api.core.config import settings
from apps.api.services import operational_health as ops
from scripts.operations import backup_manager as bm,operator_monitor as monitor
from scripts.operations.capacity_report import plan
from scripts.operations.release_guard import assess
from scripts.operations.backup_encrypted import verify_manifest

def private(path):
    path.mkdir(mode=0o700)
    return path
def fixture_backup(folder,date,number):
    name="oneboard-"+date.strftime("%Y%m%dT%H%M%SZ")+"-"+f"{number:08x}"+".dump.age"
    archive=folder/name;manifest=folder/(name+".json")
    content=("synthetic ciphertext fixture "+str(number)).encode()*10
    archive.write_bytes(content);archive.chmod(0o600)
    manifest.write_text(json.dumps({"format":"age-encrypted-pg-custom-v1","filename":name,"sha256":hashlib.sha256(content).hexdigest(),"created_utc":date.isoformat(),"snapshot_started_utc":date.isoformat(),"bytes":len(content)}));manifest.chmod(0o600)
    return archive,manifest

@pytest.mark.skipif(os.name!="posix",reason="Linux operator filesystem semantics")
def test_backup_due_retention_replica_recovery(tmp_path,monkeypatch):
    root=private(tmp_path/"primary");other=private(tmp_path/"replica");dest=private(tmp_path/"recovered")
    now=datetime.now(timezone.utc)
    ancient=[fixture_backup(root,now-timedelta(days=d),i) for i,d in enumerate((90,60,45),1)]
    fixture_backup(root,now-timedelta(days=2),4)
    calls=[]
    def backup(folder,recipient,source):
        calls.append(True)
        return fixture_backup(folder,now,5)
    monkeypatch.setattr(bm,"backup",backup)
    source={"ONEBOARD_BACKUP_OPERATION_APPROVED":"YES","ONEBOARD_PRODUCTION_MODE":"true"}
    replica=bm.DirectoryReplica(other,root)
    result=bm.manage(root,"fixture",source,retention_days=30,keep=2,replica=replica,now=now,min_free_mib=1)
    assert result["backup_created"] and result["expired"]==3 and result["verified_archives"]==2
    assert not result["offsite_verified"]
    assert all(not x[0].exists() for x in ancient)
    result=bm.manage(root,"fixture",source,retention_days=30,keep=2,replica=replica,now=now,min_free_mib=1)
    assert not result["backup_created"] and len(calls)==1
    restored,manifest=replica.retrieve(ancient[0][0].name,dest)
    assert verify_manifest(restored,manifest)["bytes"]==restored.stat().st_size
    with pytest.raises(ValueError):bm.DirectoryReplica(root,root)
    with pytest.raises(ValueError):replica.retrieve("../escape",dest)

@pytest.mark.skipif(os.name!="posix",reason="Linux operator filesystem semantics")
def test_backup_corruption_and_disk_failure_fail_closed(tmp_path,monkeypatch):
    root=private(tmp_path/"primary");other=private(tmp_path/"replica")
    now=datetime.now(timezone.utc);old=fixture_backup(root,now-timedelta(days=60),1)
    recent=fixture_backup(root,now-timedelta(hours=2),2)
    source={"ONEBOARD_BACKUP_OPERATION_APPROVED":"YES","ONEBOARD_PRODUCTION_MODE":"true"}
    replica=bm.DirectoryReplica(other,root)
    replica.put(*recent)
    (other/recent[0].name).write_bytes(b"corrupt")
    with pytest.raises(RuntimeError):bm.manage(root,"fixture",source,retention_days=7,keep=2,replica=replica,now=now,min_free_mib=1)
    assert old[0].exists() and recent[0].exists()
    assert json.loads((root/"backup-status.json").read_text())["status"]=="failed"
    blank=private(tmp_path/"blank")
    monkeypatch.setattr(bm.shutil,"disk_usage",lambda path:SimpleNamespace(free=0))
    monkeypatch.setattr(bm,"backup",lambda *args:pytest.fail("Backup attempted on full disk"))
    with pytest.raises(RuntimeError):bm.manage(blank,"fixture",source,now=now,min_free_mib=1)
    assert json.loads((blank/"backup-status.json").read_text())["alert"]
    with pytest.raises(RuntimeError):bm.manage(blank,"fixture",{},now=now)

def test_private_operator_readiness_and_trace(monkeypatch):
    from apps.api.main import app
    monkeypatch.setattr(settings,"OPERATOR_METRICS_KEY","fixture-operator-"*3)
    monkeypatch.setattr(settings,"ONEBOARD_PRODUCTION_MODE",False)
    monkeypatch.setattr(ops,"dependencies",lambda **kwargs:{"ready":True,"database":"ready","schema":"local","scheduler":"ready","inference":"ready","disk":"ready"})
    c=TestClient(app)
    assert c.get("/ops/metrics").status_code==404
    headers={"X-Operator-Key":settings.OPERATOR_METRICS_KEY,"traceparent":"00-"+"a"*32+"-"+"b"*16+"-01"}
    response=c.get("/ready",headers=headers)
    assert response.status_code==200 and response.headers["traceparent"].split("-")[1]=="a"*32
    assert response.headers["X-Request-ID"]
    assert c.get("/ops/health",headers=headers).json()["inference"]=="ready"
    c.get("/private/unmatched-fixture?secret=not-logged")
    result=c.get("/ops/metrics",headers=headers).json()
    assert result["scope"]=="process_local" and "private/unmatched-fixture" not in json.dumps(result) and "not-logged" not in json.dumps(result)
    monkeypatch.setattr(ops,"dependencies",lambda **kwargs:{"ready":False})
    assert c.get("/ready").status_code==503 and c.get("/health").status_code==200
    ops.draining(True)
    try:assert c.get("/api/auth/me").status_code==503
    finally:ops.draining(False)

def test_probe_detects_disk_and_unavailable_database(tmp_path,monkeypatch):
    engine=create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE scheduled_job_leases (job_key text,last_success_at real,attempts integer)"))
    monkeypatch.setattr(settings,"ONEBOARD_PRODUCTION_MODE",False)
    monkeypatch.setattr(ops.shutil,"disk_usage",lambda path:SimpleNamespace(free=0))
    assert ops.dependencies(engine)["ready"] is False and ops.dependencies(engine)["disk"]=="exhausted"
    broken=SimpleNamespace(connect=lambda:(_ for _ in ()).throw(OSError("fixture")))
    result=ops.dependencies(broken)
    assert result["database"]=="unavailable" and not result["ready"]
    engine.dispose()

@pytest.mark.skipif(os.name!="posix",reason="Linux operator filesystem semantics")
def test_operator_alert_transition_and_recovery(tmp_path):
    h={"ready":False,"database":"unavailable","schema":"unknown","scheduler":"failed_or_stale","disk":"exhausted","inference":"unavailable"}
    alerts=monitor.evaluate(h,{"inflight":101,"events":{"scheduler_failed":1},"pool":{"configured_max":4,"checkedout":4}},{"status":"failed"})
    assert {"service_not_ready","database_unavailable","background_job_failure","disk_unavailable","inference_unavailable","database_pool_saturated","backup_failed"}<=set(alerts)
    path=tmp_path/"alerts.json"
    first=monitor.transitions(path,alerts,now=100)
    repeated=monitor.transitions(path,alerts,now=200)
    assert first["opened"]==alerts and not repeated["opened"] and set(repeated["active"].values())=={100}
    resolved=monitor.transitions(path,[],now=300)
    assert resolved["resolved"]==alerts and not resolved["active"]

def test_capacity_and_rollback_fail_closed():
    load={"seconds":600,"unexpected_errors":0,"peak_api_rss_kib":512*1024,"requests":6000,"workers":2,"p95_ms":100}
    infer={"duration_seconds":600,"fallbacks":0,"peak_ollama_rss_kib":1024*1024,"genuine_requests":120,"p95_ms":200}
    result=plan(load,infer,2,40,8192)
    assert result["measured"]["api_requests_per_second"]==10 and result["planning"]["fits_configured_budget"]
    assert not plan(load,infer,4,20,1024)["planning"]["fits_configured_budget"]
    with pytest.raises(ValueError):plan({**load,"seconds":120},infer,2,40,8192)
    image="sha256:"+"a"*64
    assert assess(image,"024_batch_m_storage",["024_batch_m_storage"])["compatible"]
    assert not assess(image,"023_batch_l_providers",["024_batch_m_storage"])["compatible"]
    with pytest.raises(ValueError):assess("oneboard:latest","024_batch_m_storage",["024_batch_m_storage"])
