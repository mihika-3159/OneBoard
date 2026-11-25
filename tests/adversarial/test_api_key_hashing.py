"""API credentials must never authenticate from leaked database verifiers.

Production stores SHA-256 verifiers of strong random API keys, not plaintext
bearer credentials. A migrated/rotated key must work only in its raw form;
the stored digest is not itself an authenticating credential.
"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from apps.api.core import auth
from apps.api.core.database import SessionLocal, init_db
from apps.api.models.business import Business, BusinessMembership, User
from apps.api.routers.auth_router import regenerate_api_key_endpoint


def _request(api_key):
    return Request({
        "type": "http", "method": "GET", "path": "/api/auth/me",
        "headers": [(b"x-api-key", api_key.encode("utf-8"))],
        "scheme": "https", "server": ("api.example.test", 443),
        "query_string": b"",
    })


@pytest.fixture
def api_key_account():
    init_db()
    db = SessionLocal()
    uid = str(uuid4())
    business_id = str(uuid4())
    raw = auth.generate_api_key()
    business = Business(id=business_id, name=f"API key fixture {uid}", owner_id=uid)
    user = User(
        id=uid,
        email=f"key-{uid}@example.invalid",
        name="Synthetic owner",
        business_id=business_id,
        role="founder",
        hashed_password="synthetic",
        api_key=auth.hash_api_key(raw),
        is_active=True,
    )
    db.add(business)
    db.add(user)
    db.flush()
    db.add(BusinessMembership(user_id=uid, business_id=business_id, role="owner"))
    db.commit()
    try:
        yield db, user, raw
    finally:
        db.rollback()
        db.query(BusinessMembership).filter(
            BusinessMembership.user_id == uid
        ).delete()
        db.query(User).filter(User.id == uid).delete()
        db.query(Business).filter(Business.id == business_id).delete()
        db.commit()
        db.close()


def test_new_api_keys_are_unpredictable_and_verifiers_are_one_way():
    first = auth.generate_api_key()
    second = auth.generate_api_key()
    assert first != second
    assert auth._valid_api_key_format(first)
    assert auth._valid_api_key_format(second)
    verifier = auth.hash_api_key(first)
    assert verifier.startswith("sha256:")
    assert len(verifier) == 71
    assert first not in verifier
    assert verifier != auth.hash_api_key(second)


def test_production_auth_accepts_raw_key_not_stored_verifier(
    api_key_account, monkeypatch
):
    db, user, raw = api_key_account
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)
    assert auth.get_current_user(_request(raw), None, db).id == user.id
    db.refresh(user)
    assert user.api_key == auth.hash_api_key(raw)
    assert not user.api_key.startswith("obk_")
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(_request(user.api_key), None, db)
    assert exc.value.status_code == 401


def test_rotation_invalidates_old_key_and_returns_new_raw_key_only(
    api_key_account, monkeypatch
):
    db, user, raw = api_key_account
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)
    result = regenerate_api_key_endpoint(current_user=user, db=db)
    replacement = result["api_key"]
    assert auth._valid_api_key_format(replacement)
    assert replacement != raw
    db.refresh(user)
    assert user.api_key == auth.hash_api_key(replacement)
    assert user.api_key != replacement
    assert auth.get_current_user(_request(replacement), None, db).id == user.id
    for invalid in (raw, user.api_key):
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(_request(invalid), None, db)
        assert exc.value.status_code == 401


@pytest.mark.parametrize("invalid", [
    "obk_fake",
    "obk_" + ("a" * 55),
    "obk_" + ("g" * 56),
    "sha256:" + ("a" * 64),
    "obk_" + ("a" * 5000),
])
def test_invalid_api_key_format_fails_before_production_database_query(
    invalid, monkeypatch
):
    from unittest.mock import Mock

    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)
    db = Mock()
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(_request(invalid), None, db)
    assert exc.value.status_code == 401
    db.query.assert_not_called()


def test_development_only_legacy_api_key_is_not_authorized_in_production(
    api_key_account, monkeypatch
):
    db, user, raw = api_key_account
    user.api_key = raw  # Simulate older dev/production plaintext record.
    db.commit()
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(_request(raw), None, db)
    assert exc.value.status_code == 401
    # Development-only fallback remains for local seeded non-production data.
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", False)
    assert auth.get_current_user(_request(raw), None, db).id == user.id
