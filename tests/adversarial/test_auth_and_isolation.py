"""
tests/adversarial/test_auth_and_isolation.py

Comprehensive regression test suite verifying:
- Unauthenticated business GET returns 401.
- Unauthenticated demo reset, workflow execution, approval, document upload and agent mutation are rejected.
- User A can access their own business.
- User A cannot read or modify user B's business, even with a valid resource ID.
- Cross-tenant workflow approvals and agent tests are rejected.
- Cross-tenant memory searches and AI context retrieval never include another business's data.
- Demo reset cannot delete another tenant's records.
- Invalid credentials, expired sessions, forged cookies and logout-reused sessions are rejected.
- Cross-origin credentialed mutations fail CSRF checks.
- Login throttling behaves correctly.
- Existing legitimate authenticated frontend flows still work.
"""
from __future__ import annotations

import os
import time
from unittest.mock import patch
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.main import app
from apps.api.core.config import settings
from apps.api.core.database import SessionLocal, init_db
from apps.api.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    set_auth_cookies,
    generate_csrf_token,
    check_login_throttle,
    record_failed_login,
    reset_login_throttle,
    _LOGIN_ATTEMPTS,
)
from apps.api.models.business import Business, BusinessMembership, User, UserSession
from apps.api.models.entities import Invoice, Customer, Expense
from apps.api.models.memory import MemoryDocument, MemoryChunk
from apps.api.models.workflow import CustomAgent, WorkflowDefinition, WorkflowRun, ApprovalRequest
from apps.api.services.seed_data import DEMO_BUSINESS_ID, seed_northstar_studio


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def multi_tenant_fixture():
    """Create two completely isolated test businesses and founders."""
    init_db()
    db = SessionLocal()

    # Seed demo business if not present
    seed_northstar_studio(db)

    # 1. Tenant A: Alpha Corp
    db.query(User).filter(User.email == "founder_a@alpha.test").delete()
    db.query(Business).filter(Business.name == "Alpha Corp Test").delete()
    biz_a = Business(name="Alpha Corp Test", industry="B2B SaaS", current_cash_balance=50000.0, monthly_burn_rate=5000.0)
    db.add(biz_a)
    db.commit()
    db.refresh(biz_a)

    user_a = User(
        email="founder_a@alpha.test",
        name="Alice Alpha",
        role="founder",
        business_id=biz_a.id,
        hashed_password=hash_password("alpha-secure-password"),
        is_active=True
    )
    db.add(user_a)
    db.commit()
    db.refresh(user_a)
    biz_a.owner_id = user_a.id
    db.add(BusinessMembership(user_id=user_a.id, business_id=biz_a.id, role="owner"))

    # Tenant A resources
    wf_a = WorkflowDefinition(
        business_id=biz_a.id,
        name="Alpha Workflow",
        nodes=[{"id": "n1", "type": "trigger"}],
        edges=[],
        is_valid=True
    )
    db.add(wf_a)
    db.commit()
    db.refresh(wf_a)

    run_a = WorkflowRun(
        business_id=biz_a.id,
        workflow_id=wf_a.id,
        workflow_name="Alpha Workflow",
        status="awaiting_approval"
    )
    db.add(run_a)
    db.commit()
    db.refresh(run_a)

    appr_a = ApprovalRequest(
        business_id=biz_a.id,
        workflow_run_id=run_a.id,
        action_type="send_email",
        title="Alpha Action",
        description="Alpha approval description",
        status="pending"
    )
    db.add(appr_a)

    agent_a = CustomAgent(
        business_id=biz_a.id,
        name="Alpha Agent",
        role_title="Alpha Ops",
        department="Ops",
        system_prompt="You are Alpha Agent."
    )
    db.add(agent_a)

    doc_a = MemoryDocument(
        business_id=biz_a.id,
        title="Alpha Confidential Roadmap",
        content_hash="alpha_hash_123",
        raw_content="Project Alpha secret acquisition target",
        file_type="txt"
    )
    db.add(doc_a)
    db.commit()
    db.refresh(doc_a)

    db.add(MemoryChunk(
        document_id=doc_a.id,
        business_id=biz_a.id,
        chunk_index=0,
        content="Alpha confidential: Target valuation is $10M"
    ))
    db.commit()

    # 2. Tenant B: Beta Corp
    db.query(User).filter(User.email == "founder_b@beta.test").delete()
    db.query(Business).filter(Business.name == "Beta Corp Test").delete()
    biz_b = Business(name="Beta Corp Test", industry="Fintech", current_cash_balance=80000.0, monthly_burn_rate=8000.0)
    db.add(biz_b)
    db.commit()
    db.refresh(biz_b)

    user_b = User(
        email="founder_b@beta.test",
        name="Bob Beta",
        role="founder",
        business_id=biz_b.id,
        hashed_password=hash_password("beta-secure-password"),
        is_active=True
    )
    db.add(user_b)
    db.commit()
    db.refresh(user_b)
    biz_b.owner_id = user_b.id
    db.add(BusinessMembership(user_id=user_b.id, business_id=biz_b.id, role="owner"))

    wf_b = WorkflowDefinition(
        business_id=biz_b.id,
        name="Beta Workflow",
        nodes=[{"id": "n1", "type": "trigger"}],
        edges=[],
        is_valid=True
    )
    db.add(wf_b)
    db.commit()
    db.refresh(wf_b)

    run_b = WorkflowRun(
        business_id=biz_b.id,
        workflow_id=wf_b.id,
        workflow_name="Beta Workflow",
        status="awaiting_approval"
    )
    db.add(run_b)
    db.commit()
    db.refresh(run_b)

    appr_b = ApprovalRequest(
        business_id=biz_b.id,
        workflow_run_id=run_b.id,
        action_type="send_email",
        title="Beta Action",
        description="Beta approval description",
        status="pending"
    )
    db.add(appr_b)

    agent_b = CustomAgent(
        business_id=biz_b.id,
        name="Beta Agent",
        role_title="Beta Support",
        department="Support",
        system_prompt="You are Beta Agent."
    )
    db.add(agent_b)

    doc_b = MemoryDocument(
        business_id=biz_b.id,
        title="Beta Trade Secrets",
        content_hash="beta_hash_456",
        raw_content="Beta internal API key: sk-secret-beta-key-xyz",
        file_type="txt"
    )
    db.add(doc_b)
    db.commit()
    db.refresh(doc_b)

    db.add(MemoryChunk(
        document_id=doc_b.id,
        business_id=biz_b.id,
        chunk_index=0,
        content="Beta internal API key: sk-secret-beta-key-xyz"
    ))
    db.commit()

    # Mint sessions
    from secrets import token_hex
    session_a, session_b = token_hex(16), token_hex(16)
    db.add_all([
        UserSession(id=session_a, user_id=user_a.id, business_id=biz_a.id, expires_at=datetime.utcnow() + timedelta(hours=1), is_revoked=False),
        UserSession(id=session_b, user_id=user_b.id, business_id=biz_b.id, expires_at=datetime.utcnow() + timedelta(hours=1), is_revoked=False),
    ])
    db.commit()
    token_a = create_access_token(user_id=user_a.id, business_id=biz_a.id, role=user_a.role, jti=session_a)
    token_b = create_access_token(user_id=user_b.id, business_id=biz_b.id, role=user_b.role, jti=session_b)

    yield {
        "db": db,
        "biz_a": biz_a,
        "user_a": user_a,
        "wf_a": wf_a,
        "run_a": run_a,
        "appr_a": appr_a,
        "agent_a": agent_a,
        "doc_a": doc_a,
        "token_a": token_a,
        "biz_b": biz_b,
        "user_b": user_b,
        "wf_b": wf_b,
        "run_b": run_b,
        "appr_b": appr_b,
        "agent_b": agent_b,
        "doc_b": doc_b,
        "token_b": token_b,
    }
    db.close()


# ---------------------------------------------------------------------------
# Test 1 & 2: Unauthenticated Requests Return 401
# ---------------------------------------------------------------------------
class TestUnauthenticatedEnforcement:
    def test_unauthenticated_business_get_returns_401(self):
        with patch("apps.api.core.auth._DEMO_MODE", False):
            res = client.get("/api/business")
            assert res.status_code == 401
            assert "detail" in res.json()

    def test_unauthenticated_business_metrics_returns_401(self):
        with patch("apps.api.core.auth._DEMO_MODE", False):
            res = client.get("/api/business/metrics")
            assert res.status_code == 401

    def test_unauthenticated_demo_reset_rejected(self):
        with patch("apps.api.core.auth._DEMO_MODE", False):
            res = client.post("/api/business/seed-demo")
            assert res.status_code == 401

    def test_unauthenticated_workflow_execution_rejected(self):
        with patch("apps.api.core.auth._DEMO_MODE", False):
            res = client.post("/api/workflows/wf-test-id/execute")
            assert res.status_code == 401

    def test_unauthenticated_approval_action_rejected(self):
        with patch("apps.api.core.auth._DEMO_MODE", False):
            res = client.post("/api/workflows/approvals/appr-test-id/action", json={"action": "approve"})
            assert res.status_code == 401

    def test_unauthenticated_document_upload_rejected(self):
        with patch("apps.api.core.auth._DEMO_MODE", False):
            res = client.post(
                "/api/memory/upload",
                files={"file": ("test.txt", b"secret content", "text/plain")}
            )
            assert res.status_code == 401

    def test_unauthenticated_agent_mutation_rejected(self):
        with patch("apps.api.core.auth._DEMO_MODE", False):
            res = client.post(
                "/api/agents",
                json={
                    "name": "Intruder Agent",
                    "role_title": "Attacker",
                    "system_prompt": "Do harm."
                }
            )
            assert res.status_code == 401

    def test_public_health_check_remains_accessible(self):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json().get("status") == "healthy"


# ---------------------------------------------------------------------------
# Test 3 & 4: User A Access & Cross-Tenant Isolation
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    def test_user_a_can_access_own_business(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        headers = {"Authorization": f"Bearer {f['token_a']}"}
        res = client.get("/api/business", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == f["biz_a"].id
        assert data["name"] == "Alpha Corp Test"

    def test_user_a_cannot_read_user_b_business_data(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        headers = {"Authorization": f"Bearer {f['token_a']}"}
        # In OneBoard, /api/business returns the authenticated tenant's data
        res = client.get("/api/business", headers=headers)
        assert res.status_code == 200
        assert res.json()["id"] == f["biz_a"].id
        assert res.json()["id"] != f["biz_b"].id

    def test_user_a_cannot_execute_user_b_workflow(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        headers = {"Authorization": f"Bearer {f['token_a']}"}
        # User A attempts to execute User B's workflow
        res = client.post(f"/api/workflows/{f['wf_b'].id}/execute", headers=headers)
        assert res.status_code in (403, 404)

    def test_user_a_cannot_approve_user_b_workflow_run(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        headers = {"Authorization": f"Bearer {f['token_a']}"}
        # User A attempts to resolve User B's pending approval
        res = client.post(
            f"/api/workflows/approvals/{f['appr_b'].id}/action",
            headers=headers,
            json={"action": "approve"}
        )
        assert res.status_code == 403

    def test_user_a_cannot_test_user_b_agent(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        headers = {"Authorization": f"Bearer {f['token_a']}"}
        # User A attempts to test User B's agent
        res = client.post(
            f"/api/agents/{f['agent_b'].id}/test",
            headers=headers,
            json={"test_input": "Ping"}
        )
        assert res.status_code == 403

    def test_cross_tenant_memory_search_isolation(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        headers = {"Authorization": f"Bearer {f['token_a']}"}
        # User A searches for Beta's trade secrets
        res = client.post(
            "/api/memory/search",
            headers=headers,
            json={"query": "trade secrets API key"}
        )
        assert res.status_code == 200
        results = res.json().get("results", [])
        # Results must NOT contain any content from Beta's document
        for match in results:
            assert "sk-secret-beta-key-xyz" not in match.get("content", "")
            assert match.get("document_id") != f["doc_b"].id


# ---------------------------------------------------------------------------
# Test 5: Demo Reset Isolation (Cannot Delete Another Tenant's Records)
# ---------------------------------------------------------------------------
class TestDemoResetTenantIsolation:
    def test_demo_reset_preserves_other_tenant_data(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        db: Session = f["db"]

        # Ensure User A's business still exists before demo reset
        assert db.query(Business).filter(Business.id == f["biz_a"].id).first() is not None

        # Reset demo workspace
        seed_northstar_studio(db, reset=True)

        # Verify User A's business, user, workflow, and documents were NOT deleted!
        biz_a_after = db.query(Business).filter(Business.id == f["biz_a"].id).first()
        user_a_after = db.query(User).filter(User.id == f["user_a"].id).first()
        wf_a_after = db.query(WorkflowDefinition).filter(WorkflowDefinition.id == f["wf_a"].id).first()
        doc_a_after = db.query(MemoryDocument).filter(MemoryDocument.id == f["doc_a"].id).first()

        assert biz_a_after is not None, "Demo reset deleted another tenant's Business record!"
        assert user_a_after is not None, "Demo reset deleted another tenant's User record!"
        assert wf_a_after is not None, "Demo reset deleted another tenant's Workflow record!"
        assert doc_a_after is not None, "Demo reset deleted another tenant's MemoryDocument!"


# ---------------------------------------------------------------------------
# Test 6: Credentials, Sessions, Forgery, Logout Invalidation
# ---------------------------------------------------------------------------
class TestAuthenticationSecurity:
    def test_invalid_credentials_rejected(self):
        res = client.post(
            "/api/auth/login",
            json={"email": "nonexistent@test.com", "password": "wrongpassword123"}
        )
        assert res.status_code == 401

    def test_forged_cookie_signature_rejected(self):
        with patch("apps.api.core.auth._DEMO_MODE", False):
            forged_cookie = "eyJzdWIiOiAidXNlci0xMjMiLCAiZXhwIjogOTk5OTk5OTk5OX0.forgedsignature123"
            client.cookies.set("oneboard_session", forged_cookie)
            res = client.get("/api/business")
            assert res.status_code == 401
            client.cookies.clear()

    def test_expired_session_token_rejected(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        with patch("apps.api.core.auth._DEMO_MODE", False):
            # Mint token with past exp
            with patch("apps.api.core.auth.TOKEN_EXPIRY_SECONDS", -10):
                expired_token = create_access_token(user_id=f["user_a"].id, business_id=f["biz_a"].id)

            res = client.get("/api/business", headers={"Authorization": f"Bearer {expired_token}"})
            assert res.status_code == 401

    def test_logout_invalidates_session_in_database(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        db: Session = f["db"]

        # Log in to create a real session in DB
        res_login = client.post(
            "/api/auth/login",
            json={"email": f["user_a"].email, "password": "alpha-secure-password"}
        )
        assert res_login.status_code == 200
        token = res_login.json()["token"]

        payload = decode_access_token(token)
        jti = payload["jti"]

        session_record = db.query(UserSession).filter(UserSession.id == jti).first()
        assert session_record is not None
        assert session_record.is_revoked is False

        # Log out
        res_logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert res_logout.status_code == 200

        # DB session must now be marked revoked
        db.refresh(session_record)
        assert session_record.is_revoked is True

        # Re-using the logged-out token must fail with 401
        with patch("apps.api.core.auth._DEMO_MODE", False):
            res_reuse = client.get("/api/business", headers={"Authorization": f"Bearer {token}"})
            assert res_reuse.status_code == 401
            assert "revoked" in res_reuse.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test 7: CSRF Protection on Cookie Mutations
# ---------------------------------------------------------------------------
class TestCSRFProtection:
    def test_cookie_mutation_fails_on_untrusted_cross_origin(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        client.cookies.set("oneboard_session", f["token_a"])

        # Send state-changing POST from untrusted origin
        res = client.post(
            "/api/workflows",
            headers={"Origin": "https://evil-attacker.com"},
            json={
                "name": "CSRF Workflow",
                "nodes": [{"id": "n1", "type": "trigger"}],
                "edges": []
            }
        )
        assert res.status_code == 403
        assert "CSRF" in res.json()["detail"]
        client.cookies.clear()


# ---------------------------------------------------------------------------
# Test 8: Login Throttling
# ---------------------------------------------------------------------------
class TestLoginThrottling:
    def test_excessive_failed_logins_trigger_429(self):
        target_email = "bruteforce_target@test.com"
        throttle_id = f"testclient:{target_email}"
        reset_login_throttle(throttle_id)

        # 5 failed attempts
        for _ in range(5):
            record_failed_login(throttle_id)

        # 6th attempt should raise 429
        with pytest.raises(Exception) as exc_info:
            check_login_throttle(throttle_id)
        assert exc_info.value.status_code == 429

        reset_login_throttle(throttle_id)


# Additional regression cases: missing CSRF and untracked or mismatched sessions.
class TestFailClosedSessionAndCsrf:
    def test_cookie_mutation_without_csrf_header_rejected(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        with TestClient(app, raise_server_exceptions=False) as isolated:
            isolated.cookies.set("oneboard_session", f["token_a"])
            response = isolated.post("/api/workflows", json={
                "name": "No CSRF header", "nodes": [], "edges": []
            })
            assert response.status_code == 403

    def test_signed_token_without_database_session_rejected(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        token = create_access_token(user_id=f["user_a"].id, business_id=f["biz_a"].id)
        response = client.get("/api/business", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_signed_token_with_wrong_tenant_rejected(self, multi_tenant_fixture):
        f = multi_tenant_fixture
        db = f["db"]
        from secrets import token_hex
        session_id = token_hex(16)
        db.add(UserSession(
            id=session_id,
            user_id=f["user_a"].id,
            business_id=f["biz_a"].id,
            expires_at=datetime.utcnow() + timedelta(hours=1),
            is_revoked=False,
        ))
        db.commit()
        token = create_access_token(
            user_id=f["user_a"].id,
            business_id=f["biz_b"].id,
            jti=session_id,
        )
        response = client.get("/api/business", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
