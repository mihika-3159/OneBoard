"""Persistent coalescing job lease and local-only outbox processing.

PostgreSQL row locks serialize claims. A separate session advisory lock is held
through the job so a long-running healthy worker cannot be overtaken. A crashed
worker's persisted lease becomes reclaimable after its deadline. The job itself
must be idempotent; the alert refresh and local-only outbox both are.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import time
from uuid import uuid4

from sqlalchemy import text
from apps.api.models.operations import ScheduledJobLease, SideEffectOutbox

def _now(db):
    if db.get_bind().dialect.name == "postgresql":
        return float(db.execute(text("SELECT extract(epoch from clock_timestamp())")).scalar_one())
    return time.time()

def _key(job):
    return int.from_bytes(hashlib.sha256(("oneboard:job:" + job).encode()).digest()[:8],
                          "big", signed=True)

def claim_job(db, job, lease_seconds=180, now=None):
    if not job or not 1 <= lease_seconds <= 3600:
        raise ValueError("Invalid job lease")
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _key(job + ":claim")})
    now = _now(db) if now is None else now
    row = db.get(ScheduledJobLease, job)
    if row is None:
        row = ScheduledJobLease(job_key=job, next_due_at=now, lease_until=0, attempts=0)
        db.add(row)
    if row.next_due_at > now or row.lease_until > now:
        db.rollback()
        return None
    token = str(uuid4())
    row.owner_token = token
    row.lease_until = now + lease_seconds
    row.attempts += 1
    db.commit()
    return token

def finish_job(db, job, token, success, now=None, interval_seconds=60):
    if not 1 <= interval_seconds <= 3600:
        raise ValueError("Invalid job interval")
    now = _now(db) if now is None else now
    values = {"owner_token": None, "lease_until": 0,
              "next_due_at": now + (interval_seconds if success else min(15, interval_seconds))}
    if success:
        values["last_success_at"] = now
    count = db.query(ScheduledJobLease).filter(
        ScheduledJobLease.job_key == job, ScheduledJobLease.owner_token == token
    ).update(values, synchronize_session=False)
    db.commit()
    return count == 1

@contextmanager
def execution_lock(bind, job):
    if bind.dialect.name != "postgresql":
        yield True
        return
    with bind.connect() as conn:
        key = _key(job)
        held = False
        try:
            held = conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar_one()
            conn.commit()
            yield held
        finally:
            if held:
                try:
                    if not conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key}).scalar_one():
                        conn.invalidate()
                    else:
                        conn.commit()
                except BaseException:
                    conn.invalidate()
                    raise

def process_local_outbox(db, limit=100):
    """Only transition local draft intents; no provider dispatch exists."""
    query = db.query(SideEffectOutbox).filter(
        SideEffectOutbox.state == "pending",
        SideEffectOutbox.kind == "invoice_reminder_draft",
    ).order_by(SideEffectOutbox.created_at, SideEffectOutbox.id).limit(limit)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    rows = query.all()
    for row in rows:
        row.state = "draft_ready"
        row.processed_at = datetime.utcnow()
    db.commit()
    return len(rows)
