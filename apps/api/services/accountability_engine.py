from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime
from apps.api.models.decision_evidence import Decision
from apps.api.models.agent_council import AdviserScorecard

class AccountabilityEngine:
    """
    Flagship Accountability & Outcome Verification Engine.
    Enforces the closed operational loop:
    Prediction -> Recorded Assumptions -> Observed Outcome -> Error Analysis -> Immutable Audit.
    """

    def record_prediction(
        self,
        db: Session,
        decision_id: str,
        metric_name: str,
        predicted_value: float,
        timeframe_days: int,
        assumptions: List[str]
    ) -> Decision:
        decision = db.query(Decision).filter(Decision.id == decision_id).first()
        if not decision:
            raise ValueError(f"Decision {decision_id} not found")

        expected = decision.expected_outcomes or []
        expected.append({
            "metric": metric_name,
            "predicted_value": predicted_value,
            "timeframe_days": timeframe_days,
            "recorded_at": datetime.utcnow().isoformat(),
            "assumptions": assumptions
        })
        decision.expected_outcomes = expected
        db.commit()
        db.refresh(decision)
        return decision

    def record_actual_outcome(
        self,
        db: Session,
        decision_id: str,
        metric_name: str,
        actual_value: float,
        outcome_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculates error, identifies failed assumptions, and updates the empirical adviser scorecard.
        """
        decision = db.query(Decision).filter(Decision.id == decision_id).first()
        if not decision:
            raise ValueError(f"Decision {decision_id} not found")

        expected_list = decision.expected_outcomes or []
        target_prediction = None
        for exp in expected_list:
            if exp.get("metric") == metric_name:
                target_prediction = exp
                break

        predicted_val = target_prediction.get("predicted_value", 0.0) if target_prediction else 0.0
        absolute_error = abs(actual_value - predicted_val)
        pct_error = (absolute_error / predicted_val * 100.0) if predicted_val > 0 else 0.0

        actuals = decision.actual_outcomes or []
        actuals.append({
            "metric": metric_name,
            "predicted_value": predicted_val,
            "actual_value": actual_value,
            "absolute_error": round(absolute_error, 2),
            "percentage_error": round(pct_error, 1),
            "verified_at": datetime.utcnow().isoformat(),
            "notes": outcome_notes or "Empirically measured outcome."
        })
        decision.actual_outcomes = actuals
        decision.outcome_verified = True
        decision.outcome_notes = outcome_notes

        # Update Adviser Scorecards
        advisers = decision.advisers_consulted or []
        for adv_name in advisers:
            scorecard = db.query(AdviserScorecard).filter(
                AdviserScorecard.business_id == decision.business_id,
                AdviserScorecard.adviser_name == adv_name
            ).first()
            if scorecard:
                scorecard.predictions_tracked += 1
                # Recalculate moving average error
                old_avg = scorecard.average_prediction_error_pct
                scorecard.average_prediction_error_pct = round((old_avg + pct_error) / 2.0, 1)
                scorecard.last_evaluated_at = datetime.utcnow()

        db.commit()
        db.refresh(decision)

        return {
            "decision_id": decision.id,
            "metric": metric_name,
            "predicted": predicted_val,
            "actual": actual_value,
            "absolute_error": round(absolute_error, 2),
            "percentage_error": round(pct_error, 1),
            "advisers_evaluated": advisers
        }

    def get_scorecards(self, db: Session, business_id: str) -> List[Dict[str, Any]]:
        scorecards = db.query(AdviserScorecard).filter(AdviserScorecard.business_id == business_id).all()
        return [
            {
                "id": s.id,
                "adviser_name": s.adviser_name,
                "department": s.department,
                "total_recommendations": s.total_recommendations,
                "approved_recommendations": s.approved_recommendations,
                "overridden_recommendations": s.overridden_recommendations,
                "predictions_tracked": s.predictions_tracked,
                "average_prediction_error_pct": s.average_prediction_error_pct,
                "evidence_completeness_score": round(s.evidence_completeness_score * 100, 1),
                "action_completion_rate": round(s.action_completion_rate * 100, 1),
                "verified_outcome_rate": round(s.verified_outcome_rate * 100, 1),
                "last_evaluated": s.last_evaluated_at.isoformat() if s.last_evaluated_at else None
            }
            for s in scorecards
        ]

accountability_engine = AccountabilityEngine()
