"""Serialize PostgreSQL schema migrations across concurrent deploy/startup workers.

The lock is transaction-scoped and must be acquired on the SAME connection and
transaction that Alembic uses for version checks and DDL. SQLite remains a
single-process development/test database, not a production migration target.
"""
from sqlalchemy import text

# Stable, application-specific signed bigint. Do not change between deployments.
ONEBOARD_MIGRATION_LOCK_ID = 0x4F4E45424F415244


def acquire_migration_lock(connection) -> bool:
    """Acquire the PostgreSQL transaction advisory lock, if applicable.

    Caller must already be inside a transaction, and must run Alembic's
    migration using this exact connection before committing. Never use a
    session-level advisory lock: exceptions could leave it held in a pool.
    """
    if connection.dialect.name != "postgresql":
        return False
    if not connection.in_transaction():
        raise RuntimeError("PostgreSQL migration lock requires an active transaction")
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": ONEBOARD_MIGRATION_LOCK_ID},
    )
    return True
