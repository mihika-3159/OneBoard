"""Database-backed login protection: isolated SQLite regression for multi-session state.

PostgreSQL cross-process locking still needs a real multi-worker integration test.
"""
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.core.auth import check_login_throttle, record_failed_login, reset_login_throttle
from apps.api.models.business import LoginThrottleState


@pytest.fixture
def sessions():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    LoginThrottleState.__table__.create(engine)
    make_session = sessionmaker(bind=engine)
    a, b = make_session(), make_session()
    try:
        yield a, b
    finally:
        a.close()
        b.close()
        engine.dispose()


def test_failed_logins_visible_across_sessions(sessions):
    first, second = sessions
    identity = "test-client:founder@example.invalid"
    reset_login_throttle(identity, first)
    for _ in range(5):
        check_login_throttle(identity, first)
        record_failed_login(identity, first)
    with pytest.raises(HTTPException) as exc:
        check_login_throttle(identity, second)
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) > 0
    second.rollback()
    reset_login_throttle(identity, second)
    check_login_throttle(identity, first)
    first.rollback()


def test_expired_window_resets_counter(sessions):
    first, second = sessions
    identity = "test-client:expired@example.invalid"
    with patch("apps.api.core.auth.time.time", return_value=1_000.0):
        for _ in range(5):
            check_login_throttle(identity, first)
            record_failed_login(identity, first)
    with patch("apps.api.core.auth.time.time", return_value=1_301.0):
        check_login_throttle(identity, second)
        record_failed_login(identity, second)
    state = second.query(LoginThrottleState).first()
    assert state.attempt_count == 1
    assert state.identifier_hash != identity
    second.rollback()


def test_production_never_falls_back_to_process_local_counter():
    from apps.api.core.config import settings
    with patch.object(settings, "ONEBOARD_PRODUCTION_MODE", True):
        with pytest.raises(RuntimeError, match="shared DB session"):
            check_login_throttle("no-database")
        with pytest.raises(RuntimeError, match="shared DB session"):
            record_failed_login("no-database")
        with pytest.raises(RuntimeError, match="shared DB session"):
            reset_login_throttle("no-database")
