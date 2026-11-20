"""Approval checkpoints must pin executable content, not only node IDs."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.api.services.workflow_engine import WorkflowEngine


def definition(connector="demo_finance", operation="read", label="Read invoices"):
    return SimpleNamespace(
        nodes=[
            {"id": "a", "type": "trigger", "data": {}},
            {"id": "b", "type": "approval", "data": {"label": "Approve"}},
            {"id": "c", "type": "action", "data": {
                "connector": connector, "operation": operation, "label": label,
            }},
        ],
        edges=[{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
    )


@pytest.mark.parametrize("changed", [
    definition(connector="demo_email"),
    definition(operation="send"),
    definition(label="Different action"),
])
def test_executable_changes_invalidate_approval(changed):
    engine = WorkflowEngine()
    original = definition()
    digest = engine._definition_digest(original)
    assert digest != engine._definition_digest(changed)

    request = SimpleNamespace(status="pending", payload={"step_id": "b"})
    run = SimpleNamespace(
        status="awaiting_approval", current_step_id="b",
        verification_details={"node_order": ["a", "b", "c"], "definition_digest": digest},
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [request, run, changed]
    with pytest.raises(ValueError, match="definition changed"):
        engine.approve_and_resume_run(db, "run-1", "approval-1", business_id="biz-1")
    db.commit.assert_not_called()


def test_digest_ignores_json_key_order():
    engine = WorkflowEngine()
    wf = definition()
    reordered = SimpleNamespace(
        nodes=[{"data": node["data"], "type": node["type"], "id": node["id"]}
               for node in wf.nodes],
        edges=[{"target": edge["target"], "source": edge["source"]}
               for edge in wf.edges],
    )
    assert engine._definition_digest(wf) == engine._definition_digest(reordered)
