import asyncio
import unittest
from unittest.mock import AsyncMock

from apps.api.services.inference_controls import (
    CircuitOpen, ProviderCircuit, fit_prompt, retry_provider,
)


class CircuitTests(unittest.TestCase):
    def test_cooldown_single_probe_and_recovery(self):
        now = [0]
        circuit = ProviderCircuit(threshold=2, cooldown_seconds=10, clock=lambda: now[0])
        with circuit.attempt() as stale:
            for _ in range(2):
                with circuit.attempt() as record:
                    record(True)
            stale(False)
        with self.assertRaises(CircuitOpen), circuit.attempt():
            self.fail("The circuit should reject calls during cooldown")

        now[0] = 10
        with circuit.attempt() as probe:
            with self.assertRaises(CircuitOpen), circuit.attempt():
                self.fail("Only one recovery request should run")
            probe(False)
        with circuit.attempt() as record:
            record(False)

    def test_cancelled_probe_can_be_replaced(self):
        now = [0]
        circuit = ProviderCircuit(threshold=1, cooldown_seconds=1, clock=lambda: now[0])
        with circuit.attempt() as record:
            record(True)
        now[0] = 1
        with self.assertRaises(asyncio.CancelledError), circuit.attempt():
            raise asyncio.CancelledError()
        with circuit.attempt() as probe:
            probe(False)


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_status_is_retried_once(self):
        send = AsyncMock(side_effect=[503, 503])
        result = await retry_provider(send, lambda status: status == 503, (), 0)
        self.assertEqual(result, 503)
        self.assertEqual(send.await_count, 2)

    async def test_nontransient_response_and_cancellation_are_not_retried(self):
        send = AsyncMock(return_value=404)
        self.assertEqual(await retry_provider(send, lambda status: status == 503, (), 0), 404)
        send.assert_awaited_once()
        cancelled = AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):
            await retry_provider(cancelled, lambda status: True, (OSError,), 0)
        cancelled.assert_awaited_once()

    async def test_recovers_from_a_connection_failure(self):
        send = AsyncMock(side_effect=[ConnectionError(), 200])
        self.assertEqual(
            await retry_provider(send, lambda status: False, (ConnectionError,), 0),
            200,
        )
        self.assertEqual(send.await_count, 2)


class ContextTests(unittest.TestCase):
    def test_preserves_instructions_and_latest_turn_and_drops_whole_history(self):
        system = {"role": "system", "content": "safe"}
        old = {"role": "user", "content": "old"}
        answer = {"role": "assistant", "content": "reply"}
        latest = {"role": "user", "content": "नमस्ते"}
        messages = [system, old, answer, latest]
        self.assertEqual(fit_prompt(messages, 54), [system, latest])
        self.assertIsNone(fit_prompt(messages, 53))
        self.assertEqual(fit_prompt(messages, 120), messages)
