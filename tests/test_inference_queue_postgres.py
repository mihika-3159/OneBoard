import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from apps.api.services.inference_queue import claim, finish, initialize, publish, queue_engine, read, remove, renew, submit


@pytest.mark.skipif(not os.getenv("ONEBOARD_QUEUE_TEST_URL"), reason="Dedicated queue database required")
def test_distributed_fair_claims_leases_and_cancellation():
    engine = queue_engine(os.environ["ONEBOARD_QUEUE_TEST_URL"])
    initialize(engine)
    first, second, other = [str(uuid4()) for _ in range(3)]
    for tenant, key in [("a", first), ("a", second), ("b", other)]:
        assert submit(engine, tenant, "/api/chat", {"model": "test"}, 60, key)
    a = claim(engine)
    b = claim(engine)
    assert str(a["id"]) == first and str(b["id"]) == other
    assert claim(engine) is None
    assert read(engine, "b", first) is None
    finish(engine, a, 200, {"done": True})
    assert read(engine, "a", first).reply == {"done": True}
    c = claim(engine)
    assert str(c["id"]) == second
    remove(engine, "b", other)
    assert not renew(engine, b)
    with engine.begin() as db:
        db.execute(text("UPDATE inference_requests SET lease=clock_timestamp() WHERE id=:id"), {"id": second})
    recovered = claim(engine)
    assert recovered["id"] == c["id"] and recovered["owner"] != c["owner"]
    assert not publish(engine, c, "stale")
    assert publish(engine, recovered, "partial")
    assert read(engine, "a", second).partial == "partial"
    remove(engine, "a", second)
    remove(engine, "a", first)


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("ONEBOARD_QUEUE_TEST_URL"), reason="Dedicated queue database required")
async def test_client_and_independent_worker_stream_and_cancel():
    import asyncio

    import httpx
    from apps.api.services.inference_queue import dispatch
    from apps.api.services.inference_stream import on_text
    from scripts.inference_worker import execute

    engine = queue_engine(os.environ["ONEBOARD_QUEUE_TEST_URL"])
    initialize(engine)

    async def take():
        for _ in range(100):
            job = await asyncio.to_thread(claim, engine)
            if job:
                return job
            await asyncio.sleep(0.02)
        raise AssertionError("Queue did not receive work")

    for cancel in [False, True]:
        stopped = asyncio.Event()
        partial = asyncio.Event()

        class Provider:
            async def _call_providers(self, path, payload, timeout):
                try:
                    await on_text.get()("streamed")
                    if cancel:
                        await asyncio.Future()
                    await on_text.get()(" tail")
                    return httpx.Response(200, json={"message": {"content": "streamed tail"}, "done": True})
                finally:
                    stopped.set()

        fragments = []

        async def emit(fragment):
            fragments.append(fragment)
            if "".join(fragments).startswith("streamed"):
                partial.set()

        token = on_text.set(emit)
        try:
            client = asyncio.create_task(dispatch(engine, "workspace", "/api/chat", {"model": "test"}, 9))
        finally:
            on_text.reset(token)
        worker = asyncio.create_task(execute(engine, Provider(), await take()))
        try:
            await asyncio.wait_for(partial.wait(), 4)
            if cancel:
                client.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await client
            else:
                assert (await client).json()["done"]
                assert "".join(fragments) == "streamed tail"
            await asyncio.wait_for(worker, 4)
            assert stopped.is_set()
        finally:
            client.cancel()
            worker.cancel()
            await asyncio.gather(client, worker, return_exceptions=True)
