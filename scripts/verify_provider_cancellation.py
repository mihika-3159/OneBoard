"""Confirm a single-slot live Ollama serves a waiting request after caller termination."""
import asyncio
import json
import os
import sys

import httpx


URL = os.environ["OLLAMA_BASE_URL"]
MODEL = os.environ["ONEBOARD_CI_OLLAMA_MODEL"]


async def generating():
    payload = {
        "model": MODEL, "stream": True,
        "prompt": "Count from one up to ten thousand, one number per line, without stopping. Start at 1.",
        "options": {"num_predict": 4096, "temperature": 0},
    }
    async with httpx.AsyncClient(timeout=90) as client:
        async with client.stream("POST", URL + "/api/generate", json=payload) as response:
            response.raise_for_status()
            announced = False
            async for line in response.aiter_lines():
                event = json.loads(line)
                if event.get("response") and not announced:
                    print("generating", flush=True)
                    announced = True
                if event.get("done"):
                    raise RuntimeError("Provider finished before cancellation")


async def child():
    task = asyncio.create_task(generating())
    stop = asyncio.create_task(asyncio.to_thread(sys.stdin.readline))
    try:
        done, _ = await asyncio.wait([task, stop], return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            task.result()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def verify(mode):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "scripts.verify_provider_cancellation", "child",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
    )
    try:
        if await asyncio.wait_for(process.stdout.readline(), 75) != b"generating\n":
            raise RuntimeError("No live provider generation observed")
        async with httpx.AsyncClient(timeout=15) as client:
            waiting = asyncio.create_task(client.post(URL + "/api/generate", json={
                "model": MODEL, "prompt": "Hello", "stream": False, "options": {"num_predict": 1},
            }))
            await asyncio.sleep(0.4)
            if waiting.done() or process.returncode is not None:
                raise RuntimeError("Single provider slot was not occupied")
            if mode == "disconnect":
                process.stdin.write(b"stop\n")
                await process.stdin.drain()
            else:
                process.kill()
            code = await asyncio.wait_for(process.wait(), 5)
            if mode == "disconnect" and code != 0:
                raise RuntimeError("Caller did not close cleanly")
            result = await asyncio.wait_for(waiting, 10)
            result.raise_for_status()
            if result.json().get("done") is not True:
                raise RuntimeError("Waiting inference did not regain provider capacity")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


if __name__ == "__main__":
    if sys.argv[1:] == ["child"]:
        asyncio.run(child())
    else:
        for scenario in ["disconnect", "worker-termination"]:
            asyncio.run(verify(scenario))
