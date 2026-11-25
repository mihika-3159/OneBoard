"""Durable inference dispatch on a private PostgreSQL database shared by API and workers."""
import asyncio
from functools import lru_cache
import json
import time
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text
from apps.api.services.inference_stream import on_text


@lru_cache(maxsize=1)
def queue_engine(url):
    return create_engine(url, pool_pre_ping=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS inference_requests (
    id uuid PRIMARY KEY, tenant text NOT NULL, path text NOT NULL,
    payload jsonb, reply jsonb, partial text NOT NULL DEFAULT '', status integer, owner uuid,
    created timestamptz NOT NULL DEFAULT clock_timestamp(),
    deadline timestamptz NOT NULL, lease timestamptz, attempts integer NOT NULL DEFAULT 0
)
"""

LOCK = "SELECT pg_advisory_xact_lock(684231091342)"


def initialize(engine):
    with engine.begin() as db:
        db.execute(text(LOCK))
        db.execute(text(SCHEMA))
        db.execute(text("CREATE INDEX IF NOT EXISTS inference_pending ON inference_requests(created) WHERE status IS NULL"))
        db.execute(text("CREATE TABLE IF NOT EXISTS inference_turns (tenant text PRIMARY KEY, served timestamptz NOT NULL)"))


def submit(engine, tenant, path, payload, timeout, request_id):
    with engine.begin() as db:
        db.execute(text(LOCK))
        count, own = db.execute(text("""
            SELECT count(*), count(*) FILTER (WHERE tenant=:tenant) FROM inference_requests
            WHERE status IS NULL AND deadline > clock_timestamp()
        """), {"tenant": tenant}).one()
        if count >= 256 or own >= 32:
            return False
        db.execute(text("""
            INSERT INTO inference_requests(id,tenant,path,payload,deadline)
            VALUES (:id,:tenant,:path,CAST(:payload AS jsonb),clock_timestamp()+:timeout * interval '1 second')
        """), {"id": request_id, "tenant": tenant, "path": path, "payload": json.dumps(payload), "timeout": timeout})
        return True


def claim(engine, slots=2):
    with engine.begin() as db:
        db.execute(text(LOCK))
        db.execute(text("DELETE FROM inference_requests WHERE deadline <= clock_timestamp()"))
        db.execute(text("DELETE FROM inference_turns WHERE served < clock_timestamp() - interval '1 hour'"))
        active = db.execute(text("SELECT count(*) FROM inference_requests WHERE status IS NULL AND lease > clock_timestamp()")).scalar_one()
        if active >= slots:
            return None
        row = db.execute(text("""
            SELECT q.id,q.tenant,q.path,q.payload,extract(epoch FROM q.deadline-clock_timestamp()) AS remaining
            FROM inference_requests q LEFT JOIN inference_turns t ON q.tenant=t.tenant
            WHERE q.status IS NULL AND (q.lease IS NULL OR q.lease <= clock_timestamp())
              AND q.attempts < 2 AND q.partial = ''
            ORDER BY t.served NULLS FIRST,q.created,q.id LIMIT 1
        """)).mappings().first()
        if row is None:
            return None
        owner = str(uuid4())
        db.execute(text("""
            UPDATE inference_requests SET owner=:owner,lease=clock_timestamp()+interval '5 seconds',
            attempts=attempts+1 WHERE id=:id
        """), {"id": row["id"], "owner": owner})
        db.execute(text("""
            INSERT INTO inference_turns(tenant,served) VALUES(:tenant,clock_timestamp())
            ON CONFLICT(tenant) DO UPDATE SET served=excluded.served
        """), {"tenant": row["tenant"]})
        return dict(row, owner=owner)


def renew(engine, job):
    with engine.begin() as db:
        return db.execute(text("""
            UPDATE inference_requests SET lease=clock_timestamp()+interval '5 seconds'
            WHERE id=:id AND owner=:owner AND lease > clock_timestamp() AND deadline > clock_timestamp()
        """), {"id": job["id"], "owner": job["owner"]}).rowcount == 1


def finish(engine, job, status, response):
    with engine.begin() as db:
        db.execute(text("""
            UPDATE inference_requests SET status=:status,reply=CAST(:reply AS jsonb),payload=NULL,lease=NULL
            WHERE id=:id AND owner=:owner AND lease > clock_timestamp() AND deadline > clock_timestamp()
        """), {"id": job["id"], "owner": job["owner"], "status": status, "reply": json.dumps(response)})


def read(engine, tenant, request_id):
    with engine.connect() as db:
        return db.execute(text("SELECT status,reply,partial FROM inference_requests WHERE id=:id AND tenant=:tenant"),
                          {"id": request_id, "tenant": tenant}).first()


def remove(engine, tenant, request_id):
    with engine.begin() as db:
        db.execute(text("DELETE FROM inference_requests WHERE id=:id AND tenant=:tenant"),
                   {"id": request_id, "tenant": tenant})


def publish(engine, job, partial):
    with engine.begin() as db:
        return db.execute(text("""
            UPDATE inference_requests SET partial=:partial WHERE id=:id AND owner=:owner
            AND lease > clock_timestamp() AND deadline > clock_timestamp()
        """), {"partial": partial, "id": job["id"], "owner": job["owner"]}).rowcount == 1


async def dispatch(engine, tenant, path, payload, timeout):
    emit = on_text.get()
    payload = dict(payload, stream=True) if emit and path == "/api/chat" else payload
    offset = 0
    request_id = str(uuid4())
    stop = time.monotonic() + timeout
    try:
        accepted = await asyncio.to_thread(submit, engine, tenant, path, payload, timeout, request_id)
        if not accepted:
            return httpx.Response(429)
        while time.monotonic() < stop:
            row = await asyncio.to_thread(read, engine, tenant, request_id)
            if row is None:
                break
            if emit and len(row.partial) > offset:
                await emit(row.partial[offset:])
                offset = len(row.partial)
            if row.status is not None:
                return httpx.Response(row.status, json=row.reply)
            await asyncio.sleep(0.1)
        raise asyncio.TimeoutError()
    finally:
        await asyncio.to_thread(remove, engine, tenant, request_id)
