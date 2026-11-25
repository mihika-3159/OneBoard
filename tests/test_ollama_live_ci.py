"""Real Ollama smoke tests. Run only in the dedicated live-model CI job."""
import os
import pytest
from apps.api.services.ollama_gateway import OllamaGateway

pytestmark = pytest.mark.skipif(os.environ.get("ONEBOARD_LIVE_OLLAMA_TESTS") != "1", reason="Only the dedicated Ollama CI job runs live inference")

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


@pytest.mark.asyncio
async def test_real_embedding_index_and_retrieval(monkeypatch):
    """Real CPU model, synthetic local SQLite; no external inference provider."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from apps.api.core.database import Base
    from apps.api.models.operations import SemanticVector
    from apps.api.services import semantic_index
    from apps.api.services.memory_engine import memory_engine

    model = os.environ.get("ONEBOARD_CI_EMBEDDING_MODEL", "all-minilm")
    gateway = OllamaGateway(base_url=URL)
    monkeypatch.setattr(gateway, "get_model_for_task", lambda task: model)
    monkeypatch.setattr(semantic_index, "ollama_gateway", gateway)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            phrase = "Quarterly revenue increased after subscription renewals."
            related = await gateway.genuine_embedding("Subscription renewals boosted quarterly sales.", model)
            unrelated = await gateway.genuine_embedding("A penguin swims in icy ocean water.", model)
            anchor = await gateway.genuine_embedding(phrase, model)
            assert anchor and related and unrelated
            assert len(anchor) == len(related) == len(unrelated)
            assert semantic_index.cosine(anchor, related) > semantic_index.cosine(anchor, unrelated)
            doc = memory_engine.add_document_with_chunks(db, "synthetic-live-ci", "Synthetic", phrase)
            assert (await semantic_index.index_pending(db, "synthetic-live-ci", gateway=gateway))["indexed"] == 1
            stored = db.query(SemanticVector).one()
            assert stored.dimension == len(anchor) and stored.model == model
            result = await semantic_index.retrieve(db, "synthetic-live-ci", phrase, 5)
            assert result and result[0]["document_id"] == doc.id
            assert result[0]["score"] > 0.99
            assert result[0]["search_strategy"] == "exact_cosine_small_corpus"
            assert await semantic_index.retrieve(db, "another-tenant", phrase, 5) == []
    finally:
        engine.dispose()
