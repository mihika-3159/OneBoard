import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.api.services import inference_budget as budget
from apps.api.services.tenant_resource_budget import consume_tenant_budget


def test_weighted_reservations_respect_existing_window_and_do_not_increment_on_rejection():
    db = Mock()
    db.get_bind.return_value.dialect.name = "sqlite"
    row = SimpleNamespace(window_started_at=100, attempt_count=65_500)
    db.query.return_value.filter.return_value.first.return_value = row

    reservation = consume_tenant_budget(db, "tenant-a", "inference_tokens", now=101, cost=36)
    assert reservation["remaining"] == 0
    assert row.attempt_count == 65_536

    with pytest.raises(budget.HTTPException) as rejected:
        consume_tenant_budget(db, "tenant-a", "inference_tokens", now=102, cost=1)
    assert rejected.value.status_code == 429
    assert row.attempt_count == 65_536
    db.rollback.assert_called_once()

    reservation = consume_tenant_budget(db, "tenant-a", "inference_tokens", now=160, cost=20)
    assert row.attempt_count == 20
    assert reservation["remaining"] == 65_516


@pytest.mark.asyncio
async def test_concurrent_requests_meter_only_their_own_tenant(monkeypatch):
    monkeypatch.setattr(budget.settings, "ONEBOARD_PRODUCTION_MODE", True)
    charge = Mock()
    monkeypatch.setattr(budget, "_charge", charge)

    async def send(tenant, text):
        with budget.inference_tenant(tenant):
            await asyncio.sleep(0)
            await budget.charge_provider_attempt({"prompt": text})

    await asyncio.gather(send("tenant-a", "hello"), send("tenant-b", "Δ"))
    assert sorted(call.args for call in charge.call_args_list) == [
        ("tenant-a", 5), ("tenant-b", 2)
    ]
