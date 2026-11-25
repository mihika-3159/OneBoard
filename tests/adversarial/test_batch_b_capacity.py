import pytest
from apps.api.services import tenant_resource_budget as quota

@pytest.mark.parametrize("resource", ["workflow_generate", "workflow_execute",
    "agent_generate", "agent_test", "document_upload"])
def test_expensive_operations_have_finite_budgets(resource):
    limit, seconds = quota.POLICIES[resource]
    assert 0 < limit <= 30
    assert 0 < seconds <= 300
