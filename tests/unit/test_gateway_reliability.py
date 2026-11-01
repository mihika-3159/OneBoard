"""Deterministic gateway regression tests: no Ollama daemon or paid models required."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from apps.api.core.config import settings
from apps.api.models.business import Business
from apps.api.routers import model_gateway_router as router
import importlib
gateway_module = importlib.import_module("apps.api.services.ollama_gateway")
from apps.api.services.ollama_gateway import OllamaGateway


class StubResponse:
    def __init__(self, status_code=200, data=None, invalid_json=False):
        self.status_code = status_code
        self.data = data
        self.invalid_json = invalid_json

    def json(self):
        if self.invalid_json:
            raise ValueError("malformed provider JSON")
        return self.data


def stub_http(monkeypatch, *, get=None, post=None, post_error=None):
    class StubClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            return get

        async def post(self, url, json):
            if post_error:
                raise post_error
            return post

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", StubClient)


@pytest.mark.asyncio
async def test_no_installed_models_are_not_reported_inference_ready(monkeypatch):
    stub_http(monkeypatch, get=StubResponse(data={"models": []}))
    health = await OllamaGateway().check_health()
    assert health["status"] == "connected"  # Daemon reachable, but not inference-ready.
    assert health["inference_available"] is False
    assert health["available_models"] == []


@pytest.mark.asyncio
async def test_installed_model_is_reported_inference_ready(monkeypatch):
    stub_http(monkeypatch, get=StubResponse(data={"models": [{"name": "qwen2.5:7b"}]}))
    health = await OllamaGateway().check_health()
    assert health["inference_available"] is True
    assert health["available_models"] == ["qwen2.5:7b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    StubResponse(data={"message": {}}),
    StubResponse(data={"message": {"content": ""}}),
    StubResponse(data={"unexpected": True}),
    StubResponse(invalid_json=True),
])
async def test_empty_or_malformed_ollama_response_is_not_real_inference(monkeypatch, response):
    stub_http(monkeypatch, post=response)
    result = await OllamaGateway().chat_complete(messages=[{"role": "user", "content": "test"}])
    assert result["simulated"] is True
    assert result["fallback_reason"] == "invalid_model_response"


@pytest.mark.asyncio
async def test_invalid_structured_response_is_not_real_inference(monkeypatch):
    stub_http(monkeypatch, post=StubResponse(data={"message": {"content": "not JSON"}}))
    result = await OllamaGateway().chat_complete(
        messages=[{"role": "user", "content": "test"}], format_json=True
    )
    assert result["simulated"] is True
    assert result["fallback_reason"] == "invalid_model_response"


@pytest.mark.asyncio
async def test_missing_model_reports_reason_without_success(monkeypatch):
    stub_http(monkeypatch, post=StubResponse(status_code=404))
    result = await OllamaGateway().chat_complete(messages=[{"role": "user", "content": "test"}])
    assert result["simulated"] is True
    assert result["fallback_reason"] == "model_unavailable"


@pytest.mark.asyncio
async def test_timeout_reports_reason_without_success(monkeypatch):
    stub_http(monkeypatch, post_error=httpx.ReadTimeout("timed out"))
    result = await OllamaGateway().chat_complete(messages=[{"role": "user", "content": "test"}])
    assert result["simulated"] is True
    assert result["fallback_reason"] == "timeout"


@pytest.mark.asyncio
async def test_valid_model_response_is_real_inference(monkeypatch):
    stub_http(monkeypatch, post=StubResponse(data={"message": {"content": "OK"}}))
    result = await OllamaGateway().chat_complete(messages=[{"role": "user", "content": "test"}])
    assert result["simulated"] is False
    assert result["content"] == "OK"
    assert "fallback_reason" not in result


class StubDB:
    def __init__(self, business):
        self.business = business
        self.commits = 0

    def query(self, model):
        assert model is Business
        return self

    def filter(self, *args):
        return self

    def first(self):
        return self.business

    def commit(self):
        self.commits += 1


def test_business_model_profile_is_persisted_and_tenant_scoped():
    biz_a = Business(id="tenant-a", name="A", founder_preferences={})
    biz_b = Business(id="tenant-b", name="B", founder_preferences={})
    db_a, db_b = StubDB(biz_a), StubDB(biz_b)
    user_a, user_b = SimpleNamespace(business_id="tenant-a"), SimpleNamespace(business_id="tenant-b")
    router.switch_model_profile(router.SwitchProfileRequest(profile="lightweight"), user_a, db_a)
    assert db_a.commits == 1
    assert router._business_model_profile(db_a, user_a.business_id) == "lightweight"
    assert router._business_model_profile(db_b, user_b.business_id) == settings.DEFAULT_MODEL_PROFILE
    assert router.ollama_gateway.get_model_for_task(profile="lightweight") != (
        router.ollama_gateway.get_model_for_task(profile=settings.DEFAULT_MODEL_PROFILE)
    )


def test_invalid_profile_is_rejected_without_mutation():
    db = StubDB(Business(id="tenant-a", name="A", founder_preferences={}))
    with pytest.raises(HTTPException) as exc:
        router.switch_model_profile(
            router.SwitchProfileRequest(profile="unrecognized"), SimpleNamespace(business_id="tenant-a"), db
        )
    assert exc.value.status_code == 422
    assert db.commits == 0


@pytest.mark.asyncio
async def test_status_uses_tenant_profile_not_process_global(monkeypatch):
    db = StubDB(Business(id="tenant-a", name="A", founder_preferences={"model_profile": "lightweight"}))
    monkeypatch.setattr(router.ollama_gateway, "check_health", AsyncMock(return_value={
        "status": "connected", "inference_available": False, "available_models": []
    }))
    result = await router.get_gateway_status(SimpleNamespace(business_id="tenant-a"), db)
    assert result["active_profile"] == "lightweight"
    assert result["inference_available"] is False


@pytest.mark.asyncio
async def test_benchmark_never_passes_simulated_fallback(monkeypatch):
    db = StubDB(Business(id="tenant-a", name="A", founder_preferences={"model_profile": "lightweight"}))
    fake = AsyncMock(return_value={
        "content": "fallback", "model": "simulated", "simulated": True,
        "fallback_reason": "model_unavailable"
    })
    monkeypatch.setattr(router.ollama_gateway, "chat_complete", fake)
    result = await router.benchmark_gateway(SimpleNamespace(business_id="tenant-a"), db)
    assert result["status"] == "simulated_fallback"
    assert result["inference_available"] is False
    assert result["fallback_reason"] == "model_unavailable"
    assert fake.await_args.kwargs["model"] == settings.MODEL_PROFILES["lightweight"]["chat_model"]
