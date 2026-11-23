"""Real PostgreSQL migration and concurrent auth tests (disposable CI database).

Only runs when ONEBOARD_TEST_POSTGRES_URL is explicitly provided. Never target
customer databases. CI provisions a fresh service container for this test job.
"""
import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.core.auth import check_login_throttle, record_failed_login
from apps.api.core.config import settings
from apps.api.core.database import Base
from apps.api.models.business import LoginThrottleState
import apps.api.models.goals_tasks
import apps.api.models.entities
import apps.api.models.decision_evidence
import apps.api.models.agent_council
import apps.api.models.memory
import apps.api.models.workflow
import apps.api.models.integrations

URL = os.getenv("ONEBOARD_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Requires dedicated disposable PostgreSQL CI URL")
ROOT = Path(__file__).resolve().parents[2]


def _engine():
    assert URL and URL.startswith("postgresql+psycopg://"), "CI PostgreSQL URL required"
    parsed = make_url(URL)
    assert parsed.host in ("127.0.0.1", "localhost", "::1"), "Never run against remote PostgreSQL"
    assert parsed.database == "oneboard_ci", "Only the disposable oneboard_ci database is permitted"
    assert os.getenv("DATABASE_URL") == URL, "The Alembic and test database URLs must match"
    return create_engine(URL, pool_pre_ping=True)


def test_01_two_concurrent_alembic_upgrades_create_full_postgres_schema():
    # Validate the target BEFORE spawning any migration process.
    validation_engine = _engine()
    validation_engine.dispose()
    env = dict(os.environ, DATABASE_URL=URL, PYTHONPATH=str(ROOT))
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        ) for _ in range(2)
    ]
    for proc in processes:
        try:
            stdout, stderr = proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            pytest.fail("PostgreSQL concurrent migration timed out")
        assert proc.returncode == 0, (
            f"Concurrent migration exited {proc.returncode}: {stdout[-1500:]} {stderr[-2000:]}"
        )
    engine = _engine()
    try:
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert revision == "004_schema_indexes"
            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            expected = set(Base.metadata.tables)
            assert not expected - tables, f"Missing schema tables: {expected - tables}"
            for table_name, model in Base.metadata.tables.items():
                actual = {c["name"] for c in inspector.get_columns(table_name)}
                needed = {c.name for c in model.columns}
                assert needed <= actual, f"Missing columns for {table_name}: {needed - actual}"
    finally:
        engine.dispose()


def test_02_postgres_shared_throttle_serializes_simultaneous_failed_logins():
    assert URL
    engine = _engine()
    key = "account:concurrency-fixture@example.invalid"
    hashed_key = hashlib.sha256(key.encode()).hexdigest()
    limit = settings.LOGIN_MAX_ATTEMPTS
    workers = max(limit + 4, 10)
    make_session = sessionmaker(bind=engine, autoflush=False)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM login_throttle_states WHERE identifier_hash = :key"),
            {"key": hashed_key}
        )
    gate = Barrier(workers)

    def attempt(_):
        session = make_session()
        try:
            gate.wait(timeout=20)
            try:
                check_login_throttle(key, session)
                record_failed_login(key, session)
                return "accepted"
            except HTTPException as exc:
                session.rollback()
                assert exc.status_code == 429
                assert int(exc.headers["Retry-After"]) >= 1
                return "throttled"
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(attempt, range(workers)))
        assert outcomes.count("accepted") == limit, outcomes
        assert outcomes.count("throttled") == workers - limit, outcomes
        with engine.connect() as conn:
            state = conn.execute(
                text("SELECT attempt_count FROM login_throttle_states WHERE identifier_hash = :key"),
                {"key": hashed_key}
            ).scalar_one()
        assert state == limit
    finally:
        engine.dispose()


def test_03_production_schema_guard_accepts_fully_migrated_postgres(monkeypatch):
    # The process uses the same disposable DATABASE_URL as the CI service.
    from apps.api.core.database import init_db
    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
    init_db()


def test_04_postgres_schema_constraints_and_indexes_match_models():
    """A stamped schema with missing unique constraints or indexes is not safe."""
    engine = _engine()
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            for table_name, model in Base.metadata.tables.items():
                actual_indexes = inspector.get_indexes(table_name)
                indexed_columns = {
                    (tuple(index["column_names"]), bool(index.get("unique")))
                    for index in actual_indexes
                }
                actual_unique = {
                    tuple(sorted(item["column_names"]))
                    for item in inspector.get_unique_constraints(table_name)
                }
                actual_unique.update(
                    tuple(sorted(index["column_names"]))
                    for index in actual_indexes
                    if index.get("unique")
                )
                for index in model.indexes:
                    expected = (tuple(column.name for column in index.columns), bool(index.unique))
                    assert expected in indexed_columns, (
                        f"Missing PostgreSQL index on {table_name}: {expected}; "
                        f"model name {index.name}"
                    )
                for constraint in model.constraints:
                    from sqlalchemy import UniqueConstraint
                    if isinstance(constraint, UniqueConstraint):
                        cols = tuple(sorted(column.name for column in constraint.columns))
                        assert cols in actual_unique, (
                            f"Missing PostgreSQL unique constraint on {table_name}: {cols}"
                        )
    finally:
        engine.dispose()


def test_05_repeated_upgrade_preserves_auth_indexes_and_schema():
    """Repeated deploys must not remove token lookups or other security indexes."""
    engine = _engine()
    try:
        with engine.connect() as conn:
            before = {
                (tuple(item["column_names"]), bool(item.get("unique")))
                for item in inspect(conn).get_indexes("user_sessions")
            }
            assert (("token_hash",), False) in before
        env = dict(os.environ, DATABASE_URL=URL, PYTHONPATH=str(ROOT))
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        with engine.connect() as conn:
            after = {
                (tuple(item["column_names"]), bool(item.get("unique")))
                for item in inspect(conn).get_indexes("user_sessions")
            }
            assert before == after
    finally:
        engine.dispose()


def test_06_production_guard_rejects_stamped_schema_missing_session_index(monkeypatch):
    """A matching Alembic revision must not mask a missing session lookup index."""
    from sqlalchemy.engine.reflection import Inspector
    from apps.api.core.database import init_db

    _engine().dispose()  # Enforce disposable PostgreSQL target precondition.
    original = Inspector.get_indexes

    def hide_session_index(self, table_name, *args, **kwargs):
        indexes = original(self, table_name, *args, **kwargs)
        if table_name == "user_sessions":
            return [
                index for index in indexes
                if index.get("column_names") != ["token_hash"]
            ]
        return indexes

    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
    with monkeypatch.context() as patch:
        patch.setattr(Inspector, "get_indexes", hide_session_index)
        with pytest.raises(RuntimeError, match="missing required indexes/unique constraints"):
            init_db()
    # Once the index is visible again, the same real migrated database is valid.
    init_db()
