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
    required = os.getenv("ONEBOARD_CI_OLLAMA_MODEL")
    if required:
        assert required in available, "Required local chat model is not installed"
        return required
    for preferred in PREFERRED_TEST_MODELS:
        for avail in available:
            if preferred in avail or avail.startswith(preferred.split(":")[0]):
                return avail
    return available[0] if available else None


# ─── Markers ──────────────────────────────────────────────────────────────────
live_model = pytest.mark.skipif(
    os.getenv("ONEBOARD_LIVE_OLLAMA_TESTS") != "1",
    reason="Dedicated live Ollama job executes this suite",
)

@pytest.fixture(scope="module", autouse=True)
def required_live_model_readiness():
    if os.getenv("ONEBOARD_LIVE_OLLAMA_TESTS") == "1":
        from urllib.parse import urlsplit
        assert urlsplit(OLLAMA_BASE_URL).hostname in ("127.0.0.1","localhost","::1"), "Live tests must use local Ollama"
        assert is_ollama_running(), "Required Ollama is unavailable"
        assert pick_test_model(), "No required model installed"
        assert os.getenv("ONEBOARD_CI_EMBEDDING_MODEL", "all-minilm:latest") in get_available_models() or os.getenv("ONEBOARD_CI_EMBEDDING_MODEL","all-minilm") + ":latest" in get_available_models(), "Required embedding model not installed"


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
        gw = OllamaGateway(base_url="http://127.0.0.1:1")  # unreachable
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
        gw = OllamaGateway(base_url="http://127.0.0.1:1")
        result = await gw.chat_complete(
            messages=[{"role": "user", "content": "What are the key financial metrics for Northstar Studio?"}]
        )
        assert "content" in result
        assert len(result["content"]) > 20
        assert result["simulated"] is True
        print(f"\n[Simulation] content_len={len(result['content'])}, model={result['model']}")

    @pytest.mark.asyncio
    async def test_chat_complete_offline_json_workflow(self):
        gw = OllamaGateway(base_url="http://127.0.0.1:1")
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
        gw = OllamaGateway(base_url="http://127.0.0.1:1")
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
        gw = OllamaGateway(base_url="http://127.0.0.1:1")
        result = await gw.chat_complete(
            messages=[{"role": "user", "content": "Run deliberation in the boardroom — should we raise prices?"}],
            format_json=True
        )
        assert result["simulated"] is True
        data = json.loads(result["content"])
        assert data["simulated"] is True
        assert data["status"] == "unavailable"
        assert data["recommendation"] is None
        assert "reasoning" in data
        assert not data.get("findings"), "Offline boardroom must not invent findings"
        print("\n[Simulation/JSON/Boardroom] unavailable; no fabricated recommendation")

    @pytest.mark.asyncio
    async def test_embedding_offline_returns_valid_vector(self):
        gw = OllamaGateway(base_url="http://127.0.0.1:1")
        vector = await gw.generate_embedding("This is a test sentence for business memory search.")
        assert isinstance(vector, list)
        assert len(vector) == 128
        assert all(isinstance(v, float) for v in vector)
        assert all(-1.0 <= v <= 1.0 for v in vector)
        print(f"\n[Embedding/Offline] dim=128, sample={vector[:3]}")

    @pytest.mark.asyncio
    async def test_embedding_deterministic(self):
        """Same input must always produce identical offline embedding."""
        gw = OllamaGateway(base_url="http://127.0.0.1:1")
        text = "Northstar Studio pricing strategy Q2 2025"
        v1 = await gw.generate_embedding(text)
        v2 = await gw.generate_embedding(text)
        assert v1 == v2, "Offline embedding must be deterministic"

    @pytest.mark.asyncio
    async def test_embedding_distinct_for_different_texts(self):
        """Different inputs must yield meaningfully different vectors."""
        gw = OllamaGateway(base_url="http://127.0.0.1:1")
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
        model = os.getenv("ONEBOARD_CI_EMBEDDING_MODEL", "all-minilm")
        vector = await gw.genuine_embedding("OneBoard AI operating system for solopreneurs", model=model)
        assert vector and len(vector) > 128
        assert all(isinstance(v,float) for v in vector)
        assert await gw.genuine_embedding("synthetic", model="oneboard-ci-missing:never") is None

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
            assert result['simulated'] is False, result.get('fallback_reason')
            elapsed = (time.time() - start) * 1000
            latencies.append(elapsed)
        
        avg = sum(latencies) / len(latencies)
        print(f"\n[Live/Latency] model={model}, runs=3, avg={avg:.0f}ms, times={[f'{l:.0f}' for l in latencies]}")
        assert avg < 120_000, f"Average latency {avg:.0f}ms exceeds 2 minute limit"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: Live API Endpoint Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

API_BASE = os.getenv("ONEBOARD_LIVE_API_URL", "http://127.0.0.1:8000")

def is_api_running() -> bool:
    try:
        return httpx.get(f"{API_BASE}/health", timeout=2.0).status_code == 200
    except Exception:
        return False

api_running = pytest.mark.skipif(
    os.getenv("ONEBOARD_LIVE_API_TESTS") != "1",
    reason="Dedicated authenticated live API job executes this suite",
)

@pytest.fixture(scope="class")
def live_workspaces():
    from uuid import uuid4
    from urllib.parse import urlsplit
    assert urlsplit(API_BASE).hostname in ("127.0.0.1","localhost","::1")
    assert os.getenv("ONEBOARD_LIVE_API_DISPOSABLE") == "1", "Refuse to mutate non-disposable server"
    assert is_api_running(), "Required fresh API unavailable"
    def register():
        client = httpx.Client(base_url=API_BASE,timeout=30,follow_redirects=True,trust_env=False)
        email = uuid4().hex+"@example.test"
        password = "Synthetic-CI-Password123!"
        response = client.post("/api/auth/register",json={"name":"Synthetic CI Founder","email":email,"password":password,"business_name":"Disposable CI Workspace"})
        assert response.status_code==201
        data=response.json()
        client.headers.update({"X-CSRF-Token":data["csrf_token"],"Origin":API_BASE})
        # Exercise real cookie login, not a fabricated session or demo bypass.
        client.cookies.clear()
        login=client.post("/api/auth/login",json={"email":email,"password":password})
        assert login.status_code==200
        client.headers["X-CSRF-Token"]=login.json()["csrf_token"]
        return client,data["business"]["id"]
    a,aid=register()
    b,bid=register()
    try:
        yield a,aid,b,bid
    finally:
        a.close()
        b.close()

@api_running
class TestLiveAPIEndpoints:
    def test_api_health(self,live_workspaces):
        a,_,_,_=live_workspaces
        r=a.get("/health")
        assert r.status_code==200
        assert r.json()["status"]=="healthy" and r.json()["service"]=="OneBoard API"

    def test_api_business_metrics(self,live_workspaces):
        a,aid,_,_=live_workspaces
        r=a.get("/api/business/metrics")
        assert r.status_code==200
        data=r.json()
        assert data["tenant_id"]==aid
        assert data["mrr"]==0 and data["health_score"] is None
        assert data["financial_data_status"]=="unconfigured"
        assert data["financial_data_verified"] is False

    def test_api_model_gateway_health(self,live_workspaces):
        a,_,_,_=live_workspaces
        r=a.get("/api/ai/status")
        assert r.status_code==200
        data=r.json()
        assert data["status"]=="connected"
        assert data["inference_available"] is True
        assert data["requested_model"]==os.environ["ONEBOARD_CI_OLLAMA_MODEL"]

    def test_api_list_workflows(self,live_workspaces):
        a,aid,b,_=live_workspaces
        created=a.post("/api/workflows",json={"name":"Synthetic workflow","nodes":[{"id":"start","type":"trigger","data":{}}],"edges":[]})
        assert created.status_code==200
        wid=created.json()["id"]
        rows=a.get("/api/workflows")
        assert rows.status_code==200
        assert any(row["id"]==wid and row["business_id"]==aid for row in rows.json())
        other=b.get("/api/workflows")
        assert other.status_code==200 and all(row["id"]!=wid for row in other.json())

    def test_api_memory_search(self,live_workspaces):
        a,_,b,_=live_workspaces
        marker="synthetic pricing strategy revenue growth"
        upload=a.post("/api/memory/upload",files={"file":("synthetic.txt",marker.encode(),"text/plain")})
        assert upload.status_code==200
        doc=upload.json()["document_id"]
        indexed=a.post("/api/memory/index",timeout=60)
        assert indexed.status_code==200 and indexed.json()["indexed"]>=1
        r=a.post("/api/memory/search",json={"query":marker})
        assert r.status_code==200 and any(row["document_id"]==doc for row in r.json()["results"])
        r=b.post("/api/memory/search",json={"query":marker})
        assert r.status_code==200 and r.json()["results"]==[]

    def test_api_council_trigger(self,live_workspaces):
        a,aid,b,_=live_workspaces
        roles=["Finance Adviser","Marketing Adviser"]
        r=a.post("/api/council/deliberate",json={"title":"Synthetic pricing review","topic":"What evidence should a new business collect before changing prices?","meeting_type":"custom","selected_advisers":roles},timeout=240)
        assert r.status_code==200
        data=r.json()
        assert data["business_id"]==aid and data["stage"]=="completed"
        transcript=data["deliberation_transcript"]
        assert len(transcript)==3 and all(row["simulated"] is False for row in transcript)
        assert data["synthesis_summary"].startswith("AI-generated synthesis")
        other=b.get("/api/council/meetings")
        assert other.status_code==200 and all(row["id"]!=data["id"] for row in other.json())

    def test_api_alerts(self,live_workspaces):
        a,_,_,_=live_workspaces
        r=a.get("/api/alerts")
        assert r.status_code==200 and isinstance(r.json(),list)

    def test_api_list_custom_agents(self,live_workspaces):
        a,_,b,_=live_workspaces
        r=a.post("/api/agents",json={"name":"Synthetic analyst","role_title":"Analyst","system_prompt":"Use only supplied facts."})
        assert r.status_code==200
        agent=r.json()["id"]
        own=a.get("/api/agents")
        other=b.get("/api/agents")
        assert own.status_code==other.status_code==200
        assert any(row["id"]==agent for row in own.json())
        assert all(row["id"]!=agent for row in other.json())

    def test_api_founder_command_natural_language(self,live_workspaces):
        a,_,_,_=live_workspaces
        r=a.post("/api/ai/command",json={"command":"What should I record before making financial forecasts?"},timeout=90)
        assert r.status_code==200
        data=r.json()
        assert data["simulated"] is False and data["inference_engine"]=="local_ollama"
        assert data["response"].strip()
        assert data["business_state_summary"]["financial_data_verified"] is False

    def test_api_unauthenticated_and_csrf_are_denied(self,live_workspaces):
        a,_,_,_=live_workspaces
        with httpx.Client(base_url=API_BASE,trust_env=False) as anon:
            for route in ("/api/business/metrics","/api/agents","/api/workflows","/api/data/export"):
                assert anon.get(route).status_code==401
        csrf=a.headers.pop("X-CSRF-Token")
        try:
            r=a.post("/api/workflows",json={"name":"Denied","nodes":[{"id":"x","type":"trigger"}],"edges":[]})
            assert r.status_code==403
        finally:
            a.headers["X-CSRF-Token"]=csrf

    def test_api_cross_tenant_workflow_execution_denied(self,live_workspaces):
        a,_,b,_=live_workspaces
        r=a.post("/api/workflows",json={"name":"Private workflow","nodes":[{"id":"start","type":"trigger","data":{}}],"edges":[]})
        assert r.status_code==200
        denied=b.post("/api/workflows/"+r.json()["id"]+"/execute",headers={"Idempotency-Key":"cross-tenant-ci"})
        assert denied.status_code in (403,404)

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
