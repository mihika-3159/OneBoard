"""Noisy multi-tenant resource budgets are shared, bounded and fail closed."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.memory
import apps.api.models.workflow
import apps.api.models.integrations
import apps.api.models.goals_tasks
import apps.api.models.agent_council
import apps.api.models.decision_evidence
import apps.api.models.operations
from apps.api.models.operations import TenantResourceWindow
from apps.api.services import tenant_resource_budget as quota


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_one_tenant_cannot_starve_another(db, monkeypatch):
    monkeypatch.setitem(quota.POLICIES, "memory_search", (3, 60))
    assert quota.consume_tenant_budget(db, "tenant-a", "memory_search", now=100)["remaining"] == 2
    assert quota.consume_tenant_budget(db, "tenant-a", "memory_search", now=101)["remaining"] == 1
    assert quota.consume_tenant_budget(db, "tenant-a", "memory_search", now=102)["remaining"] == 0
    with pytest.raises(HTTPException) as exc:
        quota.consume_tenant_budget(db, "tenant-a", "memory_search", now=103)
    assert exc.value.status_code == 429
    assert 1 <= int(exc.value.headers["Retry-After"]) <= 60
    assert quota.consume_tenant_budget(db, "tenant-b", "memory_search", now=103)["remaining"] == 2
    assert db.query(TenantResourceWindow).count() == 2
    assert quota.consume_tenant_budget(db, "tenant-a", "memory_search", now=160)["remaining"] == 2


def test_budgets_are_independent_by_resource(db, monkeypatch):
    monkeypatch.setitem(quota.POLICIES, "ai_command", (1, 60))
    monkeypatch.setitem(quota.POLICIES, "customer_import", (1, 60))
    quota.consume_tenant_budget(db, "tenant-a", "ai_command", now=50)
    with pytest.raises(HTTPException):
        quota.consume_tenant_budget(db, "tenant-a", "ai_command", now=51)
    assert quota.consume_tenant_budget(db, "tenant-a", "customer_import", now=51)["remaining"] == 0


@pytest.mark.parametrize("resource,biz,now", [
    ("unknown", "tenant-a", 10), ("ai_command", "", 10),
    ("ai_command", "tenant-a", -1), ("ai_command", "tenant-a", float("nan")),
])
def test_invalid_usage_rejected_without_mutations(db, resource, biz, now):
    with pytest.raises(ValueError):
        quota.consume_tenant_budget(db, biz, resource, now=now)
    assert db.query(TenantResourceWindow).count() == 0
