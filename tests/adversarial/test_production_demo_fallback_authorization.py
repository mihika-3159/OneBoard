"""Production authentication must never silently resolve an anonymous demo user.

These tests guard the authorization boundary independently of the signing-key
startup check: a valid configured secret is not permission for demo fallback.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from apps.api.core import auth


def _request():
    return Request({
        "type": "http", "method": "GET", "path": "/api/auth/me",
        "headers": [], "scheme": "https",
        "server": ("oneboard.example", 443), "query_string": b"",
    })


@pytest.mark.parametrize("demo_mode,production_mode,expected", [
    (True, True, 401),
    (False, True, 401),
    (False, False, 401),
    (True, False, 200),
])
def test_anonymous_demo_fallback_only_in_explicit_nonproduction_mode(
    monkeypatch, demo_mode, production_mode, expected
):
    monkeypatch.setattr(auth, "_DEMO_MODE", demo_mode)
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", production_mode)
    demo_user = SimpleNamespace(id="demo-user", business_id="demo-business")
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = demo_user

    if expected == 401:
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(_request(), None, db)
        assert exc.value.status_code == 401
        db.query.assert_not_called()
    else:
        assert auth.get_current_user(_request(), None, db) is demo_user


def test_invalid_api_key_does_not_fall_through_to_demo(monkeypatch):
    monkeypatch.setattr(auth, "_DEMO_MODE", True)
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", False)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    request = Request({
        "type": "http", "method": "GET", "path": "/api/auth/me",
        "headers": [(b"x-api-key", b"invalid")],
        "scheme": "http", "server": ("localhost", 8000), "query_string": b"",
    })
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(request, None, db)
    assert exc.value.status_code == 401
