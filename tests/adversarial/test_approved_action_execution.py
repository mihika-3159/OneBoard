"""Approved executable checkpoints must run exactly once, not disappear."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from apps.api.services.workflow_engine import WorkflowEngine


def resume_fixture(node_type, node_data):
    engine = WorkflowEngine()
    wf = SimpleNamespace(
        name="Approval test",
        is_active=True, is_valid=True,
        nodes=[
            {"id": "start", "type": "trigger", "data": {}},
            {"id": "risky", "type": node_type, "data": node_data},
            {"id": "finish", "type": "trigger", "data": {}},
        ],
        edges=[{"source": "start", "target": "risky"},
               {"source": "risky", "target": "finish"}],
    )
    from apps.api.services.workflow_effects import canonical_digest
    payload={"step_id":"risky","node_data":node_data,"resolved_data":node_data,"effect_preview":None,
             "action_digest":engine._action_digest(wf.nodes[1]),"definition_digest":engine._definition_digest(wf),"run_id":"run-1"}
    payload["payload_digest"]=canonical_digest(payload)
    request = SimpleNamespace(status="pending", payload=payload)
    run = SimpleNamespace(
        id="run-1", business_id="biz-1", workflow_id="wf-1",
        status="awaiting_approval", current_step_id="risky",
        step_results={"start": {"status": "success"}},
        verification_details={
            "node_order": ["start", "risky", "finish"],
            "definition_digest": engine._definition_digest(wf),
        },
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [request, run, wf]
    db.query.return_value.filter.return_value.update.return_value = 1
    engine._execute_steps = MagicMock(return_value=run)
    engine._dispatch_node_tool = MagicMock(return_value={"delivered": False, "status": "simulated"})
    return engine, db, run


def test_approved_risky_action_executes_before_downstream():
    engine, db, run = resume_fixture("action", {"risk": "high", "connector": "demo_email"})
    result = engine.approve_and_resume_run(db, "run-1", "approval-1", business_id="biz-1")
    assert result is run
    engine._dispatch_node_tool.assert_called_once_with(
        db, "biz-1", "action", {"risk": "high", "connector": "demo_email"}
    )
    step_results = engine._execute_steps.call_args.args[5]
    assert step_results["risky"]["status"] == "success"
    assert step_results["risky"]["result"]["status"] == "simulated"
    assert engine._execute_steps.call_args.args[4] == 2


def test_approval_control_checkpoint_does_not_dispatch():
    engine, db, run = resume_fixture("approval", {"label": "Confirm"})
    engine.approve_and_resume_run(db, "run-1", "approval-1", business_id="biz-1")
    engine._dispatch_node_tool.assert_not_called()
    assert engine._execute_steps.call_args.args[5]["risky"]["status"] == "approved"


def test_failed_approved_action_stops_downstream():
    engine, db, run = resume_fixture("action", {"risk": "high", "connector": "unsupported"})
    engine._dispatch_node_tool.side_effect = ValueError("Unsupported workflow tool")
    result = engine.approve_and_resume_run(db, "run-1", "approval-1", business_id="biz-1")
    assert result.status == "failed"
    assert result.step_results["risky"]["status"] == "failed"
    engine._execute_steps.assert_not_called()
