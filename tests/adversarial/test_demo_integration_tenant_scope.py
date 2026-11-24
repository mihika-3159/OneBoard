"""P1 regression: mock provider records must not cross workspace boundaries.

Even a clearly labeled mock CRM contact list can reveal another demo
persona's records and mislead a founder when accessed outside the demo tenant.
This suite never invokes live integrations or creates provider accounts.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.api.core.config import settings
from apps.api.routers import integrations_router as router
from apps.api.services.seed_data import DEMO_BUSINESS_ID


@pytest.mark.parametrize("handler", [
    router.get_crm_contacts,
    router.get_finance_ledger,
    router.get_github_status,
])
@pytest.mark.parametrize("demo,production,business", [
    (False, False, DEMO_BUSINESS_ID),
    (True, True, DEMO_BUSINESS_ID),
    (True, False, "independent-business-123"),
    (False, True, "independent-business-123"),
])
def test_demo_records_inaccessible_outside_explicit_demo_workspace(
    monkeypatch, handler, demo, production, business
):
    monkeypatch.setattr(settings, "ONEBOARD_DEMO_MODE", demo)
    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", production)
    with pytest.raises(HTTPException) as exc:
        handler(current_user=SimpleNamespace(business_id=business))
    assert exc.value.status_code == 404
    assert "demo_crm" not in str(exc.value.detail)


@pytest.mark.parametrize("handler,expected", [
    (router.get_crm_contacts, "contacts"),
    (router.get_finance_ledger, "summary"),
    (router.get_github_status, "source"),
])
def test_demo_records_work_only_in_explicit_synthetic_workspace(
    monkeypatch, handler, expected
):
    monkeypatch.setattr(settings, "ONEBOARD_DEMO_MODE", True)
    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", False)
    data = handler(current_user=SimpleNamespace(business_id=DEMO_BUSINESS_ID))
    assert data["is_simulated"] is True
    assert expected in data


def test_sandbox_outbox_remains_scoped_to_its_own_tenant():
    from apps.api.services.integrations.demo_adapters import DemoEmailAdapter
    adapter = DemoEmailAdapter()
    adapter.send_email(
        "synthetic@example.invalid", "Synthetic", "No external email",
        business_id="tenant-a"
    )
    assert len(adapter.get_outbox("tenant-a")) == 1
    assert adapter.get_outbox("tenant-b") == []
