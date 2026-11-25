import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import httpx

from apps.api.services.inference_routing import route
from apps.api.services.inference_stream import read_chat_stream, stream_events, on_text


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_transient_failure_to_configured_replica(self):
        send = AsyncMock(side_effect=[httpx.ConnectError("offline"), SimpleNamespace(status_code=200)])
        result = await route(send, ["primary", "local-replica"], 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual([call.args[0] for call in send.await_args_list], ["primary", "local-replica"])

    async def test_stream_requires_terminal_event_and_cleans_up(self):
        transport = httpx.MockTransport(lambda _: httpx.Response(
            200, content=b'{"message":{"content":"draft"},"done":false}\n'
        ))
        emit = AsyncMock()
        async with httpx.AsyncClient(transport=transport) as client:
            with self.assertRaisesRegex(ValueError, "Interrupted"):
                await read_chat_stream(client, "http://local.test", {"model": "test"}, emit)
        emit.assert_awaited_once_with("draft")

    async def test_closing_browser_stream_cancels_generation(self):
        stopped = asyncio.Event()

        async def run():
            try:
                await on_text.get()("partial")
                await asyncio.Future()
            finally:
                stopped.set()

        events = stream_events(run)
        self.assertIn("partial", await anext(events))
        await events.aclose()
        self.assertTrue(stopped.is_set())
