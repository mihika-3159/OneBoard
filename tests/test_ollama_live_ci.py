"""Real Ollama smoke tests. Run only in the dedicated live-model CI job."""
import os
import pytest
from apps.api.services.ollama_gateway import OllamaGateway

MODEL = os.environ.get("ONEBOARD_CI_OLLAMA_MODEL", "qwen2.5:0.5b")
URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

@pytest.mark.asyncio
async def test_live_ollama_health_and_chat():
    gateway = OllamaGateway(base_url=URL)
    health = await gateway.check_health()
    assert health["status"] == "connected", health
    assert MODEL in health["available_models"], health
    assert health["inference_available"] is True
    result = await gateway.chat_complete(
        [{"role": "user", "content": "Reply with one short sentence saying hello."}],
        model=MODEL,
    )
    assert result["simulated"] is False, result
    assert result["model"] == MODEL
    assert isinstance(result["content"], str) and result["content"].strip()
    assert result["duration_ms"] >= 0

@pytest.mark.asyncio
async def test_live_ollama_json_response():
    gateway = OllamaGateway(base_url=URL)
    result = await gateway.chat_complete(
        [{"role": "user", "content": 'Return a JSON object with a key "ok" and boolean value true. No other text.'}],
        model=MODEL,
        format_json=True,
    )
    assert result["simulated"] is False, result
    import json
    parsed = json.loads(result["content"])
    assert isinstance(parsed, dict), parsed

@pytest.mark.asyncio
async def test_missing_model_is_labeled_fallback():
    gateway = OllamaGateway(base_url=URL)
    result = await gateway.chat_complete(
        [{"role": "user", "content": "Hello"}],
        model="oneboard-ci-nonexistent-model:never",
    )
    assert result["simulated"] is True
    assert result["fallback_reason"] == "model_unavailable"
    assert "simulated" in result["model"].lower()

@pytest.mark.asyncio
async def test_offline_server_is_labeled_fallback():
    gateway = OllamaGateway(base_url="http://127.0.0.1:1")
    health = await gateway.check_health()
    assert health["status"] == "offline"
    result = await gateway.chat_complete(
        [{"role": "user", "content": "Hello"}],
        model=MODEL,
    )
    assert result["simulated"] is True
    assert result["fallback_reason"] == "provider_unavailable"
