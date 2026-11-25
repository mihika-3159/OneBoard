"""CI gate, cancellation, UTC and secret scanning regressions."""
import asyncio
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import Mock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apps.api.core.database import Base
from apps.api.core.config import settings
from apps.api.services.durable_jobs import claim_job,finish_job
from apps.api.services.scheduler_service import SchedulerService
from scripts.require_test_suite import verify_report
from scripts.check_tracked_secrets import inspect

@pytest.mark.parametrize("case",['<skipped/>','<failure/>','<error/>'])
def test_required_ci_rejects_skipped_or_failed(tmp_path,case):
    f=tmp_path/'report.xml'
    f.write_text('<testsuite><testcase classname="required" name="one">'+case+'</testcase></testsuite>')
    with pytest.raises(SystemExit):
        verify_report(f,1)

def test_required_ci_rejects_missing_or_duplicate_cases(tmp_path):
    f=tmp_path/'report.xml'
    f.write_text('<testsuite/>')
    with pytest.raises(SystemExit):
        verify_report(f,1)
    f.write_text('<testsuite><testcase classname="required" name="one"/><testcase classname="required" name="one"/></testsuite>')
    with pytest.raises(SystemExit):
        verify_report(f,2)
    f.write_text('<testsuite><testcase classname="required" name="one"/></testsuite>')
    verify_report(f,1)

def test_tracked_secret_detector_blocks_private_material_and_environment():
    assert inspect(".env",b"SYNTHETIC=value")
    assert inspect("example.txt",b"ghp_"+b"A"*36)==["GitHub token"]
    assert inspect("example.txt",b"-----BEGIN "+b"PRIVATE KEY-----")==["private key"]
    assert not inspect(".env.example",b"AUTH_SECRET_KEY=replace-me")

def test_monitor_utc_and_configured_interval(monkeypatch):
    monkeypatch.setattr(settings,"SCHEDULER_INTERVAL_SECONDS",90)
    service=SchedulerService()
    assert str(service.scheduler.timezone)=="UTC"
    service.scheduler=Mock(running=False)
    service.start()
    assert service.scheduler.add_job.call_args.kwargs["seconds"]==90
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            # The two UTC offsets represent the same instant, including a DST boundary.
            a=datetime(2026,11,1,5,30,tzinfo=timezone.utc)
            b=a.astimezone(timezone(timedelta(hours=-4)))
            assert a.timestamp()==b.timestamp()
            token=claim_job(db,"utc",now=a.timestamp())
            assert finish_job(db,"utc",token,True,now=b.timestamp(),interval_seconds=90)
            assert claim_job(db,"utc",now=a.timestamp()+89) is None
            assert claim_job(db,"utc",now=a.timestamp()+90)
    finally:
        engine.dispose()

@pytest.mark.asyncio
async def test_cancelled_inference_releases_slot(monkeypatch):
    import importlib
    gateway_module=importlib.import_module("apps.api.services.ollama_gateway")
    entered=asyncio.Event()
    calls=0
    class Response:
        status_code=200
        def json(self): return {"done":True,"message":{"content":"synthetic"}}
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): return False
        async def post(self,url,json):
            nonlocal calls
            calls+=1
            if calls<=2:
                entered.set()
                await asyncio.Event().wait()
            return Response()
    monkeypatch.setattr(gateway_module.httpx,"AsyncClient",Client)
    gateway=gateway_module.OllamaGateway()
    prompt=[{"role":"user","content":"synthetic"}]
    tasks=[asyncio.create_task(gateway.chat_complete(prompt)) for _ in range(2)]
    await asyncio.wait_for(entered.wait(),timeout=2)
    for _ in range(100):
        if calls==2: break
        await asyncio.sleep(.01)
    assert calls==2
    for task in tasks: task.cancel()
    outcomes=await asyncio.gather(*tasks,return_exceptions=True)
    assert all(isinstance(x,asyncio.CancelledError) for x in outcomes)
    assert all(not x["simulated"] for x in await asyncio.gather(gateway.chat_complete(prompt),gateway.chat_complete(prompt)))
