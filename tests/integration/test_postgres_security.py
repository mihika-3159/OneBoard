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
import apps.api.models.operations

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
            assert revision == "010_batch_b_durability"
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
                reflected_fks = inspector.get_foreign_keys(table_name)
                for constraint in model.foreign_key_constraints:
                    local = tuple(col.parent.name for col in constraint.elements)
                    target = constraint.elements[0].column.table.name
                    remote = tuple(col.column.name for col in constraint.elements)
                    ondelete = (constraint.ondelete or "").upper()
                    assert any(
                        tuple(fk.get("constrained_columns") or ()) == local
                        and fk.get("referred_table") == target
                        and tuple(fk.get("referred_columns") or ()) == remote
                        and ((fk.get("options") or {}).get("ondelete") or "").upper() == ondelete
                        for fk in reflected_fks
                    ), f"Missing PostgreSQL FK: {table_name}{local}->{target}{remote} ON DELETE {ondelete}"
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


def test_07_postgres_downgrade_upgrade_roundtrip_preserves_auth_rows():
    """Rollback migration 005 and 004, then reapply without losing tenant auth data.

    Runs only against the validated disposable localhost oneboard_ci database.
    Rollback must remove only the constraints/indexes registered by migrations 005/004, never drop or
    rewrite businesses, users, or revocable sessions.
    """
    from uuid import uuid4

    engine = _engine()
    tenant_id, user_id, session_id = (str(uuid4()) for _ in range(3))
    env = dict(os.environ, DATABASE_URL=URL, PYTHONPATH=str(ROOT))

    def alembic(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            f"Alembic {' '.join(args)} failed: {result.stdout[-1200:]} {result.stderr[-2000:]}"
        )

    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO businesses (id, name) VALUES (:id, 'Synthetic recovery tenant')"),
                {"id": tenant_id},
            )
            conn.execute(
                text("""INSERT INTO users (id, email, name, hashed_password, business_id, role, is_active)
                        VALUES (:id, :email, 'Recovery founder', 'synthetic-only',
                                :business, 'founder', true)"""),
                {"id": user_id, "email": f"{user_id}@example.invalid", "business": tenant_id},
            )
            conn.execute(
                text("""INSERT INTO user_sessions
                        (id, user_id, business_id, expires_at, is_revoked)
                        VALUES (:id, :user, :business, CURRENT_TIMESTAMP + INTERVAL '1 day', false)"""),
                {"id": session_id, "user": user_id, "business": tenant_id},
            )

        alembic("downgrade", "003_app_schema")
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert revision == "003_app_schema"
            assert conn.execute(text("SELECT count(*) FROM user_sessions WHERE id = :id"),
                                {"id": session_id}).scalar_one() == 1
        alembic("upgrade", "head")
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert revision == "010_batch_b_durability"
            assert conn.execute(text("SELECT count(*) FROM businesses WHERE id = :id"),
                                {"id": tenant_id}).scalar_one() == 1
            assert conn.execute(text("SELECT count(*) FROM users WHERE id = :id"),
                                {"id": user_id}).scalar_one() == 1
            assert conn.execute(text("SELECT count(*) FROM user_sessions WHERE id = :id"),
                                {"id": session_id}).scalar_one() == 1
            indexes = inspect(conn).get_indexes("user_sessions")
            assert any(idx["column_names"] == ["token_hash"] for idx in indexes)
    finally:
        # Synthetic cleanup, without touching other tenant fixtures.
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM user_sessions WHERE id = :id"), {"id": session_id})
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            conn.execute(text("DELETE FROM businesses WHERE id = :id"), {"id": tenant_id})
        engine.dispose()


def test_08_production_guard_rejects_missing_auth_foreign_key(monkeypatch):
    """Even a stamped head with correct indexes cannot omit session ownership FKs."""
    from sqlalchemy.engine.reflection import Inspector
    from apps.api.core.database import init_db

    _engine().dispose()
    original = Inspector.get_foreign_keys

    def hide_session_owner_fk(self, table_name, *args, **kwargs):
        fks = original(self, table_name, *args, **kwargs)
        if table_name == "user_sessions":
            return [
                fk for fk in fks
                if fk.get("constrained_columns") != ["user_id"]
            ]
        return fks

    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
    with monkeypatch.context() as patch:
        patch.setattr(Inspector, "get_foreign_keys", hide_session_owner_fk)
        with pytest.raises(RuntimeError, match="missing required foreign-key constraints"):
            init_db()
    init_db()


def test_09_postgres_rejects_orphan_auth_session():
    """The physical database must reject orphan sessions, not merely the API."""
    from uuid import uuid4
    from sqlalchemy.exc import IntegrityError

    engine = _engine()
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text("""INSERT INTO user_sessions
                            (id, user_id, business_id, expires_at, is_revoked)
                            VALUES (:id, :user, :business,
                                    CURRENT_TIMESTAMP + INTERVAL '1 day', false)"""),
                    {"id": str(uuid4()), "user": str(uuid4()),
                     "business": str(uuid4())},
                )
    finally:
        engine.dispose()


def test_10_orphan_legacy_auth_data_blocks_fk_migration_without_loss():
    """Dirty legacy rows cannot be silently deleted or accepted during FK repair.

    Roll back migrations 006 and 005 on disposable CI PostgreSQL, introduce an
    orphaned session, require 005 to fail atomically, then remove synthetic
    corruption and prove that a clean recovery upgrade succeeds.
    """
    from uuid import uuid4

    engine = _engine()
    session_id = str(uuid4())
    env = dict(os.environ, DATABASE_URL=URL, PYTHONPATH=str(ROOT))

    def run_migration(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )

    try:
        result = run_migration("downgrade", "004_schema_indexes")
        assert result.returncode == 0, result.stderr[-2000:]
        with engine.begin() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "004_schema_indexes"
            conn.execute(
                text("""INSERT INTO user_sessions
                        (id, user_id, business_id, expires_at, is_revoked)
                        VALUES (:id, :missing, :business,
                                CURRENT_TIMESTAMP + INTERVAL '1 day', false)"""),
                {"id": session_id, "missing": str(uuid4()), "business": str(uuid4())},
            )

        result = run_migration("upgrade", "head")
        assert result.returncode != 0, "An orphaned session must block FK migration"
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "004_schema_indexes"
            assert conn.execute(
                text("SELECT count(*) FROM user_sessions WHERE id = :id"),
                {"id": session_id},
            ).scalar_one() == 1, "Migration must not discard dirty legacy tenant records"
            assert "_oneboard_005_created_fks" not in inspect(conn).get_table_names()
    finally:
        # Always remove *only* the synthetic orphan, and restore CI schema.
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM user_sessions WHERE id = :id"), {"id": session_id}
            )
        result = run_migration("upgrade", "head")
        assert result.returncode == 0, result.stderr[-2000:]
        engine.dispose()

    with _engine().connect() as conn:
        assert conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "010_batch_b_durability"


def test_11_postgres_rejects_revoked_membership_for_bearer_and_api_key(monkeypatch):
    """Live auth and role checks must work against the actual PostgreSQL engine.

    Synthetic two-tenant test records live only in the disposable oneboard_ci
    service. Revoking membership denies existing credentials, and a second
    membership never grants access to a non-active workspace.
    """
    from datetime import datetime, timedelta
    from uuid import uuid4

    from fastapi.security import HTTPAuthorizationCredentials
    from starlette.requests import Request

    from apps.api.core import auth
    from apps.api.models.business import (
        Business, BusinessMembership, User, UserSession,
    )

    engine = _engine()
    db = sessionmaker(bind=engine, autoflush=False)()
    suffix = uuid4().hex
    first_id, second_id, user_id, jti = (str(uuid4()) for _ in range(4))

    def request(api_key=None):
        headers = [(b"x-api-key", api_key.encode())] if api_key else []
        return Request({
            "type": "http", "method": "GET", "path": "/api/auth/me",
            "headers": headers, "scheme": "https", "query_string": b"",
            "server": ("oneboard.test", 443),
        })

    try:
        db.add_all([
            Business(id=first_id, name=f"Postgres primary {suffix}"),
            Business(id=second_id, name=f"Postgres secondary {suffix}"),
        ])
        db.flush()
        raw_api_key = auth.generate_api_key()
        user = User(
            id=user_id, email=f"postgres-role-{suffix}@example.invalid",
            name="Synthetic PostgreSQL founder",
            hashed_password="no-real-login",
            role="founder",
            api_key=auth.hash_api_key(raw_api_key),
            business_id=first_id,
            is_active=True,
        )
        db.add(user)
        db.flush()
        primary = BusinessMembership(
            user_id=user_id, business_id=first_id, role="founder",
        )
        secondary = BusinessMembership(
            user_id=user_id, business_id=second_id, role="member",
        )
        db.add_all([
            primary, secondary,
            UserSession(
                id=jti, user_id=user_id, business_id=first_id,
                expires_at=datetime.utcnow() + timedelta(hours=1),
                is_revoked=False,
            ),
        ])
        db.commit()

        token = auth.create_access_token(user_id, first_id, role="founder", jti=jti)
        bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
        assert auth.get_current_user(request(), bearer, db).id == user_id
        assert auth.get_current_user(request(raw_api_key), None, db).id == user_id
        assert auth.require_founder_role(current_user=user, db=db).id == user_id
        with pytest.raises(HTTPException) as outside:
            auth.enforce_tenant_boundary(second_id, user, db)
        assert outside.value.status_code == 403

        primary.role = "member"
        db.commit()
        assert auth.get_current_user(request(), bearer, db).id == user_id
        with pytest.raises(HTTPException) as demoted:
            auth.require_founder_role(current_user=user, db=db)
        assert demoted.value.status_code == 403

        db.delete(primary)
        db.commit()
        for req, credentials in (
            (request(), bearer), (request(raw_api_key), None),
        ):
            with pytest.raises(HTTPException) as revoked:
                auth.get_current_user(req, credentials, db)
            assert revoked.value.status_code == 401
    finally:
        db.rollback()
        # Remove only these synthetic records; never modify other fixtures.
        db.query(UserSession).filter(UserSession.id == jti).delete()
        db.query(BusinessMembership).filter(
            BusinessMembership.user_id == user_id
        ).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.query(Business).filter(
            Business.id.in_([first_id, second_id])
        ).delete()
        db.commit()
        db.close()
        engine.dispose()


def test_12_postgres_shared_nat_registration_quota_across_workers(monkeypatch):
    """Shared-source signup allowance is independent of the login guess limit.

    A 10-signup budget (lowered from default 30 to keep CI lightweight)
    is safely serialized across 14 simultaneous PostgreSQL workers. The
    unrelated login account key and a different source stay usable.
    """
    monkeypatch.setattr(settings, "REGISTRATION_SOURCE_MAX_ATTEMPTS", 10)
    monkeypatch.setattr(settings, "LOGIN_MAX_ATTEMPTS", 5)
    engine = _engine()
    signup_source = "registration-source:198.51.100.212"
    login_source = "source-account:198.51.100.212:person@example.invalid"
    keys = [hashlib.sha256(key.encode()).hexdigest() for key in
            [signup_source, login_source]]
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM login_throttle_states WHERE identifier_hash IN (:a, :b)"),
            {"a": keys[0], "b": keys[1]},
        )

    workers = 14
    barrier = Barrier(workers)
    make_session = sessionmaker(bind=engine, autoflush=False)

    def attempt(_):
        session = make_session()
        try:
            barrier.wait(timeout=20)
            try:
                check_login_throttle(signup_source, session)
                record_failed_login(signup_source, session)
                return "admitted"
            except HTTPException as exc:
                session.rollback()
                assert exc.status_code == 429
                return "throttled"
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(attempt, range(workers)))
        assert results.count("admitted") == 10, results
        assert results.count("throttled") == 4, results
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT attempt_count FROM login_throttle_states WHERE identifier_hash = :key"),
                {"key": keys[0]},
            ).scalar_one() == 10
        db = make_session()
        try:
            # Source-wide registrations must not exhaust the login key for an
            # unrelated account sharing the NAT.
            check_login_throttle(login_source, db)
            db.rollback()
            check_login_throttle("registration-source:203.0.113.212", db)
            db.rollback()
        finally:
            db.close()
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM login_throttle_states WHERE identifier_hash IN (:a, :b)"),
                {"a": keys[0], "b": keys[1]},
            )
        engine.dispose()


def test_13_postgres_shared_login_source_quota_blocks_email_rotation(monkeypatch):
    """Distinct account names cannot bypass one source's shared Argon2 budget."""
    monkeypatch.setattr(settings, "LOGIN_SOURCE_MAX_ATTEMPTS", 10)
    monkeypatch.setattr(settings, "LOGIN_MAX_ATTEMPTS", 5)
    engine = _engine()
    source = "login-source:198.51.100.170"
    key = hashlib.sha256(source.encode()).hexdigest()
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM login_throttle_states WHERE identifier_hash=:key"
        ), {"key": key})
    barrier = Barrier(14)
    make_session = sessionmaker(bind=engine, autoflush=False)

    def attempt(i):
        db = make_session()
        try:
            barrier.wait(timeout=20)
            try:
                # The source-wide budget is shared regardless of the
                # different account email that follows in the login route.
                check_login_throttle(source, db)
                record_failed_login(source, db)
                return "admitted"
            except HTTPException as exc:
                db.rollback()
                assert exc.status_code == 429
                return "limited"
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=14) as pool:
            results = list(pool.map(attempt, range(14)))
        assert results.count("admitted") == 10, results
        assert results.count("limited") == 4, results
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT attempt_count FROM login_throttle_states WHERE identifier_hash=:key"),
                {"key": key},
            ).scalar_one() == 10
        # A distinct source remains independently available.
        db = make_session()
        try:
            check_login_throttle("login-source:203.0.113.170", db)
            db.rollback()
        finally:
            db.close()
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM login_throttle_states WHERE identifier_hash=:key"
            ), {"key": key})
        engine.dispose()


def test_14_postgres_legacy_api_keys_are_hashed_without_losing_users(monkeypatch):
    """Canonical legacy keys are migrated, not disclosed or discarded.

    Downgrading while a hashed active key exists is deliberately refused:
    plaintext secrets cannot be reconstructed for older application versions.
    """
    from uuid import uuid4
    from apps.api.core import auth
    from apps.api.models.business import BusinessMembership, User
    from starlette.requests import Request

    engine = _engine()
    env = dict(os.environ, DATABASE_URL=URL, PYTHONPATH=str(ROOT))
    business_id, user_id = str(uuid4()), str(uuid4())
    old_raw = auth.generate_api_key()
    old_digest = auth.hash_api_key(old_raw)

    def migrate(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )

    try:
        # A disposable, isolated CI schema without active hashed keys can
        # safely return to 005 for a representative legacy upgrade.
        result = migrate("downgrade", "005_auth_foreign_keys")
        assert result.returncode == 0, result.stderr[-2000:]
        with engine.begin() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "005_auth_foreign_keys"
            conn.execute(
                text("INSERT INTO businesses (id,name) VALUES (:id,'Synthetic API migration')"),
                {"id": business_id}
            )
            conn.execute(text(
                """INSERT INTO users (id,email,name,hashed_password,business_id,
                           role,is_active,api_key)
                   VALUES (:id,:email,'Synthetic','none',:business,'founder',
                           true,:api_key)"""
            ), {
                "id": user_id,
                "email": f"key-migration-{user_id}@example.invalid",
                "business": business_id,
                "api_key": old_raw,
            })
            conn.execute(
                text("UPDATE businesses SET owner_id=:user WHERE id=:id"),
                {"user": user_id, "id": business_id},
            )
        result = migrate("upgrade", "head")
        assert result.returncode == 0, result.stderr[-2000:]

        with engine.connect() as conn:
            stored = conn.execute(
                text("SELECT api_key FROM users WHERE id=:id"), {"id": user_id}
            ).scalar_one()
            assert stored == old_digest
            assert stored != old_raw
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "010_batch_b_durability"

        monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
        db = sessionmaker(bind=engine)()
        try:
            request = Request({
                "type": "http", "method": "GET", "path": "/api/auth/me",
                "headers": [(b"x-api-key", old_raw.encode())],
                "scheme": "https", "server": ("api.example.test", 443),
                "query_string": b"",
            })
            assert auth.get_current_user(request, None, db).id == user_id
        finally:
            db.close()

        reversible = migrate("downgrade", "006_api_key_hashing")
        assert reversible.returncode == 0, reversible.stderr[-2000:]
        blocked = migrate("downgrade", "-1")
        assert blocked.returncode != 0, "Credential downgrade must fail closed"
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "006_api_key_hashing"
            assert conn.execute(
                text("SELECT api_key FROM users WHERE id=:id"), {"id": user_id}
            ).scalar_one() == old_digest
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
            conn.execute(text("DELETE FROM businesses WHERE id=:id"), {"id": business_id})
        result = migrate("upgrade", "head")
        assert result.returncode == 0, result.stderr[-2000:]
        engine.dispose()


def test_15_postgres_rejects_weak_legacy_api_key_without_data_loss():
    """Weak demo API secrets block upgrade instead of gaining production trust."""
    from uuid import uuid4

    engine = _engine()
    env = dict(os.environ, DATABASE_URL=URL, PYTHONPATH=str(ROOT))
    business_id, user_id = str(uuid4()), str(uuid4())
    weak_key = "obk_northstar_demo_local_key"

    def migrate(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )

    try:
        result = migrate("downgrade", "005_auth_foreign_keys")
        assert result.returncode == 0, result.stderr[-2000:]
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO businesses (id,name) VALUES (:id,'Weak synthetic key tenant')"),
                {"id": business_id},
            )
            conn.execute(text(
                """INSERT INTO users (id,email,name,hashed_password,business_id,
                           role,is_active,api_key)
                   VALUES (:id,:email,'Synthetic','none',:business,'founder',
                           true,:api_key)"""
            ), {
                "id": user_id,
                "email": f"weak-key-{user_id}@example.invalid",
                "business": business_id,
                "api_key": weak_key,
            })
        result = migrate("upgrade", "head")
        assert result.returncode != 0
        assert "Noncanonical legacy plaintext API key" in result.stderr
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "005_auth_foreign_keys"
            assert conn.execute(
                text("SELECT api_key FROM users WHERE id=:id"),
                {"id": user_id},
            ).scalar_one() == weak_key
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
            conn.execute(text("DELETE FROM businesses WHERE id=:id"), {"id": business_id})
        result = migrate("upgrade", "head")
        assert result.returncode == 0, result.stderr[-2000:]
        engine.dispose()


def test_16_postgres_production_guard_rejects_stamped_plaintext_api_key(monkeypatch):
    """Revision 006 stamp is insufficient when an admin reintroduces raw keys."""
    from uuid import uuid4
    from apps.api.core.database import init_db

    engine = _engine()
    business_id, user_id = str(uuid4()), str(uuid4())
    try:
        with engine.begin() as conn:
            assert conn.execute(text(
                "SELECT version_num FROM alembic_version"
            )).scalar_one() == "010_batch_b_durability"
            conn.execute(
                text("INSERT INTO businesses (id,name) VALUES (:id,'Tampered synthetic tenant')"),
                {"id": business_id},
            )
            conn.execute(text(
                """INSERT INTO users (id,email,name,hashed_password,business_id,
                           role,is_active,api_key)
                   VALUES (:id,:email,'Synthetic','none',:business,'founder',
                           true,:raw_key)"""
            ), {
                "id": user_id,
                "email": f"raw-key-stamp-{user_id}@example.invalid",
                "business": business_id,
                "raw_key": "obk_" + "c" * 56,
            })
        monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
        with pytest.raises(RuntimeError, match="non-hashed API credentials"):
            init_db()
        with engine.connect() as conn:
            assert conn.execute(text(
                "SELECT api_key FROM users WHERE id=:id"
            ), {"id": user_id}).scalar_one() == "obk_" + "c" * 56
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
            conn.execute(text("DELETE FROM businesses WHERE id=:id"), {"id": business_id})
        engine.dispose()
    # Once the synthetic corruption is removed, startup is allowed.
    init_db()


def test_17_postgres_concurrent_idempotent_workflow_execution():
    """Two worker sessions with the same tenant key persist one workflow run.

    The durable unique constraint and pg_advisory_xact_lock prevent duplicate
    action execution and approval creation under concurrent incoming requests.
    All rows and keys are synthetic and restricted to disposable oneboard_ci.
    """
    from uuid import uuid4
    from apps.api.models.workflow import (
        WorkflowDefinition, WorkflowRun, ApprovalRequest, AuditLog,
    )
    from apps.api.services.workflow_engine import workflow_engine

    engine = _engine()
    biz_id, workflow_id = str(uuid4()), str(uuid4())
    key = "parallel_idempotent_001"
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        with factory() as db:
            db.execute(text(
                "INSERT INTO businesses (id,name) VALUES (:id,'Concurrent workflow tenant')"
            ), {"id": biz_id})
            db.add(WorkflowDefinition(
                id=workflow_id, business_id=biz_id, name="CI idempotency",
                nodes=[{"id": "start", "type": "trigger", "data": {}}],
                edges=[], is_valid=True,
            ))
            db.commit()

        barrier = Barrier(2)

        def run_workflow(_):
            db = factory()
            try:
                barrier.wait(timeout=20)
                result = workflow_engine.execute_workflow(
                    db, biz_id, workflow_id, idempotency_key=key
                )
                return result.id
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=2) as workers:
            run_ids = list(workers.map(run_workflow, range(2)))
        assert run_ids[0] == run_ids[1], run_ids
        with factory() as db:
            runs = db.query(WorkflowRun).filter(
                WorkflowRun.business_id == biz_id
            ).all()
            assert len(runs) == 1
            assert runs[0].status == "completed"
            assert runs[0].idempotency_key == key
            assert len(runs[0].step_results) == 1
            assert db.query(AuditLog).filter(
                AuditLog.business_id == biz_id,
                AuditLog.action == "execute_workflow"
            ).count() == 1
            assert db.query(ApprovalRequest).filter(
                ApprovalRequest.business_id == biz_id
            ).count() == 0
    finally:
        with factory() as db:
            db.query(AuditLog).filter(AuditLog.business_id == biz_id).delete()
            db.query(ApprovalRequest).filter(
                ApprovalRequest.business_id == biz_id
            ).delete()
            db.query(WorkflowRun).filter(WorkflowRun.business_id == biz_id).delete()
            db.query(WorkflowDefinition).filter(
                WorkflowDefinition.business_id == biz_id
            ).delete()
            db.execute(text("DELETE FROM businesses WHERE id=:id"), {"id": biz_id})
            db.commit()
        engine.dispose()


def test_18_postgres_concurrent_approval_claim_prevents_duplicate_resume():
    """Only one PostgreSQL worker may resume a high-risk approval checkpoint."""
    from uuid import uuid4
    from apps.api.models.workflow import (
        WorkflowDefinition, WorkflowRun, ApprovalRequest, AuditLog,
    )
    from apps.api.services.workflow_engine import workflow_engine

    engine = _engine()
    biz_id, workflow_id = str(uuid4()), str(uuid4())
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        with factory() as db:
            db.execute(text(
                "INSERT INTO businesses (id,name) VALUES (:id,'Approval concurrency tenant')"
            ), {"id": biz_id})
            wf = WorkflowDefinition(
                id=workflow_id, business_id=biz_id, name="CI guarded workflow",
                nodes=[
                    {"id": "before", "type": "trigger", "data": {}},
                    {"id": "gate", "type": "approval", "data": {}},
                    {"id": "after", "type": "trigger", "data": {}},
                ],
                edges=[
                    {"source": "before", "target": "gate"},
                    {"source": "gate", "target": "after"},
                ],
                is_valid=True,
            )
            db.add(wf)
            db.commit()
            run = workflow_engine.execute_workflow(
                db, biz_id, workflow_id, idempotency_key="concurrent_approve_001"
            )
            assert run.status == "awaiting_approval"
            run_id = run.id
            request_id = db.query(ApprovalRequest).filter(
                ApprovalRequest.workflow_run_id == run_id
            ).one().id

        barrier = Barrier(2)

        def attempt(_):
            db = factory()
            try:
                barrier.wait(timeout=20)
                try:
                    result = workflow_engine.approve_and_resume_run(
                        db, run_id, request_id, business_id=biz_id
                    )
                    return result.status
                except ValueError:
                    db.rollback()
                    return "duplicate_rejected"
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(attempt, range(2)))
        assert statuses.count("completed") == 1, statuses
        assert statuses.count("duplicate_rejected") == 1, statuses
        with factory() as db:
            run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
            assert run.status == "completed"
            assert run.step_results["after"]["status"] == "success"
            assert db.query(AuditLog).filter(
                AuditLog.business_id == biz_id,
                AuditLog.action == "resume_workflow",
            ).count() == 1
            assert db.query(ApprovalRequest).filter(
                ApprovalRequest.id == request_id
            ).one().status == "approved"
    finally:
        with factory() as db:
            db.query(AuditLog).filter(AuditLog.business_id == biz_id).delete()
            db.query(ApprovalRequest).filter(
                ApprovalRequest.business_id == biz_id
            ).delete()
            db.query(WorkflowRun).filter(WorkflowRun.business_id == biz_id).delete()
            db.query(WorkflowDefinition).filter(
                WorkflowDefinition.business_id == biz_id
            ).delete()
            db.execute(text("DELETE FROM businesses WHERE id=:id"), {"id": biz_id})
            db.commit()
        engine.dispose()


@pytest.mark.asyncio
async def test_19_postgres_indexed_memory_finds_old_relevant_chunk(monkeypatch):
    """GIN full-text retrieval must reach old data beyond recent 1,000 chunks."""
    from uuid import uuid4
    from unittest.mock import AsyncMock
    from apps.api.models.memory import MemoryDocument, MemoryChunk
    from apps.api.services.memory_engine import memory_engine
    import apps.api.services.memory_engine as memory_module

    engine = _engine()
    tenant = str(uuid4())
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        with factory() as db:
            doc = MemoryDocument(
                business_id=tenant, title="Old synthetic archive",
                content_hash="d" * 64, file_type="txt",
            )
            db.add(doc)
            db.flush()
            doc_id = doc.id
            db.add(MemoryChunk(
                business_id=tenant, document_id=doc_id,
                chunk_index=0, content="uniquehistoricalneedle synthetic legacy key",
            ))
            db.commit()
        # Later arrivals are intentionally newer than the matching result.
        with factory() as db:
            db.add_all([
                MemoryChunk(
                    business_id=tenant, document_id=doc_id,
                    chunk_index=i + 1, content=f"Unrelated routine note {i}",
                )
                for i in range(1010)
            ])
            db.commit()
            monkeypatch.setattr(
                memory_module.ollama_gateway, "generate_embedding",
                AsyncMock(return_value=[0.1, 0.2]),
            )
            rows = await memory_engine.search_semantic_memory(
                db, tenant, "uniquehistoricalneedle", top_k=5
            )
            assert rows and "uniquehistoricalneedle" in rows[0]["content"]
            assert rows[0]["search_strategy"] == "postgresql_indexed_fulltext"
            assert rows[0]["candidate_limit_applied"] is False
            index_names = {x["name"] for x in inspect(engine).get_indexes("memory_chunks")}
            assert "ix_memory_chunks_fts_simple" in index_names
    finally:
        with factory() as db:
            db.query(MemoryChunk).filter(MemoryChunk.business_id == tenant).delete()
            db.query(MemoryDocument).filter(MemoryDocument.business_id == tenant).delete()
            db.commit()
        engine.dispose()


def test_20_postgres_concurrent_customer_import_is_idempotent():
    """Concurrent workers share a durable key and cannot duplicate rows."""
    from uuid import uuid4
    from apps.api.models.entities import Customer
    from apps.api.models.operations import LocalCustomerImport
    from apps.api.services.customer_csv_import import import_customer_csv

    engine = _engine()
    factory = sessionmaker(bind=engine, autoflush=False)
    tenant = str(uuid4())
    text_data = "name,mrr,status\nSynthetic A,12.25,active\nSynthetic B,10,churned\n"
    barrier = Barrier(2)

    def apply(_):
        with factory() as db:
            barrier.wait(timeout=20)
            return import_customer_csv(
                db, tenant, text_data, "concurrent_import_0001",
                source_name="Synthetic CSV", dry_run=False,
            )["status"]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(apply, range(2)))
        assert sorted(statuses) == ["already_imported", "imported"]
        with factory() as db:
            assert db.query(Customer).filter_by(business_id=tenant).count() == 2
            assert db.query(LocalCustomerImport).filter_by(business_id=tenant).count() == 1
    finally:
        with factory() as db:
            db.query(LocalCustomerImport).filter_by(business_id=tenant).delete()
            db.query(Customer).filter_by(business_id=tenant).delete()
            db.commit()
        engine.dispose()


def test_21_concurrent_tenant_resource_budget_is_cross_worker_and_isolated(monkeypatch):
    """12 overlapping workers: 4 accepted, 8 HTTP 429; other tenant unaffected."""
    from uuid import uuid4
    from apps.api.services import tenant_resource_budget as budgets
    from apps.api.models.operations import TenantResourceWindow

    engine = _engine()
    factory = sessionmaker(bind=engine, autoflush=False)
    tenant_a, tenant_b = str(uuid4()), str(uuid4())
    policy = "ai_command"
    monkeypatch.setitem(budgets.POLICIES, policy, (4, 60))
    barrier = Barrier(12)

    def attempt(_):
        with factory() as db:
            barrier.wait(timeout=30)
            try:
                budgets.consume_tenant_budget(db, tenant_a, policy, now=2000000)
                return "accepted"
            except HTTPException as exc:
                assert exc.status_code == 429
                assert int(exc.headers["Retry-After"]) > 0
                return "limited"

    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            answers = list(pool.map(attempt, range(12)))
        assert answers.count("accepted") == 4
        assert answers.count("limited") == 8
        with factory() as db:
            one = db.query(TenantResourceWindow).filter(
                TenantResourceWindow.business_id == tenant_a,
                TenantResourceWindow.resource == policy,
            ).one()
            assert one.attempt_count == 4
            other = budgets.consume_tenant_budget(db, tenant_b, policy, now=2000000)
            assert other["remaining"] == 3
    finally:
        with factory() as db:
            db.query(TenantResourceWindow).filter(
                TenantResourceWindow.business_id.in_([tenant_a, tenant_b])
            ).delete(synchronize_session=False)
            db.commit()
        engine.dispose()


def test_22_cluster_inference_slots_reject_third_and_release_on_error():
    from apps.api.services.cluster_capacity import inference_slot
    engine = _engine()
    try:
        with inference_slot(engine) as first, inference_slot(engine) as second:
            assert first and second
            with inference_slot(engine) as third:
                assert not third
        with pytest.raises(RuntimeError):
            with inference_slot(engine) as acquired:
                assert acquired
                raise RuntimeError("synthetic failure")
        with inference_slot(engine) as first, inference_slot(engine) as second:
            assert first and second
    finally:
        engine.dispose()


def test_23_postgres_lease_claim_is_exclusive_and_recovers():
    from uuid import uuid4
    from apps.api.services.durable_jobs import claim_job, finish_job
    from apps.api.models.operations import ScheduledJobLease
    engine = _engine()
    factory = sessionmaker(bind=engine)
    job = str(uuid4())
    barrier = Barrier(4)
    def attempt(_):
        with factory() as db:
            barrier.wait(timeout=10)
            return claim_job(db, job, lease_seconds=10, now=100)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(attempt, range(4)))
        tokens = [token for token in claims if token]
        assert len(tokens) == 1
        with factory() as db:
            recovered = claim_job(db, job, now=110)
            assert recovered and recovered != tokens[0]
            assert not finish_job(db, job, tokens[0], True, now=111)
            assert finish_job(db, job, recovered, True, now=112)
    finally:
        with factory() as db:
            db.query(ScheduledJobLease).filter_by(job_key=job).delete()
            db.commit()
        engine.dispose()


def test_24_postgres_rejects_cross_tenant_document_reference():
    from uuid import uuid4
    from sqlalchemy.exc import IntegrityError
    from apps.api.models.memory import MemoryDocument, MemoryChunk
    engine = _engine()
    factory = sessionmaker(bind=engine)
    tenant, other, doc = (str(uuid4()) for _ in range(3))
    try:
        with factory() as db:
            db.add(MemoryDocument(id=doc, business_id=tenant, title="Synthetic",
                                  content_hash="a"*64))
            db.commit()
            db.add(MemoryChunk(document_id=doc, business_id=other, content="synthetic"))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    finally:
        with factory() as db:
            db.query(MemoryDocument).filter_by(id=doc).delete()
            db.commit()
        engine.dispose()


def test_25_postgres_rls_scoped_reads_and_writes_with_non_superuser():
    from uuid import uuid4
    from sqlalchemy.exc import DBAPIError
    from apps.api.core.database import scope_tenant_session
    from apps.api.models.memory import MemoryDocument
    engine = _engine()
    factory = sessionmaker(bind=engine)
    role = "oneboard_rls_ci_" + uuid4().hex[:12]
    a, b = str(uuid4()), str(uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS"))
            conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            conn.execute(text(f"GRANT SELECT, INSERT, UPDATE ON memory_documents TO {role}"))
        with factory() as db:
            db.add_all([MemoryDocument(business_id=t, title="Synthetic",
                                       content_hash="a"*64) for t in (a,b)])
            db.commit()
            db.execute(text(f"SET LOCAL ROLE {role}"))
            scope_tenant_session(db, a)
            assert [row.business_id for row in db.query(MemoryDocument).all()] == [a]
            db.add(MemoryDocument(business_id=b, title="Rejected", content_hash="b"*64))
            with pytest.raises(DBAPIError):
                db.flush()
            db.rollback()
            db.execute(text(f"SET LOCAL ROLE {role}"))
            # SQLAlchemy transaction hook restores scope after rollback.
            assert [row.business_id for row in db.query(MemoryDocument).all()] == [a]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM memory_documents WHERE business_id IN (:a,:b)"), {"a":a,"b":b})
            conn.execute(text(f"DROP OWNED BY {role}"))
            conn.execute(text(f"DROP ROLE {role}"))
        engine.dispose()
