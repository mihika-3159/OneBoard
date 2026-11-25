"""SQLite integration regression for a correct password after distributed lockout.

PostgreSQL multi-process lock correctness is separately tested by the opt-in
disposable PostgreSQL suite.
"""
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.core.auth import hash_password
from apps.api.models.business import Business, User, UserSession, LoginThrottleState, AccountSecurity
from apps.api.routers.auth_router import LoginRequest, login


def _request(host):
    return Request({
        "type": "http", "method": "POST", "path": "/api/auth/login",
        "headers": [], "client": (host, 45678),
        "scheme": "https", "server": ("example.test", 443), "query_string": b"",
    })


def test_legitimate_password_recovers_from_remote_account_lockout():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in [Business.__table__, User.__table__, LoginThrottleState.__table__, UserSession.__table__, AccountSecurity.__table__]:
        table.create(engine)
    make_session = sessionmaker(bind=engine)
    email = f"victim-{uuid4()}@example.test"
    correct = "a unique strong test password"
    db = make_session()
    try:
        business = Business(name="Synthetic test tenant")
        db.add(business)
        db.flush()
        user = User(email=email, name="Founder", hashed_password=hash_password(correct),
                    role="founder", business_id=business.id, is_active=True)
        db.add(user)
        db.commit()
        user_id = user.id
        business_id = business.id
    finally:
        db.close()

    try:
        for index in range(5):
            session = make_session()
            try:
                with pytest.raises(HTTPException) as raised:
                    login(LoginRequest(email=email, password="wrong password"),
                          Response(), _request(f"192.0.2.{index+1}"), session)
                assert raised.value.status_code == 401
            finally:
                session.close()

        blocked = make_session()
        try:
            with pytest.raises(HTTPException) as raised:
                login(LoginRequest(email=email, password="another guess"),
                      Response(), _request("203.0.113.77"), blocked)
            assert raised.value.status_code == 429
        finally:
            blocked.close()

        genuine = make_session()
        try:
            response = Response()
            result = login(LoginRequest(email=email, password=correct),
                           response, _request("198.51.100.89"), genuine)
            assert result["status"] == "success"
            assert result["user"]["business_id"] == business_id
            assert genuine.query(UserSession).filter(UserSession.user_id == user_id).count() == 1
            assert genuine.query(LoginThrottleState).count() >= 1
            # Global account counter must be cleared after verified login.
            from apps.api.core.auth import _throttle_key
            assert genuine.query(LoginThrottleState).filter(
                LoginThrottleState.identifier_hash == _throttle_key(f"account:{email}")
            ).count() == 0
        finally:
            genuine.close()
    finally:
        engine.dispose()


def test_source_and_account_throttle_keys_do_not_store_plain_identifiers():
    from apps.api.core.auth import _throttle_key
    key = "source-account:203.0.113.4:founder@example.test"
    hashed = _throttle_key(key)
    assert key not in hashed
    assert len(hashed) == 64
