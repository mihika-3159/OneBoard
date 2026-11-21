"""Focused auth transaction and logout CSRF regression tests."""
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import event
from apps.api.main import app
from apps.api.core.database import SessionLocal, init_db
from apps.api.models.business import Business, User, BusinessMembership, UserSession

def test_registration_creates_all_records_in_single_transaction():
    init_db()
    email = f"atomic-{uuid4()}@example.test"
    with TestClient(app, raise_server_exceptions=False) as client:
        res = client.post("/api/auth/register", json={
            "name": "Atomic Founder", "email": email,
            "password": "StrongTestPassword123!", "business_name": "Atomic Workspace",
        })
    assert res.status_code == 201, res.text
    payload = res.json()
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).one()
        assert user.business_id == payload["business"]["id"]
        assert db.query(Business).filter_by(id=user.business_id, owner_id=user.id).count() == 1
        assert db.query(BusinessMembership).filter_by(user_id=user.id, business_id=user.business_id).count() == 1
        assert db.query(UserSession).filter_by(user_id=user.id, business_id=user.business_id).count() == 1
    finally:
        db.close()

def test_failed_registration_commit_rolls_back_business_and_user():
    init_db()
    email = f"rollback-{uuid4()}@example.test"
    workspace = f"Rollback Workspace {uuid4()}"
    # Inject a failure at the DB commit boundary, after flushes, before commit.
    from sqlalchemy.orm import Session
    original_commit = Session.commit
    def fail_commit(self):
        if self.query(User).filter_by(email=email).first() is not None:
            raise RuntimeError("Injected database commit failure")
        return original_commit(self)
    with patch.object(Session, "commit", fail_commit):
        with TestClient(app, raise_server_exceptions=False) as client:
            res = client.post("/api/auth/register", json={
                "name": "Rollback Founder", "email": email,
                "password": "StrongTestPassword123!", "business_name": workspace,
            })
    assert res.status_code == 500
    db = SessionLocal()
    try:
        assert db.query(User).filter_by(email=email).count() == 0
        assert db.query(Business).filter_by(name=workspace).count() == 0
    finally:
        db.close()

def test_cookie_logout_requires_csrf_but_bearer_logout_works():
    init_db()
    email = f"logout-csrf-{uuid4()}@example.test"
    with TestClient(app, raise_server_exceptions=False) as client:
        registered = client.post("/api/auth/register", json={
            "name": "Logout Founder", "email": email,
            "password": "StrongTestPassword123!", "business_name": "Logout Workspace",
        })
        assert registered.status_code == 201, registered.text
        token = registered.json()["token"]
        forbidden = client.post("/api/auth/logout", headers={"Origin": "https://attacker.example"})
        assert forbidden.status_code == 403
        assert client.get("/api/auth/me").status_code == 200
        permitted = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert permitted.status_code == 200
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
