"""Run one worker against the dedicated inference PostgreSQL database."""
import asyncio
import time

from apps.api.core.config import settings
from apps.api.services.inference_budget import TokenBudgetExceeded, inference_tenant
from apps.api.services.inference_queue import claim, finish, initialize, publish, queue_engine, renew
from apps.api.services.inference_stream import on_text
from apps.api.services.ollama_gateway import OllamaGateway, _CapacityExceeded


async def execute(engine, gateway, job):
    async def invoke():
        parts = []
        last_flush = 0.0

        async def emit(fragment):
            nonlocal last_flush
            parts.append(fragment)
            now = time.monotonic()
            if now - last_flush >= 0.1:
                if not await asyncio.to_thread(publish, engine, job, "".join(parts)):
                    raise asyncio.CancelledError()
                last_flush = now

        token = on_text.set(emit if job["payload"].get("stream") else None)
        try:
            with inference_tenant(job["tenant"]):
                return await gateway._call_providers(job["path"], job["payload"], float(job["remaining"]))
        finally:
            on_text.reset(token)

    task = asyncio.create_task(invoke())
    try:
        while not task.done():
            await asyncio.wait((task,), timeout=0.5)
            if not await asyncio.to_thread(renew, engine, job):
                return
        if task.cancelled():
            return
        result = task.result()
        status = result.status_code
        body = result.json() if status == 200 else {}
    except (TokenBudgetExceeded, _CapacityExceeded):
        status, body = 429, {}
    except Exception:
        status, body = 503, {}
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await asyncio.to_thread(finish, engine, job, status, body)


async def main():
    if not settings.INFERENCE_QUEUE_URL.startswith("postgresql"):
        raise ValueError("Set INFERENCE_QUEUE_URL to the dedicated PostgreSQL database")
    engine = queue_engine(settings.INFERENCE_QUEUE_URL)
    await asyncio.to_thread(initialize, engine)
    gateway = OllamaGateway()
    while True:
        job = await asyncio.to_thread(claim, engine)
        if job is None:
            await asyncio.sleep(0.1)
        else:
            await execute(engine, gateway, job)


if __name__ == "__main__":
    asyncio.run(main())
