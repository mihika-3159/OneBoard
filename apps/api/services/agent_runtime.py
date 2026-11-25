"""Durable, explicitly planned, read-only agent runtime.

Each HTTP advance claims at most one checkpoint. A crashed worker can be
recovered after its lease expires; old workers cannot publish a stale result.
No model-produced text is interpreted as an instruction, tool call or delegation.
"""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, and_
from sqlalchemy.exc import IntegrityError

from apps.api.models.agent_council import AgentRun
from apps.api.models.workflow import CustomAgent
from apps.api.models.memory import MemoryDocument, MemoryChunk
from apps.api.models.entities import Customer
from apps.api.services.financial_metrics import calculate_business_financials
from apps.api.services.inference_budget import inference_tenant
from apps.api.services.ollama_gateway import ollama_gateway
from apps.api.services.untrusted_content import DATA_BOUNDARY, quoted_data
from apps.api.services.tenant_storage import _lock

TOOLS = {"read_crm", "calculate_metrics", "read_memory", "analyze"}
TERMINAL = {"completed", "failed", "cancelled", "expired"}
MAX_STEPS = 12
MAX_ATTEMPTS = 2


def get_run(db, tenant, run_id):
    return db.query(AgentRun).filter_by(business_id=tenant, id=run_id, approval_state="runtime_read_only").first()


def serialize(run):
    state = run.status
    now = datetime.utcnow()
    if state not in TERMINAL and run.deadline and run.deadline <= now:
        state = "expired"
    if state == "running" and run.lease_until and run.lease_until <= now:
        state = "failed" if run.attempt_count >= MAX_ATTEMPTS else "recoverable"
    return {"id": run.id, "agent_id": run.agent_id, "goal": run.goal,
            "status": state, "next_step": run.next_step, "steps": len(run.planned_steps or []),
            "results": run.tool_results or [], "errors": run.errors or [],
            "deadline": run.deadline, "checkpoint_at": run.checkpoint_at,
            "external_effects_enabled": False}


def fingerprint(agent):
    data = {"version": agent.version, "prompt": agent.system_prompt, "model": agent.selected_model,
            "tools": agent.allowed_tools or [], "memory": agent.allowed_memory_collections or [],
            "approval": agent.requires_approval_for or [], "max_steps": agent.max_steps}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def load_agent(db, tenant, agent_id):
    agent = db.query(CustomAgent).filter_by(business_id=tenant, id=agent_id, status="active").first()
    if not agent:
        raise ValueError("Agent unavailable")
    return agent


def authorize(agent, step):
    tool = step["tool"]
    if tool not in TOOLS or tool in (agent.requires_approval_for or []):
        raise ValueError("Tool not permitted in read-only runtime")
    if tool != "analyze" and tool not in (agent.allowed_tools or []):
        raise ValueError("Tool not granted to agent")
    if tool == "read_memory":
        document_id = step.get("document_id")
        if not document_id or document_id not in (agent.allowed_memory_collections or []):
            raise ValueError("Document collection not granted to agent")
    elif step.get("document_id"):
        raise ValueError("Document scope only allowed for read_memory")


def plan_run(db, tenant, root_agent_id, goal, steps, key):
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 2000:
        raise ValueError("Invalid goal")
    if not isinstance(key, str) or not 8 <= len(key) <= 128:
        raise ValueError("Idempotency key required")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError("One to twelve steps required")
    canonical = [{"agent_id": s.get("agent_id"), "tool": s.get("tool"), "document_id": s.get("document_id")} for s in steps]
    request_hash = hashlib.sha256(json.dumps([root_agent_id, goal, canonical], sort_keys=True).encode()).hexdigest()
    _lock(db, tenant)
    previous = db.query(AgentRun).filter_by(business_id=tenant, idempotency_key=key).first()
    if previous:
        if previous.request_hash != request_hash:
            raise ValueError("Idempotency key used with a different request")
        return previous
    if canonical[0]["agent_id"] != root_agent_id:
        raise ValueError("First step must use the selected agent")
    if db.query(AgentRun).filter_by(business_id=tenant, approval_state="runtime_read_only").count() >= 1000:
        raise ValueError("Agent run storage limit reached")
    seen, counts, planned = set(), {}, []
    last = None
    for step in canonical:
        agent_id = step["agent_id"]
        if agent_id != last:
            if agent_id in seen:
                raise ValueError("Recursive handoff is not permitted")
            seen.add(agent_id)
            last = agent_id
        agent = load_agent(db, tenant, agent_id)
        authorize(agent, step)
        if step["tool"] == "read_memory" and not db.query(MemoryDocument.id).filter_by(
                business_id=tenant, id=step["document_id"]).first():
            raise ValueError("Document unavailable")
        counts[agent_id] = counts.get(agent_id, 0) + 1
        if counts[agent_id] > min(25, agent.max_steps or 0):
            raise ValueError("Agent step budget exceeded")
        planned.append({**step, "fingerprint": fingerprint(agent)})
    now = datetime.utcnow()
    run = AgentRun(business_id=tenant, agent_id=root_agent_id, goal=goal, planned_steps=planned,
                   idempotency_key=key, request_hash=request_hash, approval_state="runtime_read_only",
                   status="ready", next_step=0, attempt_count=0, tool_results=[], errors=[],
                   deadline=now + timedelta(minutes=15), checkpoint_at=now)
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.query(AgentRun).filter_by(business_id=tenant, idempotency_key=key).first()
        if previous and previous.request_hash == request_hash:
            return previous
        raise ValueError("Conflicting agent execution request")
    return run


def expire_or_recover(db, tenant, run_id):
    now = datetime.utcnow()
    query = db.query(AgentRun).filter_by(business_id=tenant, id=run_id, approval_state="runtime_read_only")
    query.filter(AgentRun.status.notin_(TERMINAL), AgentRun.deadline <= now).update(
        {"status": "expired", "lease_owner": None, "lease_until": None, "checkpoint_at": now},
        synchronize_session=False)
    query.filter(AgentRun.status == "running", AgentRun.lease_until <= now,
                 AgentRun.attempt_count >= MAX_ATTEMPTS).update(
        {"status": "failed", "lease_owner": None, "lease_until": None, "checkpoint_at": now,
         "errors": ["Checkpoint recovery attempt budget exhausted"]}, synchronize_session=False)
    db.commit()
    return get_run(db, tenant, run_id)


def claim(db, tenant, run_id):
    run = expire_or_recover(db, tenant, run_id)
    if not run or run.status in TERMINAL:
        return run, None
    now = datetime.utcnow()
    owner = str(uuid4())
    changed = db.query(AgentRun).filter_by(business_id=tenant, id=run_id, next_step=run.next_step).filter(
        AgentRun.deadline > now, AgentRun.attempt_count < MAX_ATTEMPTS,
        or_(AgentRun.status == "ready", and_(AgentRun.status == "running", AgentRun.lease_until <= now))
    ).update({"status": "running", "lease_owner": owner, "lease_until": now + timedelta(seconds=75),
              "attempt_count": AgentRun.attempt_count + 1, "checkpoint_at": now}, synchronize_session=False)
    db.commit()
    return get_run(db, tenant, run_id), owner if changed == 1 else None


def checkpoint(db, tenant, run_id, owner, index, result=None, error=None):
    run = get_run(db, tenant, run_id)
    if not run:
        return None
    now = datetime.utcnow()
    results = list(run.tool_results or [])
    if result is not None:
        results.append(result)
    next_step = index + (result is not None)
    state = "failed" if error else ("completed" if next_step == len(run.planned_steps) else "ready")
    db.query(AgentRun).filter_by(business_id=tenant, id=run_id, status="running", lease_owner=owner, next_step=index).filter(
        AgentRun.lease_until > now, AgentRun.deadline > now
    ).update({"status": state, "next_step": next_step, "tool_results": results,
              "errors": list(run.errors or []) + ([error] if error else []),
              "lease_owner": None, "lease_until": None, "attempt_count": 0, "checkpoint_at": now},
             synchronize_session=False)
    db.commit()
    return get_run(db, tenant, run_id)


def cancel(db, tenant, run_id):
    db.query(AgentRun).filter_by(business_id=tenant, id=run_id, approval_state="runtime_read_only").filter(
        AgentRun.status.notin_(TERMINAL)).update(
        {"status": "cancelled", "lease_owner": None, "lease_until": None, "checkpoint_at": datetime.utcnow()},
        synchronize_session=False)
    db.commit()
    return get_run(db, tenant, run_id)


async def execute_step(db, tenant, run, step, agent):
    tool = step["tool"]
    if tool == "read_crm":
        rows = db.query(Customer).filter_by(business_id=tenant).order_by(Customer.id).limit(30).all()
        return {"customers": [{"id": row.id, "tier": row.tier, "status": row.status, "mrr": row.mrr} for row in rows]}
    if tool == "calculate_metrics":
        return calculate_business_financials(db, tenant)
    if tool == "read_memory":
        rows = db.query(MemoryChunk).join(MemoryDocument, (MemoryDocument.id == MemoryChunk.document_id) &
            (MemoryDocument.business_id == tenant)).filter(MemoryChunk.business_id == tenant,
            MemoryChunk.document_id == step["document_id"]).order_by(MemoryChunk.chunk_index).limit(5)
        if not db.query(MemoryDocument.id).filter_by(business_id=tenant,id=step["document_id"]).first():
            raise ValueError("Granted document no longer exists")
        return {"chunks": [{"id": row.id, "content": row.content[:500]} for row in rows]}
    # Handoffs use only previous bounded checkpoint data, quoted and explicitly
    # restricted to this run. Previous agents cannot grant tools to successors.
    previous = run.tool_results or []
    # Handoff data are explicitly filtered against the receiving agent's own
    # grants. Free-form analysis is never forwarded across agent boundaries.
    def can_share(entry):
        source_step = run.planned_steps[entry["step"]]
        try:
            authorize(agent, source_step)
        except ValueError:
            return False
        if source_step["tool"] == "read_memory":
            return bool(db.query(MemoryDocument.id).filter_by(
                business_id=tenant,id=source_step["document_id"]).first())
        return True

    visible = [p for p in previous if p["agent_id"] == agent.id and can_share(p)]
    handoffs = []
    for entry in previous:
        if entry["agent_id"] == agent.id:
            continue
        item = {"agent_id": entry["agent_id"], "tool": entry["tool"], "status": "completed"}
        source_step = run.planned_steps[entry["step"]]
        if entry["tool"] in TOOLS - {"analyze"} and can_share(entry):
            item["data"] = entry["data"]
        handoffs.append(item)
    with inference_tenant(tenant):
        response = await ollama_gateway.chat_complete(
            messages=[{"role": "user", "content": quoted_data("goal", run.goal, 1500) + "\n" +
                       quoted_data("own_checkpoints", json.dumps(visible, default=str), 1800) + "\n" +
                       quoted_data("handoff", json.dumps(handoffs, default=str), 1200)}],
            system_prompt=quoted_data("agent_config", agent.system_prompt, 1000) + " " + DATA_BOUNDARY,
            model=agent.selected_model)
    if response.get("simulated") or response.get("output_limit_reached") or not response.get("content"):
        raise ValueError("No complete genuine model result")
    return {"analysis": response["content"][:4000], "model": response.get("model"), "unverified": True}


async def advance(db, tenant, run_id):
    run, owner = claim(db, tenant, run_id)
    if not run or not owner:
        return run
    index = run.next_step
    step = run.planned_steps[index]
    try:
        agent = load_agent(db, tenant, step["agent_id"])
        if fingerprint(agent) != step["fingerprint"]:
            raise ValueError("Agent configuration changed; create a new run")
        authorize(agent, step)
        value = await asyncio.wait_for(execute_step(db, tenant, run, step, agent), timeout=55)
        # Bound and normalize arbitrary numeric/date types before persistence.
        encoded = json.dumps(value, default=str, allow_nan=False)
        if len(encoded) > 16000:
            raise ValueError("Tool result exceeds checkpoint size")
        result = {"step": index, "agent_id": agent.id, "tool": step["tool"], "data": json.loads(encoded)}
        return checkpoint(db, tenant, run_id, owner, index, result=result)
    except asyncio.CancelledError:
        # No side effects occurred; the lease allows safe replay after expiry.
        db.rollback()
        raise
    except Exception:
        db.rollback()
        return checkpoint(db, tenant, run_id, owner, index, error="Step failed or permission changed")


async def run_remaining(db, tenant, run_id):
    """Advance only the persisted founder plan; do not spin on another lease."""
    run = get_run(db, tenant, run_id)
    for _ in range(MAX_STEPS):
        if not run or run.status in TERMINAL:
            break
        before = run.next_step
        run = await advance(db, tenant, run_id)
        if not run or run.status in TERMINAL or run.next_step == before:
            break
    return run
