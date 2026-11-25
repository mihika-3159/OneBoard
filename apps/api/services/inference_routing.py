"""Route an inference operation across explicitly configured replicas."""
import asyncio
from typing import Awaitable, Callable, Protocol

import httpx

from apps.api.services.inference_controls import CircuitOpen


class Reply(Protocol):
    status_code: int


async def route(operation: Callable[[str], Awaitable[Reply]], origins, timeout):
    async def attempt():
        for index, origin in enumerate(origins):
            last = index == len(origins) - 1
            try:
                result = await operation(origin)
            except (CircuitOpen, httpx.ConnectError, httpx.ConnectTimeout):
                if last:
                    raise
                continue
            if last or result.status_code not in (502, 503, 504):
                return result
        raise RuntimeError("An inference provider is required")

    return await asyncio.wait_for(attempt(), timeout)
