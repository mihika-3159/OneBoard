"""Regression checks for tenant alert freshness and scheduler idempotency."""
from unittest.mock import Mock
import pytest

from apps.api.services.scheduler_service import SchedulerService


def test_alerts_recomputed_for_every_read(monkeypatch):
    service = SchedulerService()
    calls = []

    def recompute(business_id=None):
        calls.append(business_id)
        service.active_alerts_by_business[business_id] = [
            {"id": "alert-1", "title": f"Updated {len(calls)}"}
        ]

    monkeypatch.setattr(service, "run_proactive_checks", recompute)
    first = service.get_alerts("tenant-a")
    second = service.get_alerts("tenant-a")
    assert first == [{"id": "alert-1", "title": "Updated 1"}]
    assert second == [{"id": "alert-1", "title": "Updated 2"}]
    assert calls == ["tenant-a", "tenant-a"]


def test_alerts_are_scoped_and_copies_are_returned(monkeypatch):
    service = SchedulerService()

    def recompute(business_id=None):
        service.active_alerts_by_business[business_id] = [{"id": business_id}]

    monkeypatch.setattr(service, "run_proactive_checks", recompute)
    a = service.get_alerts("tenant-a")
    b = service.get_alerts("tenant-b")
    assert a == [{"id": "tenant-a"}]
    assert b == [{"id": "tenant-b"}]
    a.append({"id": "injected"})
    assert service.get_alerts("tenant-a") == [{"id": "tenant-a"}]
    with pytest.raises(ValueError, match="business ID"):
        service.get_alerts("")


def test_failed_refresh_does_not_return_stale_alerts(monkeypatch):
    service = SchedulerService()
    service.active_alerts_by_business["tenant-a"] = [{"id": "stale"}]

    def broken(business_id=None):
        raise RuntimeError("database offline")

    monkeypatch.setattr(service, "run_proactive_checks", broken)
    with pytest.raises(RuntimeError, match="database offline"):
        service.get_alerts("tenant-a")


def test_start_is_idempotent_and_coalesces_jobs():
    service = SchedulerService()
    scheduler = Mock()
    scheduler.running = False
    service.scheduler = scheduler
    service.start()
    assert scheduler.add_job.call_count == 1
    assert scheduler.add_job.call_args.kwargs["max_instances"] == 1
    assert scheduler.add_job.call_args.kwargs["coalesce"] is True
    scheduler.running = True
    service.start()
    assert scheduler.add_job.call_count == 1
    assert scheduler.start.call_count == 1
