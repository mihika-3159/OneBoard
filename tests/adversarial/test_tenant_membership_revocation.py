"""Active-tenant and membership-revocation regression tests.

A valid extra workspace membership must not authorize a resource in an
unselected tenant. A removed workspace membership must invalidate existing
bearer sessions and API keys in production even if both credentials are
cryptographically valid.
"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from starlette.requests import Request

from apps.api.core import auth
from apps.api.core.database import SessionLocal, init_db
from apps.api.models.business import (
    Business, BusinessMembership, User, UserSession,
)


@pytest.fixture
def multiple_memberships():
    init_db()
    db: Session = SessionLocal()
    suffix = uuid4().hex
    primary = Business(id=str(uuid4()), name=f"Primary {suffix}")
    secondary = Business(id=str(uuid4()), name=f"Secondary {suffix}")
    db.add_all([primary, secondary])
    db.flush()
    founder = User(
        id=str(uuid4()),
        email=f"multi-{suffix}@example.invalid",
        name="Multi-business user",
        role="founder",
        business_id=primary.id,
        hashed_password="synthetic-no-password",
        api_key=f"obk_{uuid4().hex}{uuid4().hex[:16]}",
        is_active=True,
    )
    db.add(founder)
    db.flush()
    first = BusinessMembership(user_id=founder.id, business_id=primary.id, role="founder")
    other = BusinessMembership(user_id=founder.id, business_id=secondary.id, role="member")
    session = UserSession(
        id=uuid4().hex,
        user_id=founder.id,
        business_id=primary.id,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        is_revoked=False,
    )
    db.add_all([first, other, session])
    db.commit()
    token = auth.create_access_token(founder.id, primary.id, role="founder", jti=session.id)
    try:
        yield db, founder, primary, secondary, first, other, token
    finally:
        db.rollback()
        db.query(UserSession).filter(UserSession.id == session.id).delete()
        db.query(BusinessMembership).filter(BusinessMembership.user_id == founder.id).delete()
        db.query(User).filter(User.id == founder.id).delete()
        db.query(Business).filter(Business.id.in_([primary.id, secondary.id])).delete()
        db.commit()
        db.close()


def _request(api_key=None):
    headers = [(b"x-api-key", api_key.encode())] if api_key else []
    return Request({
        "type": "http", "method": "GET", "path": "/api/auth/me",
        "headers": headers, "scheme": "https",
        "server": ("oneboard.test", 443), "query_string": b"",
    })


def test_secondary_membership_cannot_widen_active_tenant_access(multiple_memberships):
    db, user, primary, secondary, _, _, _ = multiple_memberships
    auth.enforce_tenant_boundary(primary.id, user, db)
    with pytest.raises(HTTPException) as exc:
        auth.enforce_tenant_boundary(secondary.id, user, db)
    assert exc.value.status_code == 403


def test_removed_primary_membership_revokes_existing_signed_session_and_api_key(
    multiple_memberships, monkeypatch
):
    db, user, primary, secondary, first, _, token = multiple_memberships
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)

    signed = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert auth.get_current_user(_request(), signed, db).id == user.id
    assert auth.get_current_user(_request(api_key=user.api_key), None, db).id == user.id

    # Secondary membership remains. It must not rescue access to the primary.
    db.delete(first)
    db.commit()
    for req, bearer in ((_request(), signed), (_request(api_key=user.api_key), None)):
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(req, bearer, db)
        assert exc.value.status_code == 401

    # Reactivating a matching membership restores legitimate credentials.
    db.add(BusinessMembership(user_id=user.id, business_id=primary.id, role="member"))
    db.commit()
    assert auth.get_current_user(_request(), signed, db).id == user.id
    assert auth.get_current_user(_request(api_key=user.api_key), None, db).id == user.id


def test_business_owner_remains_authorized_without_membership_row(
    multiple_memberships, monkeypatch
):
    db, user, primary, _, first, _, token = multiple_memberships
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)
    primary.owner_id = user.id
    db.delete(first)
    db.commit()
    signed = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert auth.get_current_user(_request(), signed, db).id == user.id


def test_inactive_identity_stays_denied_even_with_membership(
    multiple_memberships, monkeypatch
):
    db, user, _, _, _, _, token = multiple_memberships
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)
    user.is_active = False
    db.commit()
    signed = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    for req, bearer in ((_request(), signed), (_request(api_key=user.api_key), None)):
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(req, bearer, db)
        assert exc.value.status_code == 401


def test_member_role_demotion_revokes_privileged_mutations_without_revoking_reads(
    multiple_memberships, monkeypatch
):
    db, user, primary, _, membership, _, token = multiple_memberships
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)
    signed = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    # A valid founder membership permits writes.
    assert auth.require_founder_role(current_user=user, db=db).id == user.id

    # Demoting the live membership invalidates founder-only authority even
    # though User.role and the HMAC-signed role claim still say "founder".
    membership.role = "member"
    db.commit()
    assert auth.get_current_user(_request(), signed, db).id == user.id
    assert auth.get_current_user(_request(api_key=user.api_key), None, db).id == user.id
    with pytest.raises(HTTPException) as exc:
        auth.require_founder_role(current_user=user, db=db)
    assert exc.value.status_code == 403

    # Live owner authority is distinct from an ordinary membership.
    primary.owner_id = user.id
    db.commit()
    assert auth.require_founder_role(current_user=user, db=db).id == user.id


def test_revoked_membership_cannot_log_in_and_mint_a_fresh_session(
    multiple_memberships, monkeypatch
):
    from fastapi import Response
    from apps.api.routers import auth_router

    db, user, _, _, first, _, _ = multiple_memberships
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", True)
    # Isolate membership authorization from Argon2: simulate an already
    # verified valid password and confirm that authorization still fails.
    monkeypatch.setattr(auth_router, "verify_password", lambda password, hashed: True)

    db.delete(first)
    db.commit()
    before = db.query(UserSession).filter(UserSession.user_id == user.id).count()
    request = Request({
        "type": "http", "method": "POST", "path": "/api/auth/login",
        "headers": [], "scheme": "https",
        "client": ("198.51.100.99", 43210),
        "server": ("oneboard.test", 443), "query_string": b"",
    })
    with pytest.raises(HTTPException) as exc:
        auth_router.login(
            auth_router.LoginRequest(email=user.email, password="correct-synthetic-pass"),
            Response(), request, db,
        )
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid email or password."
    assert db.query(UserSession).filter(UserSession.user_id == user.id).count() == before
