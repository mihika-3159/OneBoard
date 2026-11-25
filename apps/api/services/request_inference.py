"""Cancel request-owned inference when the HTTP client disconnects."""

import asyncio

from fastapi import HTTPException


async def run_request_inference(request, operation, poll_seconds=0.1):
    if request is None:
        return await operation

    async def wait_for_disconnect():
        while not await request.is_disconnected():
            await asyncio.sleep(poll_seconds)

    task = asyncio.create_task(operation)
    disconnect = asyncio.create_task(wait_for_disconnect())
    try:
        done, _ = await asyncio.wait((task, disconnect), return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return task.result()
        disconnect.result()
        raise HTTPException(status_code=499, detail="Client disconnected during inference")
    finally:
        for pending in (task, disconnect):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, disconnect, return_exceptions=True)
