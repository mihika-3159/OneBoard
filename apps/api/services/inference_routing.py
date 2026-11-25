"""Route an inference operation across explicitly configured replicas."""
import asyncio
from typing import Awaitable, Callable, Protocol

import httpx

from apps.api.services.inference_controls import CircuitOpen
from apps.api.services.inference_adapters import ProviderUnavailable


class Reply(Protocol):
    status_code: int


async def route(operation: Callable[[str], Awaitable[Reply]], origins, timeout, can_failover=lambda: True):
    async def attempt():
        deadline = asyncio.get_running_loop().time() + timeout
        for index, origin in enumerate(origins):
            last = index == len(origins) - 1
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            try:
                # Preserve time for subsequent replicas when a provider hangs.
                result = await asyncio.wait_for(operation(origin), remaining if last else remaining / (len(origins) - index))
            except (CircuitOpen, ProviderUnavailable, httpx.ConnectError, httpx.TimeoutException, asyncio.TimeoutError):
                if last or not can_failover():
                    raise
                continue
            if last or not can_failover() or result.status_code not in (404, 429, 502, 503, 504):
                return result
        raise RuntimeError("An inference provider is required")

    return await asyncio.wait_for(attempt(), timeout)
