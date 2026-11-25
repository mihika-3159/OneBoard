"""Production signup abuse controls: shared, source-wide, fail-closed admission."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from apps.api.routers import auth_router


def _request(ip="198.51.100.8", forwarded_for="203.0.113.99"):
    headers = [(b"x-forwarded-for", forwarded_for.encode("ascii"))]
    return Request({
        "type": "http", "method": "POST", "path": "/api/auth/register",
        "headers": headers, "client": (ip, 12345) if ip else None,
        "scheme": "https", "server": ("oneboard.example", 443),
        "query_string": b"",
    })


def _payload(email):
    return auth_router.RegisterRequest(
        name="Synthetic Founder", email=email, password="synthetic-password-123",
        business_name="Test Registration",
    )


@pytest.mark.parametrize("email", [
    "alpha@example.invalid", "beta@example.invalid",
    "gamma@example.invalid",
])
def test_production_registration_uses_same_source_budget_across_accounts(
    monkeypatch, email
):
    monkeypatch.setattr(auth_router.settings, "ONEBOARD_PRODUCTION_MODE", True)
    keys = []

    def deny(key, db):
        keys.append(key)
        raise HTTPException(status_code=429, detail="throttled")

    monkeypatch.setattr(auth_router, "check_login_throttle", deny)
    password_hash = Mock(side_effect=AssertionError("Argon2 should not run"))
    monkeypatch.setattr(auth_router, "hash_password", password_hash)
    db = Mock()
    with pytest.raises(HTTPException) as exc:
        auth_router.register(_payload(email), Response(), _request(), db)
    assert exc.value.status_code == 429
    assert keys == ["registration-source:198.51.100.8"]
    db.query.assert_not_called()
    db.commit.assert_not_called()
    password_hash.assert_not_called()


def test_production_registration_records_attempt_before_expensive_work(monkeypatch):
    monkeypatch.setattr(auth_router.settings, "ONEBOARD_PRODUCTION_MODE", True)
    calls = []
    monkeypatch.setattr(
        auth_router, "check_login_throttle",
        lambda key, db: calls.append(("check", key)),
    )

    def fail_persistence(key, db):
        calls.append(("record", key))
        raise RuntimeError("database write failed")

    monkeypatch.setattr(auth_router, "record_failed_login", fail_persistence)
    password_hash = Mock(side_effect=AssertionError("Hashing must never start"))
    monkeypatch.setattr(auth_router, "hash_password", password_hash)
    db = Mock()
    with pytest.raises(RuntimeError, match="database write failed"):
        auth_router.register(
            _payload("first@example.invalid"), Response(), _request(), db
        )
    assert calls == [
        ("check", "registration-source:198.51.100.8"),
        ("record", "registration-source:198.51.100.8"),
    ]
    db.query.assert_not_called()
    password_hash.assert_not_called()


def test_production_registration_does_not_trust_spoofed_forwarded_ip(monkeypatch):
    monkeypatch.setattr(auth_router.settings, "ONEBOARD_PRODUCTION_MODE", True)
    seen = []

    def deny(key, db):
        seen.append(key)
        raise HTTPException(status_code=429, detail="throttled")

    monkeypatch.setattr(auth_router, "check_login_throttle", deny)
    db = Mock()
    with pytest.raises(HTTPException):
        auth_router.register(
            _payload("test@example.invalid"), Response(),
            _request(ip="192.0.2.20", forwarded_for="1.2.3.4"), db,
        )
    assert seen == ["registration-source:192.0.2.20"]


def test_production_registration_fails_closed_without_transport_identity(monkeypatch):
    monkeypatch.setattr(auth_router.settings, "ONEBOARD_PRODUCTION_MODE", True)
    db = Mock()
    with pytest.raises(HTTPException) as exc:
        auth_router.register(
            _payload("no-ip@example.invalid"), Response(), _request(ip=None), db,
        )
    assert exc.value.status_code == 503
    db.query.assert_not_called()
    db.commit.assert_not_called()
