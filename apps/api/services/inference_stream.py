import asyncio
from contextvars import ContextVar
import json

import httpx


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


async def stream_events(operation):
    queue = asyncio.Queue(maxsize=32)

    async def run():
        async def emit(fragment):
            await queue.put({"delta": fragment})

        token = on_text.set(emit)
        try:
            result = await operation()
            await queue.put({"result": result})
        except Exception:
            await queue.put({"error": "Generation interrupted"})
        finally:
            on_text.reset(token)

    task = asyncio.create_task(run())
    try:
        while True:
            item = await queue.get()
            yield json.dumps(item) + "\n"
            if "delta" not in item:
                break
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
