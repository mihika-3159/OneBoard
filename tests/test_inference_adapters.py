import json
import unittest
from unittest.mock import AsyncMock

import httpx
from apps.api.services.inference_adapters import CompatibleAdapter, capacity_admitted, verify_remote_capacity, ProviderUnavailable
from apps.api.services.generation_cache import GenerationCache
from apps.api.services.inference_routing import route


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_capacity_fails_closed_and_routes(self):
        self.assertFalse(capacity_admitted({"accepting": True, "memory_available_bytes": 99, "load_per_cpu": 0.5}, 100, 2))
        self.assertFalse(capacity_admitted({"accepting": True, "memory_available_bytes": 100, "load_per_cpu": float("nan")}, 100, 2))
        self.assertTrue(capacity_admitted({"accepting": True, "memory_available_bytes": 100, "load_per_cpu": 0.5}, 100, 2))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))) as client:
            with self.assertRaises(ProviderUnavailable):
                await verify_remote_capacity(client, "https://operator.example", 100, 2)
        result = await route(AsyncMock(side_effect=[ProviderUnavailable(), httpx.Response(200)]), ["a", "b"], 1)
        self.assertEqual(result.status_code, 200)

    async def test_compatible_stream_requires_pin_and_terminal_event(self):
        digest = "a" * 64
        def handler(req):
            if req.url.path == "/oneboard/models":
                return httpx.Response(200, json={"models": [{"name": "m", "digest": digest}]})
            self.assertEqual(req.url.path, "/v1/chat/completions")
            self.assertEqual(json.loads(req.content)["max_tokens"], 64)
            return httpx.Response(200, content=b'data: {"model":"m","choices":[{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            emit = AsyncMock()
            result = await CompatibleAdapter({"m": digest}).send(client, "http://localhost:8080", "/api/chat",
                {"model": "m", "messages": [], "options": {"num_predict": 64}}, emit)
            self.assertEqual(result.json()["message"]["content"], "hello")
            emit.assert_awaited_once_with("hello")
            with self.assertRaises(ProviderUnavailable):
                await CompatibleAdapter({}).send(client, "http://localhost:8080", "/api/chat", {"model": "m"}, None)

    def test_generation_cache_is_tenant_pinned_bounded_and_rejects_simulation(self):
        clock = [0]
        cache = GenerationCache(capacity=1, ttl=2, clock=lambda: clock[0])
        payload = {"model": "m", "messages": [], "options": {"temperature": 0}}
        key = cache.key("a", "origin", "pin", payload)
        other = cache.key("b", "origin", "pin", payload)
        cache.put(key, {"content": "wrong", "simulated": True})
        self.assertIsNone(cache.get(key))
        cache.put(key, {"content": "real", "simulated": False})
        self.assertIsNone(cache.get(other))
        self.assertTrue(cache.get(key)["cache_hit"])
        clock[0] = 3
        self.assertIsNone(cache.get(key))
        self.assertIsNone(cache.key("a", "origin", None, payload))
