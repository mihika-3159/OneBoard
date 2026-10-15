import pytest
from apps.api.core.database import SessionLocal, init_db
from apps.api.services.seed_data import seed_northstar_studio, DEMO_BUSINESS_ID
from apps.api.services.council_engine import council_engine
from apps.api.services.workflow_engine import workflow_engine
from apps.api.services.accountability_engine import accountability_engine

@pytest.fixture(scope="module")
def db():
    init_db()
    session = SessionLocal()
    seed_northstar_studio(session, reset=True)
    yield session
    session.close()

def test_deterministic_financial_calculations(db):
    financials = council_engine._calculate_deterministic_financials(db, DEMO_BUSINESS_ID)
    assert financials["mrr"] > 0
    assert financials["monthly_expenses"] > 0
    assert financials["runway_months"] > 0
    assert financials["cash_balance"] == 132840.0
    assert financials["active_paying_customers"] >= 25

def test_workflow_dag_cycle_detection():
    # Valid DAG
    valid_wf = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
    }
    assert workflow_engine.validate_workflow(valid_wf)["is_valid"] is True

    # Cyclic graph
    cyclic_wf = {
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
    }
    assert workflow_engine.validate_workflow(cyclic_wf)["is_valid"] is False

from apps.api.models.decision_evidence import Decision

def test_accountability_error_calculation(db):
    decision = db.query(Decision).first()
    assert decision is not None
    res = accountability_engine.record_actual_outcome(
        db=db,
        decision_id=decision.id,
        metric_name="Qualified Leads",
        actual_value=14.0
    )
    # Target in demo seed was 50.0, actual 14.0
    # Absolute error = 36.0, Percentage error = 72.0%
    assert res is not None
