"""P1 resource and truthfulness matrix for local Ollama.

No external Ollama host, cloud LLM, large download, or paid service is used.
"""
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api.models.business import Business
from apps.api.routers import model_gateway_router as router
from apps.api.services.ollama_gateway import OllamaGateway
import importlib

gateway_module = importlib.import_module("apps.api.services.ollama_gateway")


class Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.payload = payload

    def json(self):
        return self.payload


def install_fake_http(monkeypatch, response):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            return response

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", FakeClient)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    Response(payload={"message": {"content": "partial"}}),
    Response(payload={"done": False, "message": {"content": "unfinished"}}),
    Response(payload={"done": True, "model": "wrong-model:latest",
                      "message": {"content": "not the requested model"}}),
    Response(payload={"done": True, "message": {"content": "null"}}),
    Response(payload={"done": True, "message": {"content": '["not", "an", "object"]'}}),
])
async def test_partial_model_mismatch_or_nonobject_json_not_reported_as_real(
    monkeypatch, response
):
    install_fake_http(monkeypatch, response)
    result = await OllamaGateway().chat_complete(
        messages=[{"role": "user", "content": "synthetic"}],
        model="qwen2.5:1.5b", format_json=True,
    )
    assert result["simulated"] is True
    assert result["fallback_reason"] == "invalid_model_response"
    assert "simulated" in result["model"]


@pytest.mark.asyncio
async def test_bounded_concurrent_requests_reject_third_without_provider_request(monkeypatch):
    entered = 0
    peak = 0
    released = asyncio.Event()
    two_in = asyncio.Event()

    class HoldingClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            nonlocal entered, peak
            entered += 1
            peak = max(peak, entered)
            if entered == 2:
                two_in.set()
            await released.wait()
            entered -= 1
            return Response(payload={
                "done": True,
                "model": json["model"],
                "message": {"content": "synthetic response"},
            })

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", HoldingClient)
    gateway = OllamaGateway()
    gateway._queue_timeout_seconds = 0.02
    prompts = [{"role": "user", "content": "no real data"}]
    first = asyncio.create_task(gateway.chat_complete(prompts))
    second = asyncio.create_task(gateway.chat_complete(prompts))
    try:
        await asyncio.wait_for(two_in.wait(), timeout=2)
        third = await gateway.chat_complete(prompts)
        assert third["simulated"] is True
        assert third["fallback_reason"] == "capacity_exceeded"
        assert entered == 2
        assert peak == 2
    finally:
        released.set()
    done = await asyncio.gather(first, second)
    assert all(x["simulated"] is False for x in done)


@pytest.mark.asyncio
async def test_provider_transport_error_does_not_log_private_prompt(monkeypatch, caplog):
    class ErrorClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            raise RuntimeError("sensitive-test-prompt-seen-by-model")

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", ErrorClient)
    caplog.set_level(logging.WARNING)
    result = await OllamaGateway().chat_complete([
        {"role": "user", "content": "sensitive-test-prompt-seen-by-model"}
    ])
    assert result["simulated"] is True
    assert "sensitive-test-prompt-seen-by-model" not in caplog.text


class FakeDB:
    def __init__(self, business):
        self.business = business

    def query(self, model):
        assert model is Business
        return self

    def filter(self, *args):
        return self

    def first(self):
        return self.business


@pytest.mark.asyncio
@pytest.mark.parametrize("installed,should_be_ready", [
    ([], False),
    (["qwen2.5:7b"], False),
    (["qwen2.5:1.5b"], True),
    (["qwen2.5:1.5b", "qwen2.5:7b"], True),
])
async def test_selected_tenant_profile_model_must_exist(
    monkeypatch, installed, should_be_ready
):
    business = Business(
        id="tenant-a", name="Synthetic",
        founder_preferences={"model_profile": "lightweight"}
    )
    monkeypatch.setattr(
        router.ollama_gateway, "check_health",
        AsyncMock(return_value={
            "status": "connected",
            "inference_available": bool(installed),
            "available_models": installed,
        })
    )
    state = await router.get_gateway_status(
        SimpleNamespace(business_id="tenant-a"), FakeDB(business)
    )
    assert state["requested_model"] == "qwen2.5:1.5b"
    assert state["requested_model_installed"] is should_be_ready
    assert state["inference_available"] is should_be_ready
    if not should_be_ready:
        assert "not installed" in state["message"]
