"""DAG validation must reject malformed graphs before execution."""
import pytest
from apps.api.services.workflow_engine import WorkflowEngine


@pytest.mark.parametrize("definition,error", [
    ({"nodes": [], "edges": []}, "at least one"),
    (None, "object"),
    ({"nodes": [{"id": "a"}], "edges": [{"source": [], "target": "a"}]}, "endpoints"),
    ({"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": {}}]}, "endpoints"),
    ({"nodes": [{"id": "a"}, {"id": "a"}], "edges": []}, "Duplicate"),
    ({"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": "missing"}]}, "Dangling"),
    ({"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]}, "Cycle"),
    ({"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"source": "a", "target": "b"}, {"source": "a", "target": "b"}]}, "duplicate edge"),
    ({"nodes": [{"id": ""}], "edges": []}, "nonempty"),
    ({"nodes": [{"id": "a", "data": []}], "edges": []}, "data"),
])
def test_rejects_invalid_workflow_graphs(definition, error):
    result = WorkflowEngine().validate_workflow(definition)
    assert result["is_valid"] is False
    assert error.lower() in result["error"].lower()


def test_stable_topological_order_independent_of_input_order():
    definition = {
        "nodes": [{"id": "finish"}, {"id": "start"}, {"id": "middle"}],
        "edges": [{"source": "start", "target": "middle"}, {"source": "middle", "target": "finish"}],
    }
    assert [n["id"] for n in WorkflowEngine()._ordered_nodes(definition)] == ["start", "middle", "finish"]


def test_workflow_graph_size_limit():
    definition = {"nodes": [{"id": str(i)} for i in range(101)], "edges": []}
    result = WorkflowEngine().validate_workflow(definition)
    assert result["is_valid"] is False
    assert "limit" in result["error"].lower()
