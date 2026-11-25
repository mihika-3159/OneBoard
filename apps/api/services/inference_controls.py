"""Resource bounds and failure recovery shared by Ollama inference calls."""

import asyncio
from contextlib import contextmanager
import time


class CircuitOpen(Exception):
    """The provider is cooling down after consecutive failures."""


class ProviderCircuit:
    def __init__(self, threshold=3, cooldown_seconds=15, clock=time.monotonic):
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._open_until = None
        self._probe_active = False
        self._generation = 0

    @contextmanager
    def attempt(self):
        probing = self._open_until is not None
        if probing and (self._clock() < self._open_until or self._probe_active):
            raise CircuitOpen()
        if probing:
            self._probe_active = True
        generation = self._generation
        try:
            yield lambda failed: self._record(generation, failed)
        finally:
            if probing:
                self._probe_active = False

    def _record(self, generation, failed):
        if generation != self._generation:
            return
        if not failed:
            self._failures = 0
            self._open_until = None
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = self._clock() + self._cooldown
            self._generation += 1


async def retry_provider(send, retry_response, retry_exceptions, delay_seconds=0.2):
    """Retry once when the connection failed or the server signals unavailability."""
    try:
        response = await send()
    except retry_exceptions:
        pass
    else:
        if not retry_response(response):
            return response
    await asyncio.sleep(delay_seconds)
    return await send()


def fit_prompt(messages, input_budget):
    """Keep system instructions and whole recent turns within a conservative budget."""
    system = [message for message in messages if message.get("role") == "system"]
    turns = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if not turns or role == "user":
            turns.append([])
        turns[-1].append(message)

    def cost(group):
        return sum(
            16 + len(message.get("content", "").encode("utf-8"))
            for message in group
        )

    remaining = input_budget - cost(system)
    if remaining < 0 or (turns and cost(turns[-1]) > remaining):
        return None
    kept = []
    for turn in reversed(turns):
        size = cost(turn)
        if size > remaining:
            break
        remaining -= size
        kept.append(turn)
    return system + [message for turn in reversed(kept) for message in turn]
