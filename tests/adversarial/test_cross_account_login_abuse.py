"""Adversarial protection against one source rotating through many emails.

A valid account password must not reset the shared-source admission budget,
and no expensive password verification may occur once that budget is full.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from apps.api.routers import auth_router


def _request(ip="198.51.100.50", forwarded="203.0.113.40"):
    return Request({
        "type": "http", "method": "POST", "path": "/api/auth/login",
        "headers": [(b"x-forwarded-for", forwarded.encode("ascii"))],
        "client": (ip, 12345) if ip else None,
        "scheme": "https", "server": ("api.example.test", 443),
        "query_string": b"",
    })


@pytest.mark.parametrize("email", [
    "first@example.invalid", "second@example.invalid",
    "third@example.invalid",
])
def test_rotated_email_source_budget_precedes_account_lookup_and_hashing(
    monkeypatch, email
):
    monkeypatch.setattr(auth_router.settings, "ONEBOARD_PRODUCTION_MODE", True)
    checked = []

    def deny(key, db):
        checked.append(key)
        raise HTTPException(status_code=429, detail="shared source exhausted")

    monkeypatch.setattr(auth_router, "check_login_throttle", deny)
    monkeypatch.setattr(auth_router, "verify_password",
                        Mock(side_effect=AssertionError("Argon2 must not execute")))
    db = Mock()
    with pytest.raises(HTTPException) as exc:
        auth_router.login(
            auth_router.LoginRequest(email=email, password="guess"),
            Response(), _request(), db
        )
    assert exc.value.status_code == 429
    assert checked == ["login-source:198.51.100.50"]
    db.query.assert_not_called()
    db.commit.assert_not_called()


def test_successful_login_never_resets_shared_source_budget(monkeypatch):
    monkeypatch.setattr(auth_router.settings, "ONEBOARD_PRODUCTION_MODE", True)
    calls = []
    monkeypatch.setattr(
        auth_router, "check_login_throttle",
        lambda key, db: calls.append(("check", key))
    )
    monkeypatch.setattr(
        auth_router, "record_failed_login",
        lambda key, db: calls.append(("record", key))
    )
    monkeypatch.setattr(
        auth_router, "reset_login_throttle",
        lambda key, db: calls.append(("reset", key))
    )
    monkeypatch.setattr(auth_router, "verify_password", lambda pw, hash: True)
    monkeypatch.setattr(auth_router, "_require_active_membership",
                        lambda user, db: None)
    user = SimpleNamespace(
        id="synthetic-user", email="founder@example.invalid",
        business_id="synthetic-tenant", role="founder",
        is_active=True, hashed_password="fake"
    )
    business = SimpleNamespace(
        id="synthetic-tenant", name="Synthetic Tenant",
        industry="Test", current_cash_balance=0.0
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.side_effect = [user, business]

    result = auth_router.login(
        auth_router.LoginRequest(
            email="founder@example.invalid", password="correct"
        ), Response(), _request(), db
    )
    assert result["status"] == "success"
    assert calls[:3] == [
        ("check", "login-source:198.51.100.50"),
        ("record", "login-source:198.51.100.50"),
        ("check", "source-account:198.51.100.50:founder@example.invalid"),
    ]
    assert ("reset", "login-source:198.51.100.50") not in calls


def test_spoofed_forwarding_headers_cannot_rotate_login_source(monkeypatch):
    monkeypatch.setattr(auth_router.settings, "ONEBOARD_PRODUCTION_MODE", True)
    checked = []

    def deny(key, db):
        checked.append(key)
        raise HTTPException(status_code=429, detail="shared source exhausted")

    monkeypatch.setattr(auth_router, "check_login_throttle", deny)
    with pytest.raises(HTTPException) as exc:
        auth_router.login(
            auth_router.LoginRequest(email="test@example.invalid", password="guess"),
            Response(), _request(ip="192.0.2.77", forwarded="8.8.8.8"), Mock()
        )
    assert exc.value.status_code == 429
    assert checked == ["login-source:192.0.2.77"]


def test_production_login_fails_closed_without_transport_source(monkeypatch):
    monkeypatch.setattr(auth_router.settings, "ONEBOARD_PRODUCTION_MODE", True)
    db = Mock()
    with pytest.raises(HTTPException) as exc:
        auth_router.login(
            auth_router.LoginRequest(email="test@example.invalid", password="guess"),
            Response(), _request(ip=None), db
        )
    assert exc.value.status_code == 503
    db.query.assert_not_called()
    db.commit.assert_not_called()


def test_source_wide_login_budget_remains_larger_than_account_guess_budget(
    monkeypatch
):
    from apps.api.core import auth
    monkeypatch.setattr(auth, "_LOGIN_ATTEMPTS", {})
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", False)
    monkeypatch.setattr(auth.settings, "LOGIN_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(auth.settings, "LOGIN_SOURCE_MAX_ATTEMPTS", 60)
    source = "login-source:198.51.100.50"
    individual = "source-account:198.51.100.50:account@example.invalid"
    for _ in range(5):
        auth.check_login_throttle(source)
        auth.record_failed_login(source)
        auth.check_login_throttle(individual)
        auth.record_failed_login(individual)
    with pytest.raises(HTTPException) as exc:
        auth.check_login_throttle(individual)
    assert exc.value.status_code == 429
    auth.check_login_throttle(source)
    for _ in range(55):
        auth.check_login_throttle(source)
        auth.record_failed_login(source)
    with pytest.raises(HTTPException) as exc:
        auth.check_login_throttle(source)
    assert exc.value.status_code == 429
