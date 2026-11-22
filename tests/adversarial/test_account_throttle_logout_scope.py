"""Regression tests for account-wide throttling and session revocation scope."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from apps.api.routers import auth_router


def _request(ip="198.51.100.7", headers=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/api/auth/login",
                    "headers": raw, "client": (ip, 12345), "scheme": "https",
                    "server": ("example.test", 443), "query_string": b""})


@pytest.mark.parametrize("ip", ["198.51.100.7", "203.0.113.22", "192.0.2.8"])
def test_failed_login_uses_same_account_throttle_across_source_ips(monkeypatch, ip):
    checked, failed = [], []
    monkeypatch.setattr(auth_router, "check_login_throttle", lambda key, db: checked.append(key))
    monkeypatch.setattr(auth_router, "record_failed_login", lambda key, db: failed.append(key))
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    req = auth_router.LoginRequest(email="  Founder@Example.test ", password="wrong")
    with pytest.raises(HTTPException) as exc:
        auth_router.login(req, Response(), _request(ip), db)
    assert exc.value.status_code == 401
    assert checked == failed == ["account:founder@example.test"]


@pytest.mark.parametrize("session_user,session_tenant,expected_revoked", [
    ("victim", "tenant-a", False),
    ("attacker", "tenant-b", False),
    ("attacker", "tenant-a", True),
])
def test_logout_only_revokes_session_owned_by_signed_identity(
    monkeypatch, session_user, session_tenant, expected_revoked
):
    session = SimpleNamespace(id="target", user_id=session_user,
                              business_id=session_tenant, is_revoked=False)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = session
    monkeypatch.setattr(auth_router, "decode_access_token", lambda token: {
        "jti": "target", "sub": "attacker", "biz": "tenant-a"
    })
    response = Response()
    auth_router.logout(_request(headers={"authorization": "Bearer signed-token"}), response, db)
    assert session.is_revoked is expected_revoked
    assert db.commit.call_count == int(expected_revoked)
