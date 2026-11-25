from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.api.core import auth


def request(origin=None, referer=None):
    headers = {"x-csrf-token": "test-csrf"}
    if origin is not None:
        headers["origin"] = origin
    if referer is not None:
        headers["referer"] = referer
    return SimpleNamespace(
        method="POST",
        cookies={"oneboard_session": "session", "oneboard_csrf": "test-csrf"},
        headers=headers,
    )


@pytest.mark.parametrize("origin,referer", [
    ("https://evil.example", None),
    (None, "https://evil.example/path"),
    (None, "https://app.example.evil/path"),
    (None, "not-a-url"),
])
def test_rejects_cross_site_cookie_mutations(monkeypatch, origin, referer):
    monkeypatch.setattr(auth.settings, "CORS_ORIGINS", "https://app.example")
    with pytest.raises(HTTPException) as exc:
        auth.verify_csrf_protection(request(origin, referer))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("origin,referer", [
    ("https://app.example", None),
    (None, "https://app.example/path?x=1"),
])
def test_accepts_allowlisted_origin_or_referer(monkeypatch, origin, referer):
    monkeypatch.setattr(auth.settings, "CORS_ORIGINS", "https://app.example")
    auth.verify_csrf_protection(request(origin, referer))


def test_production_rejects_missing_origin_evidence(monkeypatch):
    monkeypatch.setattr(auth.settings, "CORS_ORIGINS", "https://app.example")
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)
    with pytest.raises(HTTPException) as exc:
        auth.verify_csrf_protection(request())
    assert exc.value.status_code == 403
