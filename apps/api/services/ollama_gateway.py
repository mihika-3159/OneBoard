import httpx
import json
import logging
import time
from typing import List, Dict, Any, Optional, AsyncGenerator
from apps.api.core.config import settings

logger = logging.getLogger(__name__)

class OllamaGateway:
    def __init__(self, base_url: str = settings.OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.active_profile = settings.DEFAULT_MODEL_PROFILE
        
    async def check_health(self) -> Dict[str, Any]:
        """Check if local Ollama daemon is reachable and list downloaded models."""
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                latency_ms = int((time.time() - start) * 1000)
                if res.status_code == 200:
                    models = res.json().get("models", [])
                    return {
                        "status": "connected",
                        "base_url": self.base_url,
                        "latency_ms": latency_ms,
                        "available_models": [m.get("name") for m in models],
                        "active_profile": self.active_profile,
                        "profile_details": settings.MODEL_PROFILES.get(self.active_profile, {})
                    }
        except Exception as e:
            logger.info(f"Ollama server not reachable at {self.base_url}: {e}")
            
        return {
            "status": "offline",
            "base_url": self.base_url,
            "latency_ms": 0,
            "available_models": [],
            "active_profile": self.active_profile,
            "profile_details": settings.MODEL_PROFILES.get(self.active_profile, {}),
            "offline_mode": True,
            "message": "Local Ollama daemon is offline or not installed. High-fidelity local simulation adapter is active."
        }

    def get_model_for_task(self, task_type: str = "chat") -> str:
        profile = settings.MODEL_PROFILES.get(self.active_profile, settings.MODEL_PROFILES["balanced"])
        if task_type == "reasoning":
            return profile.get("reasoning_model", "llama3.1:8b")
        elif task_type == "embedding":
            return profile.get("embedding_model", "nomic-embed-text")
        return profile.get("chat_model", "qwen2.5:7b")

    async def chat_complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        task_type: str = "chat",
        format_json: bool = False
    ) -> Dict[str, Any]:
        """Execute chat completion via local Ollama with fallback simulation."""
        target_model = model or self.get_model_for_task(task_type)
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": [],
            "stream": False,
        }
        
        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})
        for msg in messages:
            payload["messages"].append(msg)
            
        if format_json:
            payload["format"] = "json"

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(f"{self.base_url}/api/chat", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    content = data.get("message", {}).get("content", "")
                    duration_ms = int((time.time() - start_time) * 1000)
                    return {
                        "content": content,
                        "model": target_model,
                        "simulated": False,
                        "duration_ms": duration_ms
                    }
        except Exception as e:
            logger.warning(f"Ollama chat call failed ({e}). Engaging deterministic local business reasoning adapter.")

        # Deterministic simulation fallback
        duration_ms = int((time.time() - start_time) * 1000)
        simulated_response = self._generate_simulated_response(messages, system_prompt, format_json)
        return {
            "content": simulated_response,
            "model": f"{target_model} (local simulated fallback)",
            "simulated": True,
            "duration_ms": max(duration_ms, 85)
        }

    async def generate_embedding(self, text: str, model: Optional[str] = None) -> List[float]:
        """Fetch local text embedding from Ollama or fallback to deterministic hash vector."""
        target_model = model or self.get_model_for_task("embedding")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": target_model, "prompt": text}
                )
                if res.status_code == 200:
                    return res.json().get("embedding", [])
        except Exception:
            pass
            
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
                    "recommendation": "Maintain core Growth tier pricing at $59/mo while offering annual prepay discounts to stabilize cash runway.",
                    "reasoning": "Current runway stands at 7.2 months. A sudden price hike risks churn on accounts with bespoke quotes, whereas upfront billing bolsters working capital.",
                    "assumptions": ["Churn remains below 4% monthly", "Annual upfront conversion reaches 18%"],
                    "risks": ["Price sensitivity among SMB cohort", "Sales cycle may lengthen by 1.5 weeks"],
                    "expected_impact": {"metric": "Cash Runway", "target": "+3.5 months", "timeframe": "60 days"},
                    "dissenting_adviser": "Marketing Adviser",
                    "dissenting_reason": "Aggressive annual lock-in could dampen top-of-funnel conversion without strong self-serve onboarding."
                })
            else:
                return json.dumps({
                    "status": "success",
                    "analysis": "Analyzed query against structured business state.",
                    "findings": ["Cash runway is healthy at 7.2 months.", "1 customer commitment pending delivery."],
                    "recommended_action": "Review overdue commitment for Sarah Chen before Friday."
                })
                
        # Default conversational response
        return (
            "I have examined Northstar Studio's current operational state across your financial ledger, "
            "CRM, and active commitments. Our Monthly Recurring Revenue (MRR) is $18,450 across 38 active customers, "
            "with a net cash runway of 7.2 months. \n\n"
            "Key priorities requiring founder attention today:\n"
            "1. **Critical Commitment**: Custom webhook exporter promised to Sarah Chen (Acme Corp) is due in 3 days.\n"
            "2. **Pricing Discrepancy**: Proposal document references $49/mo while published tier is $59/mo.\n"
            "3. **Boardroom Deliberation**: The Executive Council is prepared for the Q2 Growth & Pricing Review."
        )

ollama_gateway = OllamaGateway()
