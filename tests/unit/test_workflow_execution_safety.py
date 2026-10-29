"""Regression tests for issue #2: DAG execution and approval safety.

All tests use an isolated in-memory database; no external services are called.
"""
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.core.database import Base
import apps.api.models.business  # noqa: F401 - register ORM tables
import apps.api.models.goals_tasks  # noqa: F401
import apps.api.models.entities  # noqa: F401
import apps.api.models.decision_evidence  # noqa: F401
import apps.api.models.agent_council  # noqa: F401
import apps.api.models.memory  # noqa: F401
import apps.api.models.integrations  # noqa: F401
from apps.api.models.workflow import WorkflowDefinition, WorkflowRun, ApprovalRequest
from apps.api.services.workflow_engine import workflow_engine


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_workflow(db, nodes, edges=None, business_id="tenant-a"):
    workflow = WorkflowDefinition(
        business_id=business_id,
        name="Test process",
        nodes=nodes,
        edges=edges or [],
        is_valid=True,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def node(node_id, node_type="action"):
    return {"id": node_id, "type": node_type, "data": {"label": node_id}}


def edges(*pairs):
    return [{"id": f"{a}-{b}", "source": a, "target": b} for a, b in pairs]


def test_dag_uses_edges_not_stored_node_order(db):
    wf = make_workflow(
        db, [node("last"), node("first", "trigger"), node("middle")],
        edges(("first", "middle"), ("middle", "last")),
    )
    with patch.object(workflow_engine, "_dispatch_node_tool", return_value={"ok": True}) as dispatch:
        run = workflow_engine.execute_workflow(db, "tenant-a", wf.id)
    assert [call.args[3]["label"] for call in dispatch.call_args_list] == [
        "first", "middle", "last"
    ]
    assert run.status == "completed"
    assert run.verified_success is False
    assert run.verification_details["node_order"] == ["first", "middle", "last"]


def test_approval_resumes_remaining_steps_exactly_once(db):
    wf = make_workflow(
        db, [node("after"), node("gate", "approval"), node("before", "trigger")],
        edges(("before", "gate"), ("gate", "after")),
    )
    with patch.object(workflow_engine, "_dispatch_node_tool", return_value={"ok": True}) as dispatch:
        run = workflow_engine.execute_workflow(db, "tenant-a", wf.id)
        assert run.status == "awaiting_approval"
        assert dispatch.call_count == 1
        approval = db.query(ApprovalRequest).filter_by(workflow_run_id=run.id).one()
        assert "after" not in run.step_results
        resumed = workflow_engine.approve_and_resume_run(db, run.id, approval.id, "tenant-a")
        assert resumed.status == "completed"
        assert dispatch.call_count == 2
        assert [c.args[3]["label"] for c in dispatch.call_args_list] == ["before", "after"]
        assert resumed.step_results["gate"]["status"] == "approved"
        assert resumed.step_results["after"]["status"] == "success"
        assert resumed.verified_success is False
        with pytest.raises(ValueError):
            workflow_engine.approve_and_resume_run(db, run.id, approval.id, "tenant-a")
        assert dispatch.call_count == 2


def test_multiple_approval_gates_each_require_separate_approval(db):
    wf = make_workflow(
        db,
        [node("first", "trigger"), node("gate1", "approval"),
         node("middle"), node("gate2", "approval"), node("last")],
        edges(("first", "gate1"), ("gate1", "middle"),
              ("middle", "gate2"), ("gate2", "last")),
    )
    with patch.object(workflow_engine, "_dispatch_node_tool", return_value={"ok": True}) as dispatch:
        run = workflow_engine.execute_workflow(db, "tenant-a", wf.id)
        gate1 = db.query(ApprovalRequest).filter_by(workflow_run_id=run.id).one()
        run = workflow_engine.approve_and_resume_run(db, run.id, gate1.id, "tenant-a")
        assert run.status == "awaiting_approval"
        assert run.current_step_id == "gate2"
        assert dispatch.call_count == 2
        gate2 = db.query(ApprovalRequest).filter_by(
            workflow_run_id=run.id, status="pending"
        ).one()
        run = workflow_engine.approve_and_resume_run(db, run.id, gate2.id, "tenant-a")
        assert run.status == "completed"
        assert dispatch.call_count == 3


def test_dry_run_never_dispatches_or_creates_approvals(db):
    wf = make_workflow(
        db, [node("first", "trigger"), node("gate", "approval"), node("last")],
        edges(("first", "gate"), ("gate", "last")),
    )
    with patch.object(workflow_engine, "_dispatch_node_tool") as dispatch:
        run = workflow_engine.execute_workflow(db, "tenant-a", wf.id, dry_run=True)
    dispatch.assert_not_called()
    assert run.status == "completed"
    assert run.verified_success is False
    assert run.verification_details["dry_run"] is True
    assert all(step["status"] == "simulated" for step in run.step_results.values())
    assert db.query(ApprovalRequest).count() == 0


@pytest.mark.parametrize("nodes,graph", [
    ([node("same"), node("same")], []),
    ([node("a"), node("b")], edges(("a", "b"), ("b", "a"))),
    ([node("a")], edges(("a", "missing"))),
])
def test_invalid_dag_rejected_before_creating_run(db, nodes, graph):
    wf = make_workflow(db, nodes, graph)
    with pytest.raises(ValueError):
        workflow_engine.execute_workflow(db, "tenant-a", wf.id)
    assert db.query(WorkflowRun).count() == 0


def test_unsupported_tool_is_failure_not_fake_success(db):
    wf = make_workflow(db, [
        {"id": "unknown", "type": "action", "data": {
            "label": "Unrecognized task", "connector": "not_configured"
        }}
    ])
    run = workflow_engine.execute_workflow(db, "tenant-a", wf.id)
    assert run.status == "failed"
    assert run.verified_success is False
    assert run.step_results["unknown"]["status"] == "failed"


def test_wrong_approval_cannot_resume_other_run(db):
    wf = make_workflow(db, [node("gate", "approval"), node("after")],
                       edges(("gate", "after")))
    with patch.object(workflow_engine, "_dispatch_node_tool", return_value={"ok": True}) as dispatch:
        run1 = workflow_engine.execute_workflow(db, "tenant-a", wf.id)
        run2 = workflow_engine.execute_workflow(db, "tenant-a", wf.id)
        request1 = db.query(ApprovalRequest).filter_by(workflow_run_id=run1.id).one()
        with pytest.raises(ValueError):
            workflow_engine.approve_and_resume_run(db, run2.id, request1.id, "tenant-a")
        assert run1.status == "awaiting_approval"
        assert run2.status == "awaiting_approval"
        assert request1.status == "pending"
        dispatch.assert_not_called()


def test_failed_step_after_approval_does_not_complete(db):
    wf = make_workflow(db, [node("gate", "approval"), node("broken")],
                       edges(("gate", "broken")))
    with patch.object(workflow_engine, "_dispatch_node_tool",
                      side_effect=RuntimeError("simulated tool failure")):
        run = workflow_engine.execute_workflow(db, "tenant-a", wf.id)
        approval = db.query(ApprovalRequest).filter_by(workflow_run_id=run.id).one()
        run = workflow_engine.approve_and_resume_run(db, run.id, approval.id, "tenant-a")
    assert run.status == "failed"
    assert run.verified_success is False
    assert run.step_results["broken"]["status"] == "failed"
