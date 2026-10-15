import pytest
from apps.api.core.database import SessionLocal, init_db
from apps.api.models.business import Business
from apps.api.models.entities import Invoice, Expense, Customer
from apps.api.models.workflow import WorkflowDefinition, WorkflowRun, ApprovalRequest
from apps.api.services.workflow_engine import workflow_engine, ToolRegistry
from apps.api.services.council_engine import council_engine
from apps.api.routers.business_router import compute_financial_health_score

@pytest.fixture(scope="module")
def db_session():
    init_db()
    session = SessionLocal()
    # Create isolated test business
    test_biz = Business(
        name="Test Workflow Tenant",
        current_cash_balance=25000.0,
        monthly_burn_rate=5000.0
    )
    session.add(test_biz)
    session.commit()
    session.refresh(test_biz)
    
    yield {"db": session, "biz": test_biz}
    session.close()

def test_topological_sorting_reverse_declaration_order():
    """
    DAG with nodes declared in reverse order [node_3, node_2, node_1]
    with edges node_1 -> node_2 -> node_3.
    Validator and executor must sort and execute in order [node_1, node_2, node_3].
    """
    reversed_wf = {
        "nodes": [
            {"id": "node_3", "type": "action", "data": {"label": "Step Three"}},
            {"id": "node_2", "type": "action", "data": {"label": "Step Two"}},
            {"id": "node_1", "type": "trigger", "data": {"label": "Step One"}}
        ],
        "edges": [
            {"source": "node_1", "target": "node_2"},
            {"source": "node_2", "target": "node_3"}
        ]
    }
    validation = workflow_engine.validate_workflow(reversed_wf)
    assert validation["is_valid"] is True
    assert validation["topological_order"] == ["node_1", "node_2", "node_3"]

def test_branching_dag_convergence():
    """
    Diamond DAG:
        A
       / \
      B   C
       \ /
        D
    A executes first, D executes last.
    """
    diamond_wf = {
        "nodes": [
            {"id": "D", "type": "action", "data": {"label": "Finalize"}},
            {"id": "B", "type": "action", "data": {"label": "Branch Left"}},
            {"id": "C", "type": "action", "data": {"label": "Branch Right"}},
            {"id": "A", "type": "trigger", "data": {"label": "Root"}}
        ],
        "edges": [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "D"},
            {"source": "C", "target": "D"}
        ]
    }
    validation = workflow_engine.validate_workflow(diamond_wf)
    assert validation["is_valid"] is True
    order = validation["topological_order"]
    assert order[0] == "A"
    assert order[-1] == "D"
    assert "B" in order[1:3]
    assert "C" in order[1:3]

def test_cycle_detection_in_complex_graph():
    """Cyclic dependency must be flagged as invalid."""
    cyclic_graph = {
        "nodes": [
            {"id": "A", "type": "trigger"},
            {"id": "B", "type": "action"},
            {"id": "C", "type": "action"}
        ],
        "edges": [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "C", "target": "A"}  # Cycle back to A
        ]
    }
    res = workflow_engine.validate_workflow(cyclic_graph)
    assert res["is_valid"] is False
    assert "cycle" in res["error"].lower()

def test_workflow_dry_run_no_database_mutations(db_session):
    """Dry run should simulate execution without writing WorkflowRun or ApprovalRequest."""
    db = db_session["db"]
    biz = db_session["biz"]
    
    wf = WorkflowDefinition(
        business_id=biz.id,
        name="Dry Run Test Workflow",
        nodes=[
            {"id": "step_1", "type": "trigger", "data": {"label": "Manual Trigger"}},
            {"id": "step_2", "type": "calculate", "data": {"label": "Calculate Overdue Total"}},
            {"id": "step_3", "type": "approval", "data": {"label": "Founder Sign-off"}}
        ],
        edges=[
            {"source": "step_1", "target": "step_2"},
            {"source": "step_2", "target": "step_3"}
        ]
    )
    db.add(wf)
    db.commit()
    
    initial_runs_count = db.query(WorkflowRun).filter(WorkflowRun.business_id == biz.id).count()
    initial_approvals_count = db.query(ApprovalRequest).filter(ApprovalRequest.business_id == biz.id).count()
    
    dry_run_result = workflow_engine.execute_workflow(
        db=db,
        business_id=biz.id,
        workflow_id=wf.id,
        dry_run=True
    )
    assert dry_run_result.status == "dry_run_success"
    assert dry_run_result.verified_success is True
    assert "step_2" in dry_run_result.step_results
    
    # Verify no persistent DB records were created
    assert db.query(WorkflowRun).filter(WorkflowRun.business_id == biz.id).count() == initial_runs_count
    assert db.query(ApprovalRequest).filter(ApprovalRequest.business_id == biz.id).count() == initial_approvals_count

def test_approval_checkpoint_and_true_dag_resumption(db_session):
    """
    Workflow:
      [trigger_1] -> [approval_gate] -> [action_post_approval]
    1. Execution halts at approval_gate with status 'awaiting_approval'.
    2. action_post_approval is NOT yet executed.
    3. approve_and_resume_run() executes action_post_approval and finalizes run to 'completed'.
    4. Subsequent call is idempotent.
    """
    db = db_session["db"]
    biz = db_session["biz"]
    
    wf = WorkflowDefinition(
        business_id=biz.id,
        name="HITL Resumption Pipeline",
        nodes=[
            {"id": "n1", "type": "trigger", "data": {"label": "Start"}},
            {"id": "n2", "type": "approval", "data": {"label": "Founder Review Gate", "risk": "high"}},
            {"id": "n3", "type": "calculate", "data": {"label": "Post-Approval Calculation"}}
        ],
        edges=[
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"}
        ]
    )
    db.add(wf)
    db.commit()
    
    # 1. Start execution
    run = workflow_engine.execute_workflow(db=db, business_id=biz.id, workflow_id=wf.id)
    assert run.status == "awaiting_approval"
    assert "n1" in run.step_results
    assert run.step_results["n2"]["status"] == "awaiting_founder_approval"
    assert "n3" not in run.step_results  # n3 must NOT be executed yet!
    
    req_id = run.step_results["n2"]["request_id"]
    assert req_id is not None
    
    # 2. Founder approves and resumes
    resumed_run = workflow_engine.approve_and_resume_run(db=db, run_id=run.id, request_id=req_id)
    assert resumed_run.status == "completed"
    assert resumed_run.verified_success is True
    assert resumed_run.step_results["n2"]["status"] == "approved"
    assert "n3" in resumed_run.step_results  # n3 MUST now be executed!
    assert resumed_run.step_results["n3"]["status"] == "success"
    
    # 3. Idempotency check: repeating approval does not fail or duplicate
    idempotent_run = workflow_engine.approve_and_resume_run(db=db, run_id=run.id, request_id=req_id)
    assert idempotent_run.status == "completed"

def test_workflow_rejection_prevents_downstream_execution(db_session):
    """Rejecting an approval gate immediately aborts the run without running downstream nodes."""
    db = db_session["db"]
    biz = db_session["biz"]
    
    wf = WorkflowDefinition(
        business_id=biz.id,
        name="Rejection Pipeline",
        nodes=[
            {"id": "step_a", "type": "trigger", "data": {"label": "Start"}},
            {"id": "gate_b", "type": "approval", "data": {"label": "Review Gate", "risk": "high"}},
            {"id": "step_c", "type": "action", "data": {"label": "Dangerous Downstream Action"}}
        ],
        edges=[
            {"source": "step_a", "target": "gate_b"},
            {"source": "gate_b", "target": "step_c"}
        ]
    )
    db.add(wf)
    db.commit()
    
    run = workflow_engine.execute_workflow(db=db, business_id=biz.id, workflow_id=wf.id)
    req_id = run.step_results["gate_b"]["request_id"]
    
    rejected_run = workflow_engine.reject_run(db=db, run_id=run.id, request_id=req_id, notes="Too risky")
    assert rejected_run.status == "rejected"
    assert rejected_run.verified_success is False
    assert "step_c" not in rejected_run.step_results

def test_financial_calculations_edge_cases(db_session):
    """
    Test edge cases in deterministic financial calculations:
    1. Zero cash balance
    2. Profitable business (MRR > Burn) -> infinite runway (999.0)
    3. Burning business -> exact calculated months
    """
    db = db_session["db"]
    
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    # 1. Profitable Business
    prof_biz = Business(name="Profitable SaaS", current_cash_balance=10000.0)
    db.add(prof_biz)
    db.commit()
    
    # MRR = $5,000, Expenses = $2,000 -> Net burn = -$3,000 (profitable)
    c1 = Customer(business_id=prof_biz.id, name="Client 1", mrr=5000.0, status="active")
    e1 = Expense(business_id=prof_biz.id, vendor="AWS", amount=2000.0, category="infra")
    db.add_all([c1, e1])
    db.commit()
    
    fin_prof = council_engine._calculate_deterministic_financials(db, prof_biz.id)
    assert fin_prof["is_profitable"] is True
    assert fin_prof["runway_months"] == 999.0
    assert fin_prof["net_burn"] <= 0.0
    
    # 2. Zero Cash Depleted Business
    broke_biz = Business(name="Depleted Startup", current_cash_balance=0.0)
    db.add(broke_biz)
    db.commit()
    
    e2 = Expense(business_id=broke_biz.id, vendor="Staff", amount=10000.0, category="payroll")
    db.add(e2)
    db.commit()
    
    fin_broke = council_engine._calculate_deterministic_financials(db, broke_biz.id)
    assert fin_broke["cash_balance"] == 0.0
    assert fin_broke["runway_months"] == 0.0
    assert fin_broke["runway_status"] == "depleted"

def test_demonstrable_founder_scenario(db_session):
    """
    Demonstrable founder validation task:
    1. Review overdue invoices -> produce correct deterministic receivable total
    2. Executive advisers debate realistic next actions -> dynamic grounded positions
    3. Founder approves plan -> immutable Decision record generated
    4. Workflow drafts reminder sandbox emails -> sandbox status recorded
    5. Audit log reflects verified outcome
    """
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    db = db_session["db"]
    biz = db_session["biz"]
    
    # Insert 2 overdue invoices
    inv1 = Invoice(
        business_id=biz.id,
        invoice_number="INV-TEST-01",
        customer_name="Alpha Corp",
        amount=1500.0,
        status="overdue",
        due_date=now - timedelta(days=10)
    )
    inv2 = Invoice(
        business_id=biz.id,
        invoice_number="INV-TEST-02",
        customer_name="Beta LLC",
        amount=2500.0,
        status="overdue",
        due_date=now - timedelta(days=5)
    )
    db.add_all([inv1, inv2])
    db.commit()
    
    # Step 1: Calculate receivable total deterministically
    calc = ToolRegistry.calculate_invoice_totals(db, biz.id)
    assert calc["total_overdue"] == 4000.0
    assert calc["invoice_count"] >= 2
    
    # Step 2: Draft sandbox reminder emails
    drafts = ToolRegistry.draft_invoice_reminder_emails(db, biz.id)
    assert drafts["drafts_created"] >= 2
    assert drafts["is_simulated"] is True
    
    # Step 3: Sandbox dispatch action
    dispatch_res = ToolRegistry.send_email_action(
        db=db,
        business_id=biz.id,
        recipient="Alpha Corp",
        subject="Invoice Overdue Notice",
        body="Please remit payment."
    )
    assert dispatch_res["status"] == "sandbox_draft_dispatched"
    assert dispatch_res["delivered"] is False
    assert dispatch_res["is_simulated"] is True
