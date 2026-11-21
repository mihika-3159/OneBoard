"""Council grounding regressions: isolated SQLite, no real Ollama or integrations."""
import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.core.database import Base
import apps.api.models.business  # noqa: F401
import apps.api.models.entities  # noqa: F401
import apps.api.models.goals_tasks  # noqa: F401
import apps.api.models.workflow  # noqa: F401
import apps.api.models.memory  # noqa: F401
import apps.api.models.agent_council  # noqa: F401
import apps.api.models.decision_evidence  # noqa: F401
import apps.api.models.integrations  # noqa: F401
from apps.api.models.business import Business
from apps.api.models.entities import Expense, Invoice
from apps.api.models.agent_council import CouncilMeeting
from apps.api.models.decision_evidence import Decision
from apps.api.models.goals_tasks import Task
from apps.api.services.council_engine import council_engine


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def business(db, name="Founder Company", cash=0):
    record = Business(name=name, current_cash_balance=cash)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def deliberate(db, business_id, topic, advisers=None):
    return asyncio.run(council_engine.conduct_deliberation(
        db=db, business_id=business_id, title="Review", meeting_type="custom",
        topic=topic, selected_advisers=advisers
    ))


async def offline_response(**kwargs):
    return {
        "simulated": True,
        "content": "Northstar Studio has $132,840 cash and $18,450 MRR; price is $59.",
        "model": "simulated"
    }


def test_offline_council_never_presents_canned_business_claims(db):
    a = business(db)
    with patch("apps.api.services.council_engine.ollama_gateway.chat_complete",
               side_effect=offline_response):
        meeting = deliberate(db, a.id, "Reduce onboarding support delays",
                             ["Finance Adviser", "Operations Adviser"])
    text = meeting.synthesis_summary + " ".join(
        entry["content"] for entry in meeting.deliberation_transcript
    )
    assert "132,840" not in text
    assert "18,450" not in text
    assert "Northstar Studio" not in text
    assert "Reduce onboarding support delays" in text
    assert "no LLM inference" in meeting.synthesis_summary
    assert all(item["simulated"] for item in meeting.deliberation_transcript)
    assert meeting.areas_of_agreement == []
    assert meeting.areas_of_disagreement == []


def test_topic_and_actual_financials_change_recommendations(db):
    a = business(db, cash=100)
    db.add(Expense(
        business_id=a.id, category="Hosting", vendor="Host",
        amount=200, billing_period="monthly"
    ))
    db.commit()
    with patch("apps.api.services.council_engine.ollama_gateway.chat_complete",
               side_effect=offline_response):
        low = deliberate(db, a.id, "Improve customer onboarding",
                         ["Finance Adviser", "Operations Adviser"])
        a.current_cash_balance = 5000
        db.commit()
        healthy = deliberate(db, a.id, "Improve product reliability",
                             ["Finance Adviser", "Operations Adviser"])
    assert low.recommended_actions != healthy.recommended_actions
    assert any("cash runway" in action["title"] for action in low.recommended_actions)
    assert not any("cash runway" in action["title"] for action in healthy.recommended_actions)
    assert "onboarding" in low.recommended_actions[0]["title"]
    assert "reliability" in healthy.recommended_actions[0]["title"]
    assert all(action["source"] in ("meeting_topic", "tenant_financial_snapshot")
               for action in low.recommended_actions)


def test_invalid_advisers_rejected_without_persisting_meeting(db):
    a = business(db)
    for advisers in ([], ["Unknown Adviser"], ["Finance Adviser", "Finance Adviser"]):
        with pytest.raises(ValueError):
            deliberate(db, a.id, "Audit operations", advisers)
    assert db.query(CouncilMeeting).count() == 0


def test_live_synthesis_receives_real_positions_and_labels_unverified(db):
    a = business(db)
    prompts = []

    async def online_response(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        prompts.append(prompt)
        if "Actual adviser positions:" in prompt:
            return {"simulated": False, "content": "Review evidence before action"}
        if "position:" in prompt:
            return {"simulated": False, "content": "Possible capacity trade-off"}
        return {"simulated": False, "content": "Review staffing capacity and service delays"}

    with patch("apps.api.services.council_engine.ollama_gateway.chat_complete",
               side_effect=online_response):
        meeting = deliberate(db, a.id, "Reduce support response times",
                             ["Operations Adviser", "Customer Success Adviser"])
    assert "Review staffing capacity and service delays" in prompts[-1]
    assert "Possible capacity trade-off" in prompts[-1]
    assert "unverified" in meeting.synthesis_summary.lower()
    assert meeting.deliberation_transcript[-1]["stage"] == "challenge_round"
    assert not any(entry["simulated"] for entry in meeting.deliberation_transcript)


def test_approval_has_no_fabricated_forecasts_and_cannot_replay_or_cross_tenant(db):
    a, b = business(db, "A"), business(db, "B")
    with patch("apps.api.services.council_engine.ollama_gateway.chat_complete",
               side_effect=offline_response):
        meeting = deliberate(db, a.id, "Assess privacy risks", ["Risk and Compliance Adviser"])
    with pytest.raises(ValueError):
        council_engine.approve_meeting_decision(db, b.id, meeting.id)
    decision = council_engine.approve_meeting_decision(db, a.id, meeting.id)
    assert decision.assumptions == []
    assert decision.expected_outcomes == []
    assert decision.planned_actions == meeting.recommended_actions
    assert db.query(Task).filter(Task.business_id == a.id, Task.decision_id == decision.id).count() == 1
    with pytest.raises(ValueError):
        council_engine.approve_meeting_decision(db, a.id, meeting.id)
    assert db.query(Decision).filter(Decision.business_id == a.id).count() == 1
    assert db.query(Task).filter(Task.business_id == a.id).count() == 1
