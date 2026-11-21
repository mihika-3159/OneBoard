"""A sandbox adapter must never misrepresent a simulated send as delivery."""
from apps.api.services.workflow_engine import ToolRegistry


def test_demo_email_does_not_claim_delivery():
    result = ToolRegistry.send_email_action(
        db=None,
        business_id="test-tenant",
        recipient="example@example.invalid",
        subject="test",
        body="test",
    )
    assert result["delivered"] is False
    assert result["status"] == "simulated"
    assert result["channel"] == "demo_email"
