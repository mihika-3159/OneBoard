"""P0 Batch A: no self-attested outcome may certify advisers or real-world success."""
import math
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.memory
import apps.api.models.workflow
import apps.api.models.goals_tasks
import apps.api.models.agent_council
import apps.api.models.decision_evidence
import apps.api.models.integrations
import apps.api.models.operations
from apps.api.models.agent_council import AdviserScorecard
from apps.api.models.decision_evidence import Decision, Evidence
from apps.api.services.accountability_engine import accountability_engine


@pytest.fixture
def records():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        d = Decision(
            business_id="test-tenant", title="Synthetic forecast",
            business_context="Synthetic only",
            expected_outcomes=[{"metric": "Qualified Leads", "predicted_value": 50, "timeframe_days": 7}],
            advisers_consulted=["Marketing Adviser"],
        )
        sc = AdviserScorecard(business_id="test-tenant",
                              adviser_name="Marketing Adviser", department="Growth")
        db.add_all([d, sc])
        db.commit()
        yield db, d, sc
    engine.dispose()


def test_founder_reported_outcome_is_not_verified_or_scored(records):
    db, decision, card = records
    response = accountability_engine.record_actual_outcome(
        db, decision.id, "Qualified Leads", 14, "Synthetic manual entry"
    )
    assert response["absolute_error"] == 36
    assert response["percentage_error"] == 72
    assert response["status"] == "recorded_unverified"
    assert response["independently_verified"] is False
    assert response["advisers_evaluated"] == []
    db.refresh(decision)
    db.refresh(card)
    assert decision.outcome_verified is False
    assert decision.actual_outcomes[-1]["independently_verified"] is False
    assert decision.actual_outcomes[-1]["source"] == "founder_reported_unverified"
    assert card.predictions_tracked == 0
    scores = accountability_engine.get_scorecards(db, "test-tenant")
    assert len(scores) == 1
    for column in ("average_prediction_error_pct", "evidence_completeness_score",
                   "action_completion_rate", "verified_outcome_rate", "last_evaluated"):
        assert scores[0][column] is None
    assert scores[0]["verification_status"] == "not_independently_verified"


def test_unsupported_prediction_rejected_and_does_not_mutate(records):
    db, decision, _ = records
    for metric in ("Revenue", "", "Other"):
        with pytest.raises(ValueError):
            accountability_engine.record_actual_outcome(db, decision.id, metric, 15)
    db.refresh(decision)
    assert not (decision.actual_outcomes or [])
    assert not decision.outcome_verified


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_actual_is_rejected(records, bad):
    db, d, _ = records
    with pytest.raises(ValueError):
        accountability_engine.record_actual_outcome(db, d.id, "Qualified Leads", bad)


def test_zero_prediction_does_not_fabricate_zero_percent_error(records):
    db, d, _ = records
    d.expected_outcomes = [{"metric": "Zero baseline", "predicted_value": 0, "timeframe_days": 1}]
    db.commit()
    result = accountability_engine.record_actual_outcome(db, d.id, "Zero baseline", 4)
    assert result["absolute_error"] == 4
    assert result["percentage_error"] is None
    assert result["independently_verified"] is False


def test_unbacked_default_scores_are_null_even_on_new_models(records):
    db, d, sc = records
    db.refresh(sc)
    assert sc.evidence_completeness_score is None
    assert sc.action_completion_rate is None
    assert sc.verified_outcome_rate is None
    evidence = Evidence(
        business_id="test-tenant", title="synthetic", source_connector="local_file",
        snippet="founder statement",
    )
    db.add(evidence)
    db.commit()
    assert evidence.provenance_type == "user_statement"
    assert evidence.confidence_score is None


def test_seeded_scorecards_not_presented_as_authenticated_performance(records):
    db, d, card = records
    card.evidence_completeness_score = 0.92
    card.action_completion_rate = 0.88
    card.verified_outcome_rate = 0.85
    card.average_prediction_error_pct = 9.2
    card.predictions_tracked = 1
    db.commit()
    values = accountability_engine.get_scorecards(db, "test-tenant")[0]
    assert values["average_prediction_error_pct"] is None
    assert values["evidence_completeness_score"] is None
    assert values["action_completion_rate"] is None
    assert values["verified_outcome_rate"] is None
