import httpx
import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional, AsyncGenerator
from apps.api.core.config import settings
from apps.api.services.cluster_capacity import inference_slot
from apps.api.services.model_identity import matches_pin

from apps.api.services.inference_controls import CircuitOpen, ProviderCircuit, fit_prompt, retry_provider

logger = logging.getLogger(__name__)

class _CapacityExceeded(Exception):
    pass


class _ModelIdentityMismatch(Exception):
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
        
    async def _post_inference(self, path, payload, timeout):
        with self._circuit.attempt() as record_failure:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if settings.OLLAMA_MODEL_DIGESTS:
                    await asyncio.wait_for(self._verify_model(client, payload["model"]), timeout=3.0)

                async def send():
                    return await client.post(f"{self.base_url}{path}", json=payload)

                try:
                    response = await asyncio.wait_for(
                        retry_provider(
                            send,
                            lambda reply: reply.status_code in (502, 503, 504),
                            (httpx.ConnectError, httpx.ConnectTimeout),
                        ),
                        timeout=timeout,
                    )
                except (httpx.TransportError, asyncio.TimeoutError):
                    record_failure(True)
                    raise
                record_failure(response.status_code >= 500)
                return response

    async def _verify_model(self, client, model):
        expected = settings.OLLAMA_MODEL_DIGESTS.get(model)
        if expected is None:
            raise _ModelIdentityMismatch()
        try:
            response = await client.get(f"{self.base_url}/api/tags", timeout=2.0)
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
        format_json: bool = False
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
        reason = "context_budget_exceeded"
        acquired = False
        try:
            if fitted is not None:
                payload["messages"] = fitted
                reason = "provider_unavailable"
            try:
                if fitted is not None:
                    await asyncio.wait_for(
                        self._inference_slots.acquire(),
                        timeout=self._queue_timeout_seconds,
                    )
                    acquired = True
            except asyncio.TimeoutError:
                reason = "capacity_exceeded"
            if acquired:
                try:
                    with inference_slot() as admitted:
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
                            return {
                                "content": content,
                                "model": target_model,
                                "simulated": False,
                                "input_tokens": data.get("prompt_eval_count"),
                                "output_tokens": data.get("eval_count"),
                                "provider_load_ns": data.get("load_duration"),
                                "provider_eval_ns": data.get("eval_duration"),
                                "output_limit_reached": data.get("done_reason") == "length",
                                "duration_ms": int((time.monotonic() - start_time) * 1000),
                            }
                    elif response.status_code == 404:
                        reason = "model_unavailable"
                    else:
                        reason = "provider_http_error"
                except _CapacityExceeded:
                    reason = "capacity_exceeded"
                except _ModelIdentityMismatch:
                    reason = "model_identity_unverified"
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
        acquired = False
        try:
            await asyncio.wait_for(self._inference_slots.acquire(), timeout=self._queue_timeout_seconds)
            acquired = True
            with inference_slot() as admitted:
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
                            return [float(x) for x in v]
        except Exception:
            pass
        finally:
            if acquired:
                self._inference_slots.release()
        return None

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
