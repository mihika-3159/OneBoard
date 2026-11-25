import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException

from apps.api.services.request_inference import run_request_inference


class RequestInferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_waits_for_inference_cleanup(self):
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def inference():
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        async def disconnected():
            await started.wait()
            return True

        with self.assertRaises(HTTPException) as raised:
            await run_request_inference(SimpleNamespace(is_disconnected=disconnected), inference())
        self.assertEqual(raised.exception.status_code, 499)
        self.assertTrue(stopped.is_set())

    async def test_response_completes_while_client_remains_connected(self):
        request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
        operation = AsyncMock(return_value="completed")
        self.assertEqual(await run_request_inference(request, operation()), "completed")
