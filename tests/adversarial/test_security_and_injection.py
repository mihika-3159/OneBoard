import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from apps.api.main import app
from apps.api.core.database import SessionLocal, init_db
from apps.api.models.business import Business, User
from apps.api.models.workflow import WorkflowDefinition, ApprovalRequest, WorkflowRun
from apps.api.core.auth import hash_password, create_access_token
from apps.api.services.workflow_engine import workflow_engine, ToolRegistry
from apps.api.services.integrations.local_files import local_files_adapter

client = TestClient(app)

@pytest.fixture(scope="module")
def setup_tenants():
    init_db()
    db = SessionLocal()
    
    # Clean prior test runs
    db.query(User).filter(User.email.in_(["founder_a@alpha.test", "founder_b@beta.test"])).delete()
    db.query(Business).filter(Business.name.in_(["Tenant Alpha", "Tenant Beta"])).delete()
    biz_a = Business(name="Tenant Alpha", industry="FinTech", current_cash_balance=50000.0)
    db.add(biz_a)
    db.commit()
    db.refresh(biz_a)
    
    user_a = User(
        email="founder_a@alpha.test",
        name="Founder Alpha",
        role="founder",
        business_id=biz_a.id,
        hashed_password=hash_password("secretA123"),
        is_active=True
    )
    db.add(user_a)
    db.commit()
    db.refresh(user_a)
    
    # Create Tenant Beta
    biz_b = Business(name="Tenant Beta", industry="BioTech", current_cash_balance=10000.0)
    db.add(biz_b)
    db.commit()
    db.refresh(biz_b)
    
    user_b = User(
        email="founder_b@beta.test",
        name="Founder Beta",
        role="founder",
        business_id=biz_b.id,
        hashed_password=hash_password("secretB123"),
        is_active=True
    )
    db.add(user_b)
    db.commit()
    db.refresh(user_b)
    
    token_a = create_access_token(user_id=user_a.id, business_id=biz_a.id)
    token_b = create_access_token(user_id=user_b.id, business_id=biz_b.id)
    
    yield {
        "db": db,
        "biz_a": biz_a,
        "biz_b": biz_b,
        "user_a": user_a,
        "user_b": user_b,
        "token_a": token_a,
        "token_b": token_b
    }
    db.close()

def test_unauthorized_token_rejection():
    """Attempt API call with forged/tampered bearer token."""
    res = client.get("/api/business", headers={"Authorization": "Bearer invalid.tampered.token"})
    assert res.status_code == 401
    assert "Invalid or expired token" in res.json().get("detail", "")

def test_cross_tenant_isolation_read(setup_tenants):
    """User A should only see Tenant Alpha's metrics, not Tenant Beta's."""
    token_a = setup_tenants["token_a"]
    token_b = setup_tenants["token_b"]
    
    res_a = client.get("/api/business", headers={"Authorization": f"Bearer {token_a}"})
    assert res_a.status_code == 200
    assert res_a.json()["id"] == setup_tenants["biz_a"].id
    assert res_a.json()["name"] == "Tenant Alpha"
    
    res_b = client.get("/api/business", headers={"Authorization": f"Bearer {token_b}"})
    assert res_b.status_code == 200
    assert res_b.json()["id"] == setup_tenants["biz_b"].id
    assert res_b.json()["name"] == "Tenant Beta"

def test_cross_tenant_approval_tamper_prevention(setup_tenants):
    """User A cannot approve a workflow run belonging to Tenant Beta."""
    db = setup_tenants["db"]
    biz_b = setup_tenants["biz_b"]
    token_a = setup_tenants["token_a"]
    
    # Create workflow and approval belonging to Beta
    wf_b = WorkflowDefinition(
        business_id=biz_b.id,
        name="Beta Secret Workflow",
        nodes=[{"id": "n1", "type": "approval", "data": {"label": "Beta Wire Transfer"}}],
        edges=[]
    )
    db.add(wf_b)
    db.commit()
    
    run_b = WorkflowRun(
        business_id=biz_b.id,
        workflow_id=wf_b.id,
        workflow_name=wf_b.name,
        status="awaiting_approval"
    )
    db.add(run_b)
    db.commit()
    
    req_b = ApprovalRequest(
        business_id=biz_b.id,
        workflow_run_id=run_b.id,
        action_type="workflow_step_approval",
        title="Unauthorized Action Attempt",
        description="Attempt to approve another tenant's action"
    )
    db.add(req_b)
    db.commit()
    
    # User A tries to approve Beta's request
    res = client.post(
        f"/api/workflows/approvals/{req_b.id}/action",
        json={"action": "approve"},
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert res.status_code == 403
    assert "Forbidden" in res.json().get("detail", "")

def test_oversized_file_upload_rejection(setup_tenants):
    """Attempting upload exceeding 10MB quota must be rejected with 413."""
    token_a = setup_tenants["token_a"]
    oversized_data = b"0" * (11 * 1024 * 1024)  # 11 MB
    files = {"file": ("massive_dump.txt", oversized_data, "text/plain")}
    
    res = client.post(
        "/api/memory/upload",
        files=files,
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert res.status_code == 413
    assert "maximum allowed limit" in res.json().get("detail", "")

def test_disallowed_extension_upload_rejection(setup_tenants):
    """Executable or shell scripts must be strictly rejected."""
    token_a = setup_tenants["token_a"]
    files = {"file": ("malicious.exe", b"MZ_binary_executable_data", "application/x-msdownload")}
    
    res = client.post(
        "/api/memory/upload",
        files=files,
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert res.status_code == 400
    assert "not permitted" in res.json().get("detail", "")

def test_path_traversal_sanitization():
    """Attempting directory traversal in filename is sanitized to pure basename."""
    malicious_filename = "../../../../etc/passwd"
    extracted = local_files_adapter.extract_text(b"sample data", malicious_filename)
    assert extracted["text"] == "sample data"
    assert extracted["metadata"]["filename"] == "passwd"

def test_duplicate_node_id_in_workflow_rejected():
    """Workflow with duplicate node IDs must be rejected by DAG validator."""
    invalid_wf = {
        "nodes": [
            {"id": "duplicate_id", "type": "trigger"},
            {"id": "duplicate_id", "type": "action"}
        ],
        "edges": []
    }
    validation = workflow_engine.validate_workflow(invalid_wf)
    assert validation["is_valid"] is False
    assert "Duplicate node ID" in validation["error"]

def test_unsupported_node_type_rejected():
    """Workflow with arbitrary unauthorized node types must be rejected."""
    invalid_wf = {
        "nodes": [{"id": "n1", "type": "unauthorized_arbitrary_shell_exec"}],
        "edges": []
    }
    validation = workflow_engine.validate_workflow(invalid_wf)
    assert validation["is_valid"] is False
    assert "Unsupported node type" in validation["error"]

def test_self_cycle_rejected():
    """Workflow containing a self-referential edge must be detected immediately."""
    invalid_wf = {
        "nodes": [{"id": "n1", "type": "action"}],
        "edges": [{"source": "n1", "target": "n1"}]
    }
    validation = workflow_engine.validate_workflow(invalid_wf)
    assert validation["is_valid"] is False
    assert "cycle" in validation["error"].lower()
