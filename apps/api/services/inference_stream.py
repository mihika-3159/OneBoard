import asyncio
from contextvars import ContextVar
import json

import httpx
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from apps.api.services.request_inference import run_request_inference


on_text = ContextVar("inference_stream_callback", default=None)


async def read_chat_stream(client, url, payload, emit):
    fragments = []
    total = 0
    async with client.stream("POST", url, json={**payload, "stream": True}) as response:
        if response.status_code != 200:
            return httpx.Response(response.status_code)
        async for line in response.aiter_lines():
            if not line:
                continue
            event = json.loads(line)
            if event.get("error") or event.get("model") not in (None, payload["model"]):
                raise ValueError("Invalid provider stream")
            delta = event["message"]["content"]
            if not isinstance(delta, str):
                raise ValueError("Invalid text fragment")
            total += len(delta)
            if total > 262144:
                raise ValueError("Response exceeds streaming limit")
            if delta:
                fragments.append(delta)
                await emit(delta)
            if event.get("done") is True:
                event["message"] = {"role": "assistant", "content": "".join(fragments)}
                return httpx.Response(200, json=event)
    raise ValueError("Interrupted provider stream")


async def stream_events(operation, expose_text=True, provider_stream=True):
    queue = asyncio.Queue(maxsize=32)

    async def run():
        async def emit(fragment):
            if expose_text:
                await queue.put({"delta": fragment})

        token = on_text.set(emit if provider_stream else None)
        try:
            result = await operation()
            await queue.put({"result": jsonable_encoder(result)})
        except Exception:
            await queue.put({"error": "Generation interrupted"})
        finally:
            on_text.reset(token)

    task = asyncio.create_task(run())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if not expose_text:
                    yield json.dumps({"progress": "Inference running"}) + "\n"
                continue
            yield json.dumps(item) + "\n"
            if "delta" not in item:
                break
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def stream_or_wait(request, operation, provider_stream=True):
    """Existing JSON clients retain status codes; opted-in browsers get safe progress."""
    if request is not None and "application/x-ndjson" in request.headers.get("accept", ""):
        return StreamingResponse(
            stream_events(operation, expose_text=False, provider_stream=provider_stream),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    return await run_request_inference(request, operation())
