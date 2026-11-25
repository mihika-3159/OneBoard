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


    async def test_cancel_during_queue_submission_removes_late_insert(self):
        import threading
        from unittest.mock import patch
        from apps.api.services import inference_queue

        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        records = set()

        def submit(engine, tenant, path, payload, timeout, request_id):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("Submission did not resume")
            records.add((tenant, request_id))
            return True

        def remove(engine, tenant, request_id):
            records.discard((tenant, request_id))

        with patch.object(inference_queue, "submit", submit), patch.object(inference_queue, "remove", remove):
            task = asyncio.create_task(inference_queue.dispatch(None, "tenant", "/api/chat", {}, 10))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                task.cancel()
                await asyncio.sleep(0)
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 2)
                self.assertEqual(records, set())
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)


    async def test_structured_stream_never_exposes_provisional_json(self):
        from datetime import datetime
        async def operation():
            await on_text.get()('{"unvalidated":')
            return {"validated": True, "created": datetime(2026, 1, 1)}
        frames = [frame async for frame in stream_events(operation, expose_text=False)]
        self.assertEqual(len(frames), 1)
        self.assertNotIn("unvalidated", frames[0])
        self.assertIn('"validated": true', frames[0])
