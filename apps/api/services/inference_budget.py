"""Meter provider attempts against the tenant's shared inference budget."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException

from apps.api.core.config import settings
from apps.api.core.database import SessionLocal, scope_tenant_session
from apps.api.services.tenant_resource_budget import consume_tenant_budget


_inference_tenant = ContextVar("inference_tenant", default=None)


class TokenBudgetExceeded(Exception):
    pass


def current_inference_tenant():
    return _inference_tenant.get()


@contextmanager
def inference_tenant(tenant):
    token = _inference_tenant.set(tenant)
    try:
        yield
    finally:
        _inference_tenant.reset(token)


def _charge(tenant, cost):
    with SessionLocal() as db:
        db.info["oneboard_worker"] = True
        scope_tenant_session(db, tenant)
        try:
            consume_tenant_budget(db, tenant, "inference_tokens", cost=cost)
        except HTTPException as exc:
            if exc.status_code == 429:
                raise TokenBudgetExceeded() from exc
            raise


def estimated_tokens(payload):
    if "prompt" in payload:
        return max(1, len(payload["prompt"].encode("utf-8")))
    messages = payload["messages"]
    prompt = sum(16 + len(message["content"].encode("utf-8")) for message in messages)
    return 64 + prompt + payload["options"]["num_predict"]


async def charge_provider_attempt(payload):
    tenant = _inference_tenant.get()
    if settings.ONEBOARD_PRODUCTION_MODE and tenant:
        await asyncio.to_thread(_charge, tenant, estimated_tokens(payload))
