import pytest
import asyncio
from apps.api.core.database import SessionLocal, init_db
from apps.api.services.seed_data import seed_northstar_studio, DEMO_BUSINESS_ID
from apps.api.services.council_engine import council_engine
from apps.api.services.workflow_engine import workflow_engine
from apps.api.models.workflow import WorkflowDefinition

@pytest.fixture(scope="module")
def db():
    init_db()
    session = SessionLocal()
    seed_northstar_studio(session, reset=True)
    yield session
    session.close()

@pytest.mark.asyncio
async def test_council_deliberation_and_approval(db):
    meeting = await council_engine.conduct_deliberation(
        db=db,
        business_id=DEMO_BUSINESS_ID,
        title="Integration Test Review",
        meeting_type="weekly_executive_review",
        topic="Evaluate annual prepay incentives",
        selected_advisers=["Chief of Staff", "Finance Adviser", "Marketing Adviser"]
    )
    assert meeting.id is not None
    assert len(meeting.deliberation_transcript) > 0
    assert "Evaluate annual prepay incentives" in meeting.synthesis_summary
    assert meeting.recommended_actions
    assert all(action.get("source") in ("meeting_topic", "tenant_financial_snapshot")
               for action in meeting.recommended_actions)
    # Do not fabricate consensus when the offline model cannot establish it.
    assert not meeting.areas_of_agreement

    decision = council_engine.approve_meeting_decision(
        db=db,
        business_id=DEMO_BUSINESS_ID,
        meeting_id=meeting.id,
        decision_notes="Approved in integration test."
    )
    assert decision.founder_decision == "approved"
    assert decision.expected_outcomes == []  # No invented financial forecasts.
    assert decision.planned_actions == meeting.recommended_actions

def test_workflow_execution_and_approval_gate(db):
    wf = db.query(WorkflowDefinition).filter(WorkflowDefinition.business_id == DEMO_BUSINESS_ID).first()
    assert wf is not None

    run = workflow_engine.execute_workflow(
        db=db,
        business_id=DEMO_BUSINESS_ID,
        workflow_id=wf.id,
        trigger_source="test"
    )
    assert run.status in ["completed", "awaiting_approval"]
    assert len(run.step_results) > 0
