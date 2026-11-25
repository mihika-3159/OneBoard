import asyncio
from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apps.api.core.database import Base
from apps.api.models.business import Business
from apps.api.models.workflow import CustomAgent
from apps.api.models.agent_council import AgentRun
from apps.api.services import agent_runtime as runtime


@pytest.fixture
def setup():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        a, b = Business(name="A"), Business(name="B")
        db.add_all([a,b]); db.commit()
        agents = [CustomAgent(business_id=t.id, name="Agent", role_title="Reader", system_prompt="Review records",
                             allowed_tools=["read_crm"], max_steps=2) for t in (a,a,b)]
        db.add_all(agents); db.commit()
        yield db, a.id, b.id, [x.id for x in agents]
    engine.dispose()


def step(agent, tool="read_crm"):
    return {"agent_id": agent, "tool": tool}


def test_idempotency_tenant_permission_and_nonrecursive_handoff(setup):
    db, a, b, (one,two,foreign) = setup
    plan = [step(one),step(two)]
    run = runtime.plan_run(db,a,one,"Review",plan,"request-1")
    assert runtime.plan_run(db,a,one,"Review",plan,"request-1").id == run.id
    assert runtime.get_run(db,b,run.id) is None
    for invalid in ([step(one),step(foreign)], [step(one,"send_email")],
                    [step(one,"read_memory")], [step(one),step(two),step(one)],
                    [step(one),step(one),step(one)]):
        with pytest.raises(ValueError):
            runtime.plan_run(db,a,one,"Review",invalid,"invalid-key")
    assert asyncio.run(runtime.advance(db,a,run.id)).next_step == 1
    completed = asyncio.run(runtime.advance(db,a,run.id))
    assert completed.status == "completed"
    assert [r["agent_id"] for r in completed.tool_results] == [one,two]
    assert asyncio.run(runtime.advance(db,a,run.id)).next_step == 2


def test_fenced_recovery_and_cancellation(setup):
    db, a, _, (one,two,foreign) = setup
    run = runtime.plan_run(db,a,one,"Review",[step(one)],"request-2")
    run, old = runtime.claim(db,a,run.id)
    assert old and runtime.claim(db,a,run.id)[1] is None
    run.lease_until = datetime.utcnow() - timedelta(seconds=1); db.commit()
    run, new = runtime.claim(db,a,run.id)
    assert new and new != old
    assert runtime.checkpoint(db,a,run.id,old,0,result={"stale":True}).next_step == 0
    runtime.cancel(db,a,run.id)
    assert runtime.checkpoint(db,a,run.id,new,0,result={"late":True}).status == "cancelled"


def test_permission_change_fails_closed(setup):
    db,a,_,(one,two,foreign) = setup
    run = runtime.plan_run(db,a,one,"Review",[step(one)],"request-3")
    agent = db.get(CustomAgent,one)
    agent.allowed_tools = []; db.commit()
    assert asyncio.run(runtime.advance(db,a,run.id)).status == "failed"
