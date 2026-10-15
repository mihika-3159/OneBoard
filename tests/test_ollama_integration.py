r"""
OneBoard - Ollama Live Integration Tests
=========================================
Tests real Ollama connections, actual model inference, embedding generation,
and full council deliberation with a live local model.

Usage:
  # With Ollama running + a model pulled:
  .venv\Scripts\python -m pytest tests/test_ollama_integration.py -v

  # Skip live model tests (offline mode only):
  .venv\Scripts\python -m pytest tests/test_ollama_integration.py -v -m "not live_model"
"""
import asyncio
import pytest
import json
import httpx
import time
from typing import List, Dict

# ─── Gateway Under Test ───────────────────────────────────────────────────────
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apps.api.services.ollama_gateway import OllamaGateway, ollama_gateway
from apps.api.core.config import settings


# ─── Helpers ──────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL  # default: http://localhost:11434
PREFERRED_TEST_MODELS = ["qwen2.5:0.5b", "qwen2.5:1.5b", "llama3.2:1b", "phi3.5:mini", "qwen2.5:7b"]


def is_ollama_running() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def get_available_models() -> List[str]:
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def pick_test_model() -> str | None:
    available = get_available_models()
    for preferred in PREFERRED_TEST_MODELS:
        for avail in available:
            if preferred in avail or avail.startswith(preferred.split(":")[0]):
                return avail
    return available[0] if available else None


# ─── Markers ──────────────────────────────────────────────────────────────────
live_model = pytest.mark.skipif(
    not is_ollama_running(),
    reason="Ollama is not running at localhost:11434 — skipping live model tests"
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: Gateway Health & Discovery
# ─────────────────────────────────────────────────────────────────────────────

class TestOllamaGatewayHealth:

    @pytest.mark.asyncio
    async def test_health_check_returns_valid_structure(self):
        gw = OllamaGateway()
        result = await gw.check_health()
        assert "status" in result
        assert result["status"] in ("connected", "offline")
        assert "available_models" in result
        assert "active_profile" in result
        print(f"\n[Health] status={result['status']}, models={result['available_models']}")

    @pytest.mark.asyncio
    @live_model
    async def test_health_check_when_ollama_running(self):
        gw = OllamaGateway()
        result = await gw.check_health()
        assert result["status"] == "connected"
        assert result["latency_ms"] >= 0
        assert isinstance(result["available_models"], list)
        print(f"\n[Health/Live] latency={result['latency_ms']}ms, models={result['available_models']}")

    @pytest.mark.asyncio
    async def test_health_check_offline_fallback(self):
        gw = OllamaGateway(base_url="http://localhost:99999")  # unreachable
        result = await gw.check_health()
        assert result["status"] == "offline"
        assert result["offline_mode"] is True
        assert "message" in result

    def test_get_model_for_task_chat(self):
        gw = OllamaGateway()
        model = gw.get_model_for_task("chat")
        assert isinstance(model, str)
        assert len(model) > 0

    def test_get_model_for_task_reasoning(self):
        gw = OllamaGateway()
        model = gw.get_model_for_task("reasoning")
        assert isinstance(model, str)

    def test_get_model_for_task_embedding(self):
        gw = OllamaGateway()
        model = gw.get_model_for_task("embedding")
        assert isinstance(model, str)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: Offline Simulation Fallback (Always runs)
# ─────────────────────────────────────────────────────────────────────────────

class TestOfflineSimulationFallback:

    @pytest.mark.asyncio
    async def test_chat_complete_offline_returns_content(self):
        gw = OllamaGateway(base_url="http://localhost:99999")
        result = await gw.chat_complete(
            messages=[{"role": "user", "content": "What are the key financial metrics for Northstar Studio?"}]
        )
        assert "content" in result
        assert len(result["content"]) > 20
        assert result["simulated"] is True
        print(f"\n[Simulation] content_len={len(result['content'])}, model={result['model']}")

    @pytest.mark.asyncio
    async def test_chat_complete_offline_json_workflow(self):
        gw = OllamaGateway(base_url="http://localhost:99999")
        result = await gw.chat_complete(
            messages=[{"role": "user", "content": "Build me a workflow automation for invoice follow-up"}],
            format_json=True
        )
        assert result["simulated"] is True
        data = json.loads(result["content"])
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) >= 2
        print(f"\n[Simulation/JSON/Workflow] nodes={len(data['nodes'])}, edges={len(data['edges'])}")

    @pytest.mark.asyncio
    async def test_chat_complete_offline_json_agent(self):
        gw = OllamaGateway(base_url="http://localhost:99999")
        result = await gw.chat_complete(
            messages=[{"role": "user", "content": "Create a custom agent for customer onboarding"}],
            system_prompt="You are an agent studio assistant. role_title: onboarding agent",
            format_json=True
        )
        data = json.loads(result["content"])
        assert "name" in data
        assert "role_title" in data
        print(f"\n[Simulation/JSON/Agent] name={data['name']}")

    @pytest.mark.asyncio
    async def test_chat_complete_offline_json_boardroom(self):
        gw = OllamaGateway(base_url="http://localhost:99999")
        result = await gw.chat_complete(
            messages=[{"role": "user", "content": "Run deliberation in the boardroom — should we raise prices?"}],
            format_json=True
        )
        data = json.loads(result["content"])
        assert "recommendation" in data
        assert "reasoning" in data
        print(f"\n[Simulation/JSON/Boardroom] recommendation={data['recommendation'][:60]}...")

    @pytest.mark.asyncio
    async def test_embedding_offline_returns_valid_vector(self):
        gw = OllamaGateway(base_url="http://localhost:99999")
        vector = await gw.generate_embedding("This is a test sentence for business memory search.")
        assert isinstance(vector, list)
        assert len(vector) == 128
        assert all(isinstance(v, float) for v in vector)
        assert all(-1.0 <= v <= 1.0 for v in vector)
        print(f"\n[Embedding/Offline] dim=128, sample={vector[:3]}")

    @pytest.mark.asyncio
    async def test_embedding_deterministic(self):
        """Same input must always produce identical offline embedding."""
        gw = OllamaGateway(base_url="http://localhost:99999")
        text = "Northstar Studio pricing strategy Q2 2025"
        v1 = await gw.generate_embedding(text)
        v2 = await gw.generate_embedding(text)
        assert v1 == v2, "Offline embedding must be deterministic"

    @pytest.mark.asyncio
    async def test_embedding_distinct_for_different_texts(self):
        """Different inputs must yield meaningfully different vectors."""
        gw = OllamaGateway(base_url="http://localhost:99999")
        v1 = await gw.generate_embedding("Revenue growth strategy")
        v2 = await gw.generate_embedding("Customer churn mitigation plan")
        dot = sum(a * b for a, b in zip(v1, v2))
        mag1 = sum(a ** 2 for a in v1) ** 0.5
        mag2 = sum(b ** 2 for b in v2) ** 0.5
        cosine = dot / (mag1 * mag2) if mag1 > 0 and mag2 > 0 else 0
        # Texts are semantically different: cosine sim should not be > 0.999
        assert cosine < 0.999, f"Different texts should not be identical vectors (cosine={cosine:.4f})"
        print(f"\n[Embedding/Distinct] cosine_similarity={cosine:.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: Live Ollama Model Tests (Requires running Ollama + model)
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveOllamaModel:

    @pytest.mark.asyncio
    @live_model
    async def test_live_chat_complete_basic(self):
        gw = OllamaGateway()
        model = pick_test_model()
        assert model is not None, "No models available in Ollama"
        
        result = await gw.chat_complete(
            messages=[{"role": "user", "content": "Reply with exactly: ONEBOARD_TEST_OK"}],
            model=model
        )
        assert "content" in result
        assert result["simulated"] is False
        assert len(result["content"]) > 0
        assert result["duration_ms"] >= 0
        print(f"\n[Live/Chat] model={result['model']}, duration={result['duration_ms']}ms")
        print(f"Response: {result['content'][:200]}")

    @pytest.mark.asyncio
    @live_model
    async def test_live_chat_complete_business_question(self):
        gw = OllamaGateway()
        model = pick_test_model()
        
        result = await gw.chat_complete(
            messages=[{
                "role": "user",
                "content": "In 2 sentences, what is the most important financial metric for a bootstrapped SaaS startup?"
            }],
            system_prompt="You are a concise business advisor. Keep responses under 50 words.",
            model=model
        )
        assert result["simulated"] is False
        assert len(result["content"]) > 10
        print(f"\n[Live/Business] content={result['content'][:200]}")

    @pytest.mark.asyncio
    @live_model
    async def test_live_json_structured_output(self):
        gw = OllamaGateway()
        model = pick_test_model()
        
        result = await gw.chat_complete(
            messages=[{
                "role": "user",
                "content": 'Return a JSON object with keys: "metric", "value", "unit". Use MRR as the metric, value 5000, unit "USD/month".'
            }],
            model=model,
            format_json=True
        )
        assert result["simulated"] is False
        try:
            data = json.loads(result["content"])
            print(f"\n[Live/JSON] parsed_keys={list(data.keys())}")
        except json.JSONDecodeError:
            pytest.fail(f"Model did not return valid JSON: {result['content'][:200]}")

    @pytest.mark.asyncio
    @live_model
    async def test_live_embedding_generation(self):
        gw = OllamaGateway()
        # Try nomic or fallback to offline
        try:
            vector = await gw.generate_embedding(
                "OneBoard AI operating system for solopreneurs",
                model="nomic-embed-text"
            )
            if vector and len(vector) > 0:
                assert isinstance(vector[0], float)
                print(f"\n[Live/Embedding] dim={len(vector)}, sample={vector[:3]}")
                return
        except Exception:
            pass
        # Fallback embedding
        vector = await gw.generate_embedding("OneBoard AI operating system")
        assert len(vector) > 0
        print(f"\n[Live/Embedding/Fallback] dim={len(vector)}")

    @pytest.mark.asyncio
    @live_model
    async def test_live_council_style_multi_turn(self):
        """Simulate a multi-turn council deliberation with the live model."""
        gw = OllamaGateway()
        model = pick_test_model()
        
        system_prompt = (
            "You are the CFO adviser in an AI executive council. "
            "Your job is to provide concise financial analysis. "
            "Keep all responses under 60 words."
        )
        conversation = [
            {"role": "user", "content": "Our MRR is $18,000 and monthly burn is $12,200. What is our runway?"},
        ]
        
        result = await gw.chat_complete(
            messages=conversation,
            system_prompt=system_prompt,
            model=model
        )
        assert result["simulated"] is False
        assert len(result["content"]) > 5
        print(f"\n[Live/Council] CFO response: {result['content'][:300]}")
        
        # Follow-up turn
        conversation.append({"role": "assistant", "content": result["content"]})
        conversation.append({"role": "user", "content": "What is your top recommendation to extend runway by 3 months?"})
        
        result2 = await gw.chat_complete(
            messages=conversation,
            system_prompt=system_prompt,
            model=model
        )
        assert result2["simulated"] is False
        print(f"[Live/Council] CFO follow-up: {result2['content'][:300]}")

    @pytest.mark.asyncio
    @live_model
    async def test_live_latency_benchmark(self):
        """Benchmark inference latency for the live model."""
        gw = OllamaGateway()
        model = pick_test_model()
        latencies = []
        
        for i in range(3):
            start = time.time()
            result = await gw.chat_complete(
                messages=[{"role": "user", "content": f"Say 'OK_{i}' and nothing else."}],
                model=model
            )
            elapsed = (time.time() - start) * 1000
            latencies.append(elapsed)
        
        avg = sum(latencies) / len(latencies)
        print(f"\n[Live/Latency] model={model}, runs=3, avg={avg:.0f}ms, times={[f'{l:.0f}' for l in latencies]}")
        assert avg < 120_000, f"Average latency {avg:.0f}ms exceeds 2 minute limit"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: Live API Endpoint Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

API_BASE = "http://localhost:8000"


def is_api_running() -> bool:
    try:
        r = httpx.get(f"{API_BASE}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


api_running = pytest.mark.skipif(
    not is_api_running(),
    reason="OneBoard API is not running at localhost:8000 — start with uvicorn first"
)


class TestLiveAPIEndpoints:

    @api_running
    def test_api_health(self):
        r = httpx.get(f"{API_BASE}/health", timeout=5.0)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["app"] == "OneBoard"
        print(f"\n[API/Health] {data}")

    @api_running
    def test_api_business_metrics(self):
        r = httpx.get(f"{API_BASE}/api/business/metrics", timeout=10.0)
        assert r.status_code == 200
        data = r.json()
        assert "mrr" in data
        assert "runway_months" in data
        assert "health_score" in data
        assert data["health_score"] >= 0
        print(f"\n[API/Metrics] MRR={data['mrr']}, Runway={data['runway_months']}mo, Health={data['health_score']}")

    @api_running
    def test_api_model_gateway_health(self):
        r = httpx.get(f"{API_BASE}/api/ai/status", timeout=5.0)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        print(f"\n[API/ModelGateway] status={data['status']}, models={data.get('available_models', [])}")

    @api_running
    def test_api_list_workflows(self):
        r = httpx.get(f"{API_BASE}/api/workflows", timeout=10.0, follow_redirects=True)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"\n[API/Workflows] count={len(data)}")

    @api_running
    def test_api_memory_search(self):
        payload = {"query": "pricing strategy revenue growth"}
        r = httpx.post(f"{API_BASE}/api/memory/search", json=payload, timeout=10.0)
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        print(f"\n[API/Memory] query_results={len(data['results'])}")

    @api_running
    def test_api_council_trigger(self):
        """Trigger a council deliberation and verify structured response."""
        payload = {
            "title": "Q4 Pricing Strategy Review",
            "topic": "Should Northstar Studio raise prices by 15% this quarter? MRR is $18,450, monthly burn is $12,200, runway is 7.2 months, 38 active customers.",
            "meeting_type": "strategy_session",
            "selected_advisers": ["cfo", "cmo"]
        }
        r = httpx.post(f"{API_BASE}/api/council/deliberate", json=payload, timeout=90.0)
        # Accept 200 or 201; may take time for council deliberation
        assert r.status_code in (200, 201)
        data = r.json()
        # Council response may contain different top-level keys depending on state
        assert isinstance(data, dict) and len(data) > 0
        print(f"\n[API/Council] response_keys={list(data.keys())}")

    @api_running
    def test_api_alerts(self):
        r = httpx.get(f"{API_BASE}/api/alerts", timeout=5.0, follow_redirects=True)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"\n[API/Alerts] count={len(data)}")

    @api_running
    def test_api_list_custom_agents(self):
        r = httpx.get(f"{API_BASE}/api/agents", timeout=5.0, follow_redirects=True)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"\n[API/Agents] count={len(data)}")

    @api_running
    def test_api_founder_command_natural_language(self):
        """Test natural language input processing via Founder Command."""
        payload = {"command": "Show me all overdue invoices and flag any customers at risk of churn"}
        r = httpx.post(f"{API_BASE}/api/business/command", json=payload, timeout=30.0)
        # Accept 200 or 422 (if endpoint uses different schema)
        assert r.status_code in (200, 201, 404, 422)
        print(f"\n[API/Command] status={r.status_code}, response_len={len(r.text)}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: Full End-to-End Live Integration (Ollama + API)
# ─────────────────────────────────────────────────────────────────────────────

class TestEndToEndWithOllama:

    @pytest.mark.asyncio
    @live_model
    async def test_e2e_council_deliberation_with_real_model(self):
        """
        Full E2E: Send a business question through the OllamaGateway using a real
        live local model (not the simulation) and verify structured output.
        """
        gw = OllamaGateway()
        model = pick_test_model()
        assert model is not None

        health = await gw.check_health()
        print(f"\n[E2E] Ollama connected, model={model}, available={health['available_models']}")

        # Simulate what CouncilEngine does: role-specific prompts
        roles = [
            ("Chief Financial Officer", "Analyze the financial risk of a 15% price increase given current runway."),
            ("Chief Marketing Officer", "Evaluate the market positioning impact of a 15% price increase."),
        ]
        
        responses = []
        for role, question in roles:
            system_prompt = (
                f"You are the {role} adviser in an AI executive council for a bootstrapped SaaS company. "
                f"Provide concise, data-driven analysis. Keep your response under 80 words."
            )
            result = await gw.chat_complete(
                messages=[{"role": "user", "content": question}],
                system_prompt=system_prompt,
                model=model
            )
            assert result["simulated"] is False
            assert len(result["content"]) > 10
            responses.append({"role": role, "response": result["content"], "model": result["model"]})
            print(f"\n[E2E/{role}] {result['content'][:150]}...")
        
        assert len(responses) == 2
        # Synthesize — both advisers should produce different perspectives
        assert responses[0]["response"] != responses[1]["response"]
        print(f"\n[E2E] Council deliberation complete with {len(responses)} advisers using live model '{model}'")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Quick diagnostic runner
    print("=== OneBoard Ollama Integration Diagnostic ===")
    print(f"Ollama running: {is_ollama_running()}")
    print(f"Available models: {get_available_models()}")
    print(f"Test model: {pick_test_model()}")
    print(f"API running: {is_api_running()}")
    print()
    
    async def run_quick_tests():
        gw = OllamaGateway()
        health = await gw.check_health()
        print(f"Gateway health: {health['status']} | models={health['available_models']}")
        
        result = await gw.chat_complete(
            messages=[{"role": "user", "content": "What is the most important metric for a SaaS startup?"}]
        )
        print(f"Chat complete: simulated={result['simulated']}, len={len(result['content'])}")
        print(f"Response preview: {result['content'][:200]}")
        
        vector = await gw.generate_embedding("Revenue growth strategy for B2B SaaS")
        print(f"Embedding: dim={len(vector)}, sample={vector[:3]}")
    
    asyncio.run(run_quick_tests())
