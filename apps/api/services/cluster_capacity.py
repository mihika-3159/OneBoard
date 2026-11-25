"""PostgreSQL cluster-wide admission for local inference HTTP requests."""
from contextlib import contextmanager
import hashlib
from sqlalchemy import text
from apps.api.core.database import engine

GLOBAL_SLOTS = 2

def _key(slot):
    return int.from_bytes(hashlib.sha256(
        f"oneboard:inference:{slot}".encode()).digest()[:8], "big", signed=True)

@contextmanager
def inference_slot(bind=None):
    bind = engine if bind is None else bind
    if bind.dialect.name != "postgresql":
        yield True
        return
    with bind.connect() as conn:
        held = None
        try:
            for slot in range(GLOBAL_SLOTS):
                key = _key(slot)
                if conn.execute(text("SELECT pg_try_advisory_lock(:key)"),
                                {"key": key}).scalar_one():
                    held = key
                    break
            conn.commit()
            yield held is not None
        finally:
            if held is not None:
                try:
                    if not conn.execute(text("SELECT pg_advisory_unlock(:key)"),
                                        {"key": held}).scalar_one():
                        conn.invalidate()
                    else:
                        conn.commit()
                except BaseException:
                    conn.invalidate()
                    raise
