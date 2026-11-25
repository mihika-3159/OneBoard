from contextlib import nullcontext
import httpx
import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional, AsyncGenerator
from apps.api.core.config import settings
from apps.api.services.cluster_capacity import inference_slot
from apps.api.services.model_identity import matches_pin
from apps.api.services.inference_budget import TokenBudgetExceeded, charge_provider_attempt, current_inference_tenant
from apps.api.services.embedding_cache import EmbeddingCache
from apps.api.services.inference_resources import has_headroom
from apps.api.services.inference_routing import route
from apps.api.services.inference_stream import on_text
from apps.api.services.inference_adapters import (OllamaAdapter, CompatibleAdapter, ProviderUnavailable, ProviderIdentityUnavailable,
    is_remote, verify_remote_capacity)
from apps.api.services.generation_cache import GenerationCache

from apps.api.services.inference_controls import CircuitOpen, ProviderCircuit, fit_prompt, retry_provider

logger = logging.getLogger(__name__)

class _CapacityExceeded(Exception):
    pass


class _ModelIdentityMismatch(ProviderIdentityUnavailable):
    pass


class OllamaGateway:
    def __init__(self, base_url: str = settings.OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.active_profile = settings.DEFAULT_MODEL_PROFILE
        # An unbounded burst of founder requests can saturate a free CPU
        # Ollama server and starve unrelated tenants. Fail busy requests
        # explicitly rather than consuming unbounded worker resources.
        self._inference_slots = asyncio.Semaphore(2)
        self._queue_timeout_seconds = 3.0
        self._circuit = ProviderCircuit()
        self._circuits = {self.base_url: self._circuit}
        if settings.OLLAMA_LOCAL_REPLICA_PORT:
            replica = f"http://127.0.0.1:{settings.OLLAMA_LOCAL_REPLICA_PORT}"
            self._circuits.setdefault(replica, ProviderCircuit())
        self._adapters = {origin: OllamaAdapter() for origin in self._circuits}
        if settings.INFERENCE_COMPATIBLE_LOCAL_PORT:
            origin = f"http://127.0.0.1:{settings.INFERENCE_COMPATIBLE_LOCAL_PORT}"
            if origin in self._adapters:
                raise ValueError("Compatible provider needs a distinct port")
            self._circuits[origin] = ProviderCircuit()
            self._adapters[origin] = CompatibleAdapter(settings.INFERENCE_COMPATIBLE_DIGESTS)
        self._embedding_cache = EmbeddingCache()
        self._generation_cache = GenerationCache()
        
    def _queued(self):
        return bool(settings.INFERENCE_QUEUE_URL and current_inference_tenant())

    async def _post_inference(self, path, payload, timeout):
        if self._queued():
            from apps.api.services.inference_queue import dispatch, queue_engine
            return await dispatch(
                queue_engine(settings.INFERENCE_QUEUE_URL), current_inference_tenant(), path, payload, timeout
            )
        return await self._call_providers(path, payload, timeout)

    async def _call_providers(self, path, payload, timeout):
        if settings.ONEBOARD_PRODUCTION_MODE and not has_headroom(
            settings.INFERENCE_MIN_FREE_MIB * 1024 * 1024, settings.INFERENCE_MAX_LOAD_PER_CPU
        ):
            raise _CapacityExceeded()
        published = False
        emit = on_text.get()
        async def guarded_emit(fragment):
            nonlocal published
            published = True
            await emit(fragment)
        async def operation(origin):
            return await self._post_to_origin(origin, path, payload, timeout)

        origins = tuple(origin for origin, adapter in self._adapters.items()
                        if path == "/api/chat" or isinstance(adapter, OllamaAdapter))
        token = on_text.set(guarded_emit if emit is not None else None)
        try:
            return await route(operation, origins, timeout, can_failover=lambda: not published)
        finally:
            on_text.reset(token)

    async def _post_to_origin(self, origin, path, payload, timeout):
        from apps.api.services.operational_health import propagate
        with self._circuits[origin].attempt() as record_failure:
            async with httpx.AsyncClient(timeout=timeout,event_hooks={"request":[propagate]}) as client:
                adapter = self._adapters[origin]
                if settings.ONEBOARD_PRODUCTION_MODE and is_remote(origin):
                    await verify_remote_capacity(client, origin, settings.INFERENCE_MIN_FREE_MIB * 1024 * 1024,
                        settings.INFERENCE_MAX_LOAD_PER_CPU, settings.INFERENCE_REMOTE_ACCELERATOR_MIN_MIB * 1024 * 1024)
                if settings.OLLAMA_MODEL_DIGESTS and isinstance(adapter, OllamaAdapter):
                    await asyncio.wait_for(self._verify_model(client, origin, payload["model"]), timeout=3.0)

                published = False
                emit = on_text.get()
                async def guarded_emit(fragment):
                    nonlocal published
                    published = True
                    await emit(fragment)
                async def send():
                    await charge_provider_attempt(payload)
                    try:
                        return await adapter.send(client, origin, path, payload, guarded_emit if emit is not None else None)
                    except httpx.TransportError as exc:
                        if published:
                            raise ValueError("Interrupted provider response") from exc
                        raise

                try:
                    response = await asyncio.wait_for(
                        retry_provider(
                            send,
                            lambda reply: not published and reply.status_code in (502, 503, 504),
                            (httpx.ConnectError, httpx.ConnectTimeout),
                        ),
                        timeout=timeout,
                    )
                except (httpx.TransportError, asyncio.TimeoutError):
                    record_failure(True)
                    raise
                record_failure(response.status_code >= 500)
                if response.status_code == 200:
                    try:
                        body = response.json()
                        if isinstance(body, dict):
                            body["provider_protocol"] = "remote_ollama" if is_remote(origin) else adapter.protocol
                            return httpx.Response(200, json=body)
                    except (ValueError, TypeError):
                        pass
                return response

    async def _verify_model(self, client, origin, model):
        expected = settings.OLLAMA_MODEL_DIGESTS.get(model)
        if expected is None:
            raise _ModelIdentityMismatch()
        try:
            response = await client.get(f"{origin}/api/tags", timeout=2.0)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and matches_pin(data.get("models"), model, expected):
                    return
        except (ValueError, httpx.TransportError):
            pass
        raise _ModelIdentityMismatch()

    async def check_health(self) -> Dict[str, Any]:
        """Check if local Ollama daemon is reachable and list downloaded models."""
        start = time.time()
        if len(self._adapters) > 1 or (settings.ONEBOARD_PRODUCTION_MODE and is_remote(self.base_url)):
            return await self._configured_health(start)
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                latency_ms = int((time.time() - start) * 1000)
                if res.status_code == 200:
                    payload = res.json()
                    models = payload.get("models", []) if isinstance(payload, dict) else []
                    models = models if isinstance(models, list) else []
                    available = [m.get("name") for m in models if isinstance(m, dict) and isinstance(m.get("name"), str) and m.get("name")]
                    if settings.OLLAMA_MODEL_DIGESTS:
                        available = [
                            name for name in available
                            if matches_pin(models, name, settings.OLLAMA_MODEL_DIGESTS.get(name))
                        ]
                    return {
                        "status": "connected",
                        "base_url": self.base_url,
                        "latency_ms": latency_ms,
                        "available_models": available,
                        "inference_available": bool(available),
                        "offline_mode": False,
                        "message": None if available else "Ollama is reachable but no models are installed. Inference will use a clearly labeled fallback.",
                        "active_profile": self.active_profile,
                        "profile_details": settings.MODEL_PROFILES.get(self.active_profile, {})
                    }
        except Exception as e:
            logger.info("Ollama health unavailable (%s)", type(e).__name__)
            
        return {
            "status": "offline",
            "base_url": self.base_url,
            "latency_ms": 0,
            "available_models": [],
            "inference_available": False,
            "active_profile": self.active_profile,
            "profile_details": settings.MODEL_PROFILES.get(self.active_profile, {}),
            "offline_mode": True,
            "message": "Ollama is offline or not installed. Only a clearly labeled deterministic fallback is available; no model has generated an answer."
        }

    async def _configured_health(self, start):
        """Report only reachable, admitted and verified configured model providers."""
        async def probe(origin, adapter):
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    if settings.ONEBOARD_PRODUCTION_MODE and is_remote(origin):
                        await verify_remote_capacity(client, origin, settings.INFERENCE_MIN_FREE_MIB * 1024 * 1024,
                            settings.INFERENCE_MAX_LOAD_PER_CPU, settings.INFERENCE_REMOTE_ACCELERATOR_MIN_MIB * 1024 * 1024)
                    compatible = isinstance(adapter, CompatibleAdapter)
                    response = await client.get(origin + ("/oneboard/models" if compatible else "/api/tags"))
                    response.raise_for_status()
                    models = response.json().get("models", [])
                    pins = adapter.pins if compatible else settings.OLLAMA_MODEL_DIGESTS
                    available = {m.get("name") for m in models if isinstance(m, dict)
                                 and isinstance(m.get("name"), str) and m.get("name")
                                 and (not pins or matches_pin(models, m["name"], pins.get(m["name"])))}
                    if compatible:
                        catalog = await client.get(origin + "/v1/models")
                        catalog.raise_for_status()
                        available &= {m.get("id") for m in catalog.json().get("data", []) if isinstance(m, dict)}
                    return {"protocol": "remote_ollama" if is_remote(origin) else adapter.protocol,
                            "status": "connected", "models": sorted(available)}
            except Exception:
                return {"protocol": "remote_ollama" if is_remote(origin) else adapter.protocol,
                        "status": "unavailable", "models": []}
        providers = await asyncio.gather(*(probe(origin, adapter) for origin, adapter in self._adapters.items()))
        available = sorted({model for provider in providers for model in provider["models"]})
        connected = any(provider["status"] == "connected" for provider in providers)
        return {"status": "connected" if connected else "offline", "base_url": self.base_url,
                "latency_ms": int((time.time() - start) * 1000), "available_models": available,
                "inference_available": bool(available), "offline_mode": not connected,
                "message": None if available else "No admitted, verified model is available.",
                "active_profile": self.active_profile, "profile_details": settings.MODEL_PROFILES.get(self.active_profile, {}),
                "providers": providers}

    def get_model_for_task(self, task_type: str = "chat", profile: Optional[str] = None) -> str:
        # Request-scoped profiles prevent one tenant from changing another's model.
        selected = profile or settings.DEFAULT_MODEL_PROFILE
        profile_config = settings.MODEL_PROFILES.get(selected, settings.MODEL_PROFILES["balanced"])
        if task_type == "reasoning":
            return profile_config.get("reasoning_model", "llama3.1:8b")
        elif task_type == "embedding":
            return profile_config.get("embedding_model", "nomic-embed-text")
        return profile_config.get("chat_model", "qwen2.5:7b")

    async def chat_complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        task_type: str = "chat",
        format_json: bool = False,
        cache_text: bool = False
    ) -> Dict[str, Any]:
        """Run bounded local server-side inference, with explicit fallback status.

        The process permits at most two simultaneous CPU generation requests.
        Unavailable, incomplete, malformed, or overloaded Ollama responses
        must never be reported as completed real inference. No prompts or
        provider response bodies are logged.
        """
        target_model = model or self.get_model_for_task(task_type)
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": [],
            "stream": False,
            "options": {"num_predict": max(64,min(4096,settings.OLLAMA_MAX_JSON_OUTPUT_TOKENS if format_json else settings.OLLAMA_MAX_OUTPUT_TOKENS))},
        }
        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})
        payload["messages"].extend(messages)
        if format_json:
            payload["format"] = "json"

        start_time = time.monotonic()
        context_window = settings.OLLAMA_CONTEXT_WINDOW
        fitted = fit_prompt(payload["messages"], context_window - payload["options"]["num_predict"] - 64)
        payload["options"]["num_ctx"] = context_window
        cache_key = None
        if cache_text and not format_json and fitted is not None and on_text.get() is None and len(self._adapters) == 1:
            payload["options"]["temperature"] = 0
            payload["messages"] = fitted
            cache_key = self._generation_cache.key(current_inference_tenant(), self.base_url,
                settings.OLLAMA_MODEL_DIGESTS.get(target_model), payload)
            cached = self._generation_cache.get(cache_key)
            if cached is not None:
                return cached
        reason = "context_budget_exceeded"
        acquired = False
        try:
            if fitted is not None:
                payload["messages"] = fitted
                reason = "provider_unavailable"
            try:
                if fitted is not None:
                    if not self._queued():
                        await asyncio.wait_for(
                            self._inference_slots.acquire(),
                            timeout=self._queue_timeout_seconds,
                        )
                        acquired = True
            except asyncio.TimeoutError:
                reason = "capacity_exceeded"
            if acquired or (fitted is not None and self._queued()):
                try:
                    with (nullcontext(True) if self._queued() else inference_slot()) as admitted:
                        if not admitted:
                            raise _CapacityExceeded()
                        response = await self._post_inference("/api/chat", payload, 45.0)
                    if response.status_code == 200:
                        try:
                            data = response.json()
                            if not isinstance(data, dict):
                                raise ValueError("Invalid provider envelope")
                            message = data.get("message")
                            content = message.get("content") if isinstance(message, dict) else None
                            if not isinstance(content, str) or not content.strip():
                                raise ValueError("Incomplete model output")
                            if data.get("done") is not True:
                                raise ValueError("Incomplete generation")
                            if data.get("model") not in (None, target_model):
                                raise ValueError("Wrong model returned")
                            if format_json:
                                parsed = json.loads(content)
                                if not isinstance(parsed, dict):
                                    raise ValueError("Structured model output must be an object")
                        except (ValueError, TypeError, AttributeError):
                            reason = "invalid_model_response"
                        else:
                            result = {
                                "content": content,
                                "model": target_model,
                                "simulated": False,
                                "input_tokens": data.get("prompt_eval_count"),
                                "output_tokens": data.get("eval_count"),
                                "provider_load_ns": data.get("load_duration"),
                                "provider_eval_ns": data.get("eval_duration"),
                                "output_limit_reached": data.get("done_reason") == "length",
                                "duration_ms": int((time.monotonic() - start_time) * 1000),
                                "provider_protocol": data.get("provider_protocol", "local_ollama"),
                            }
                            self._generation_cache.put(cache_key, result)
                            return result
                    elif response.status_code == 404:
                        reason = "model_unavailable"
                    else:
                        reason = "provider_http_error"
                except ProviderIdentityUnavailable:
                    reason = "model_identity_unverified"
                except (_CapacityExceeded, ProviderUnavailable):
                    reason = "capacity_exceeded"
                except TokenBudgetExceeded:
                    reason = "token_budget_exhausted"
                except CircuitOpen:
                    reason = "provider_circuit_open"
                except (httpx.TimeoutException, asyncio.TimeoutError):
                    reason = "timeout"
                except Exception:
                    # asyncio.CancelledError inherits BaseException and must
                    # propagate; no untrusted error body or prompt is logged.
                    reason = "provider_unavailable"
        finally:
            if acquired:
                self._inference_slots.release()

        logger.warning(
            "Ollama inference unavailable (reason=%s); returning labeled fallback.",
            reason,
        )
        content = self._generate_simulated_response(messages, system_prompt, format_json)
        return {
            "content": content,
            "model": f"{target_model} (local simulated fallback)",
            "simulated": True,
            "fallback_reason": reason,
            "duration_ms": max(int((time.monotonic() - start_time) * 1000), 0),
        }

    async def genuine_embedding(self, text: str, model: Optional[str] = None):
        """Return validated provider embeddings only; never return hash fallback."""
        import math
        target_model = model or self.get_model_for_task("embedding")
        cache_key = self._embedding_cache.key(
            current_inference_tenant(), self.base_url, target_model,
            settings.OLLAMA_MODEL_DIGESTS.get(target_model), text,
        )
        cached = self._embedding_cache.get(cache_key)
        if cached is not None:
            return cached
        acquired = False
        try:
            if not self._queued():
                await asyncio.wait_for(self._inference_slots.acquire(), timeout=self._queue_timeout_seconds)
                acquired = True
            with (nullcontext(True) if self._queued() else inference_slot()) as admitted:
                if admitted:
                    res = await self._post_inference(
                        "/api/embeddings", {"model": target_model, "prompt": text}, 10.0
                    )
                    if res.status_code == 200:
                        v = res.json().get("embedding")
                        if (isinstance(v, list) and 1 <= len(v) <= 4096
                            and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                    and math.isfinite(x) and abs(x) <= 1e6 for x in v)
                            and any(v)):
                            vector = [float(x) for x in v]
                            self._embedding_cache.put(cache_key, vector)
                            return vector
        except Exception:
            pass
        finally:
            if acquired:
                self._inference_slots.release()
        return None

    async def genuine_embeddings(self,texts,model=None):
        """Bounded native Ollama batch embedding, preserving order and cache identity."""
        import math
        if not isinstance(texts,list) or not 1<=len(texts)<=16 or any(not isinstance(t,str) or not 1<=len(t)<=2048 for t in texts):
            raise ValueError("Invalid embedding batch")
        target=model or self.get_model_for_task("embedding")
        keys=[self._embedding_cache.key(current_inference_tenant(),self.base_url,target,settings.OLLAMA_MODEL_DIGESTS.get(target),t) for t in texts]
        result=[self._embedding_cache.get(k) for k in keys]
        missing=[i for i,v in enumerate(result) if v is None]
        if not missing:return result
        acquired=False
        try:
            if not self._queued():
                await asyncio.wait_for(self._inference_slots.acquire(),timeout=self._queue_timeout_seconds)
                acquired=True
            with (nullcontext(True) if self._queued() else inference_slot()) as admitted:
                if not admitted:return result
                response=await self._post_inference("/api/embed",{"model":target,"input":[texts[i] for i in missing],"truncate":False},30.0)
                if response.status_code!=200:return result
                vectors=response.json().get("embeddings")
                if not isinstance(vectors,list) or len(vectors)!=len(missing):return result
                if not all(isinstance(v,list) and 1<=len(v)<=4096 and any(v) and all(
                    type(x) in (int,float) and math.isfinite(x) and abs(x)<=1e6 for x in v) for v in vectors):
                    return result
                if len({len(v) for v in vectors})!=1 or any(v is not None and len(v)!=len(vectors[0]) for v in result):return result
                for i,v in zip(missing,vectors):
                    result[i]=[float(x) for x in v];self._embedding_cache.put(keys[i],result[i])
        except Exception:
            pass
        finally:
            if acquired:self._inference_slots.release()
        return result

    async def generate_embedding(self, text: str, model: Optional[str] = None) -> List[float]:
        """Legacy development caller; semantic index never uses this fallback."""
        genuine = await self.genuine_embedding(text, model)
        if genuine is not None:
            return genuine
        # Deterministic pseudo-embedding for local offline vector similarity (128 dims)
        import hashlib
        vector = []
        for i in range(128):
            h = hashlib.sha256(f"{text}_{i}".encode('utf-8')).hexdigest()
            val = (int(h[:8], 16) / 0xffffffff) * 2.0 - 1.0
            vector.append(round(val, 6))
        return vector

    def _generate_simulated_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        format_json: bool
    ) -> str:
        last_user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "")
                break
                
        lower_prompt = (last_user_msg + " " + (system_prompt or "")).lower()

        if format_json:
            if "workflow" in lower_prompt or "automation" in lower_prompt:
                return json.dumps({
                    "name": "Overdue Invoices & Customer Follow-up",
                    "description": "Triggered on scheduled intervals to audit open invoices, calculate balances, and draft reminders.",
                    "trigger_type": "schedule",
                    "trigger_config": {"cron": "0 9 * * 5", "description": "Every Friday at 9:00 AM"},
                    "nodes": [
                        {"id": "trigger_1", "type": "trigger", "position": {"x": 100, "y": 150}, "data": {"label": "Friday 9 AM Trigger", "source": "Schedule"}},
                        {"id": "fetch_invoices", "type": "data_fetch", "position": {"x": 350, "y": 150}, "data": {"label": "Fetch Overdue Invoices", "connector": "demo_finance"}},
                        {"id": "calculate_totals", "type": "calculate", "position": {"x": 600, "y": 150}, "data": {"label": "Calculate Total Outstanding", "formula": "sum(amount)"}},
                        {"id": "approval_gate", "type": "approval", "position": {"x": 850, "y": 150}, "data": {"label": "Founder Approval Gate", "risk": "high"}},
                        {"id": "send_notifications", "type": "action", "position": {"x": 1100, "y": 150}, "data": {"label": "Send Personalized Reminders", "channel": "email"}}
                    ],
                    "edges": [
                        {"id": "e1", "source": "trigger_1", "target": "fetch_invoices"},
                        {"id": "e2", "source": "fetch_invoices", "target": "calculate_totals"},
                        {"id": "e3", "source": "calculate_totals", "target": "approval_gate"},
                        {"id": "e4", "source": "approval_gate", "target": "send_notifications"}
                    ],
                    "validation": {"is_valid": True, "cycles_detected": False}
                })
            elif "custom agent" in lower_prompt or "agent studio" in lower_prompt or "role_title" in lower_prompt:
                return json.dumps({
                    "name": "Customer Onboarding Specialist",
                    "role_title": "Onboarding & Activation Agent",
                    "department": "Customer Success",
                    "description": "Guides newly acquired SaaS customers through setup, detects stalling, and drafts welcome sequences.",
                    "system_prompt": "You are the Customer Onboarding Specialist for Northstar Studio. Review new signups, check onboarding checklist completion, and draft tailored assistance.",
                    "allowed_tools": ["read_customers", "check_onboarding_status", "draft_welcome_email"],
                    "requires_approval_for": ["send_welcome_email"],
                    "max_steps": 4
                })
            elif "deliberation" in lower_prompt or "boardroom" in lower_prompt:
                return json.dumps({
                    "recommendation": None,
                    "reasoning": "Inference unavailable; no business evidence was evaluated.",
                    "assumptions": [],
                    "risks": [],
                    "expected_impact": None,
                    "dissenting_adviser": None,
                    "dissenting_reason": None,
                    "simulated": True,
                    "status": "unavailable"
                })
            else:
                return json.dumps({
                    "status": "unavailable",
                    "simulated": True,
                    "analysis": "No model inference or structured business analysis occurred.",
                    "findings": [],
                    "recommended_action": None
                })

        # No inference occurred. Never fabricate tenant-specific financial facts.
        return (
            "Offline simulated response: Ollama inference was unavailable. "
            "No business facts were independently verified and no recommendation "
            "was generated by an AI model. Review the structured dashboard and "
            "source records for current figures, or retry when Ollama is online."
        )

ollama_gateway = OllamaGateway()
