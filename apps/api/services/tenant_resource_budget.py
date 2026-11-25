"""PostgreSQL-backed tenant budgets for expensive operations across workers.

Only invoked for production endpoints. This is not IP DDoS mitigation, a
global model semaphore, or an externally verified load benchmark.
"""
from __future__ import annotations
import hashlib
import math
import time
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.models.operations import TenantResourceWindow

POLICIES = {
    "inference_tokens": (65_536, 60),
    "ai_command": (30, 60),
    "ai_benchmark": (6, 60),
    "memory_search": (120, 60),
    "customer_import": (6, 300),
    "financial_reconciliation": (20, 60),
    "workflow_generate": (10, 60),
    "workflow_execute": (30, 60),
    "agent_generate": (10, 60),
    "agent_test": (20, 60),
    "agent_run": (20, 60),
    "document_upload": (10, 300),
    "council_deliberate": (6, 60),
    "workspace_delete": (3, 300),
    "data_export": (3, 300),
}


def consume_tenant_budget(
    db: Session, business_id: str, resource: str, *,
    now: float | None = None, cost: int = 1,
) -> dict:
    if resource not in POLICIES or not business_id:
        raise ValueError("Unknown tenant resource or missing tenant")
    limit, duration = POLICIES[resource]
    if isinstance(cost, bool) or not isinstance(cost, int) or cost < 1:
        raise ValueError("Resource cost must be a positive integer")
    if cost > limit:
        raise HTTPException(status_code=429, detail="Request exceeds the tenant resource budget.")
    now = time.time() if now is None else now
    if not math.isfinite(now) or now < 0:
        raise ValueError("Invalid request clock")
    if db.get_bind().dialect.name == "postgresql":
        from apps.api.services.tenant_storage import _lock
        _lock(db,business_id)
        key = int.from_bytes(
            hashlib.sha256((business_id + ":budget:" + resource).encode()).digest()[:8],
            "big", signed=True
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    row = db.query(TenantResourceWindow).filter(
        TenantResourceWindow.business_id == business_id,
        TenantResourceWindow.resource == resource,
    ).first()
    if row is None:
        row = TenantResourceWindow(
            business_id=business_id, resource=resource,
            attempt_count=cost, window_started_at=now,
        )
        db.add(row)
    elif now < row.window_started_at or now - row.window_started_at >= duration:
        row.window_started_at = now
        row.attempt_count = cost
    elif row.attempt_count + cost > limit:
        retry = max(1, math.ceil(duration - (now - row.window_started_at)))
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail="Tenant resource budget exhausted. Retry after the window.",
            headers={"Retry-After": str(retry)},
        )
    else:
        row.attempt_count += cost
    db.commit()
    return {"resource": resource, "remaining": limit - row.attempt_count,
            "window_seconds": duration}
