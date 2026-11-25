"""Runtime security matrix: anonymous API access and foreign tenant resource IDs."""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.core import auth
from apps.api.core.config import settings
from apps.api.core.database import SessionLocal, init_db
from apps.api.core.auth import create_access_token
from apps.api.models.business import Business, User, UserSession
from apps.api.models.workflow import WorkflowDefinition, WorkflowRun, ApprovalRequest, CustomAgent
from apps.api.models.integrations import IntegrationAccount
from apps.api.routers.business_router import reset_demo


@pytest.mark.parametrize("path", [
    "/api/business",
    "/api/business/metrics",
    "/api/council/meetings",
    "/api/memory/graph",
    "/api/memory/conflicts",
    "/api/workflows",
    "/api/workflows/runs",
    "/api/workflows/approvals",
    "/api/agents",
    "/api/accountability/decisions",
    "/api/accountability/scorecards",
    "/api/integrations",
    "/api/alerts",
    "/api/ai/status",
    "/api/auth/me",
    "/api/data/export",
    "/api/data/retention",
    "/api/diagnostics/operations",
])
def test_anonymous_business_api_reads_require_authentication(monkeypatch, path):
    monkeypatch.setattr(auth, "_DEMO_MODE", False)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(path)
    assert response.status_code == 401, (path, response.status_code, response.text[:250])


def test_production_cannot_reset_demo_even_if_demo_flag_is_set(monkeypatch):
    """Defense in depth if production flags conflict outside lifespan validation."""
    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
    monkeypatch.setattr(settings, "ONEBOARD_DEMO_MODE", True)
    user = type("UserStub", (), {"business_id": "demo-business", "role": "founder"})()
    with pytest.raises(HTTPException) as exc:
        reset_demo(current_user=user, db=None)
    assert exc.value.status_code == 403


@pytest.fixture(scope="module")
def protected_foreign_resources():
    init_db()
    db = SessionLocal()
    try:
        left = Business(name=f"Isolation A {uuid4()}", industry="SaaS")
        right = Business(name=f"Isolation B {uuid4()}", industry="SaaS")
        db.add_all([left, right])
        db.flush()
        uid = str(uuid4())
        owner = User(id=uid, email=f"left-{uid}@example.test", name="Left Founder",
                     hashed_password="not-used", business_id=left.id, role="founder", is_active=True)
        db.add(owner)
        db.flush()
        sid = str(uuid4())
        db.add(UserSession(id=sid, user_id=owner.id, business_id=left.id,
                           expires_at=datetime.utcnow() + timedelta(hours=1), is_revoked=False))
        wf = WorkflowDefinition(
            business_id=right.id, name="Private B workflow",
            nodes=[{"id": "trigger", "type": "trigger"}], edges=[], is_valid=True
        )
        agent = CustomAgent(
            business_id=right.id, name="Private B agent", role_title="Ops",
            department="Operations", system_prompt="Do not expose."
        )
        integration = IntegrationAccount(
            business_id=right.id, connector_type="demo_crm", name="Private B CRM",
            status="sandbox_ready", is_mock=True,
        )
        db.add_all([wf, agent, integration])
        db.flush()
        run = WorkflowRun(
            business_id=right.id, workflow_id=wf.id,
            workflow_name=wf.name, status="awaiting_approval"
        )
        db.add(run)
        db.flush()
        approval = ApprovalRequest(
            business_id=right.id, workflow_run_id=run.id, action_type="send_email",
            title="B private approval", description="Private", status="pending",
        )
        db.add(approval)
        db.commit()
        yield {
            "token": create_access_token(user_id=owner.id, business_id=left.id, jti=sid),
            "workflow": wf.id, "agent": agent.id,
            "integration": integration.id, "approval": approval.id,
        }
    finally:
        db.close()


@pytest.mark.parametrize("method,path_key,payload", [
    ("POST", "workflow", None),
    ("POST", "agent", {"test_input": "ping"}),
    ("POST", "integration", None),
    ("POST", "approval", {"action": "approve"}),
])
def test_foreign_tenant_mutations_are_denied_before_execution(
    protected_foreign_resources, monkeypatch, method, path_key, payload
):
    f = protected_foreign_resources
    paths = {
        "workflow": f"/api/workflows/{f['workflow']}/execute",
        "agent": f"/api/agents/{f['agent']}/test",
        "integration": f"/api/integrations/{f['integration']}/sync",
        "approval": f"/api/workflows/approvals/{f['approval']}/action",
    }
    monkeypatch.setattr(auth, "_DEMO_MODE", False)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, paths[path_key],
                                  headers={"Authorization": f"Bearer {f['token']}"},
                                  json=payload)
    assert response.status_code in (403, 404), (path_key, response.status_code, response.text[:250])
