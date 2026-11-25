from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime
from math import isfinite
from apps.api.models.decision_evidence import Decision
from apps.api.models.agent_council import AdviserScorecard

class AccountabilityEngine:
    """
    Prediction tracking records user observations, never authenticates
    observations or calls them independently verified.
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
        """Record a founder-reported observation, without certifying provenance."""
        if not isinstance(metric_name, str) or not metric_name.strip():
            raise ValueError("A predicted metric must be selected")
        if isinstance(actual_value, bool) or not isfinite(float(actual_value)):
            raise ValueError("Actual outcome must be a finite number")
        if outcome_notes is not None and len(outcome_notes) > 4000:
            raise ValueError("Outcome notes exceed 4000 characters")
        decision = db.query(Decision).filter(Decision.id == decision_id).with_for_update().first()
        if not decision:
            raise ValueError("Decision not found")

        matches = [entry for entry in (decision.expected_outcomes or [])
                   if entry.get("metric") == metric_name]
        if len(matches) != 1:
            raise ValueError("Outcome requires exactly one matching recorded prediction")
        if matches[0].get("source") in ("founder_recorded_prospective_forecast","model_adviser_prospective_forecast"):
            due = datetime.fromisoformat(matches[0]["due_at"])
            if datetime.utcnow() < due:
                raise ValueError("Prospective forecast observation is not due yet")
            if any(entry.get("metric")==metric_name for entry in decision.actual_outcomes or []):
                raise ValueError("Prospective forecast already has a recorded observation")
        predicted_val = matches[0].get("predicted_value")
        if (type(predicted_val) not in (float, int)
                or not isfinite(float(predicted_val))):
            raise ValueError("Prediction is missing a valid numerical target")
        predicted_val = float(predicted_val)
        actual_value = float(actual_value)
        absolute_error = abs(actual_value - predicted_val)
        pct_error = (absolute_error / abs(predicted_val) * 100.0) if predicted_val else None

        actuals = list(decision.actual_outcomes or [])
        if len(actuals) >= 100:
            raise ValueError("Decision outcome history limit reached")
        actuals.append({
            "metric": metric_name,
            "predicted_value": predicted_val,
            "actual_value": actual_value,
            "absolute_error": round(absolute_error, 2),
            "percentage_error": round(pct_error, 1) if pct_error is not None else None,
            "recorded_at": datetime.utcnow().isoformat(),
            "source": "founder_reported_unverified",
            "independently_verified": False,
            "notes": outcome_notes or "",
        })
        decision.actual_outcomes = actuals
        # An operator-entered value or free-text note cannot prove settlement
        # or real-world outcome. Do not increment empirical adviser scorecards.
        decision.outcome_verified = False
        decision.outcome_notes = outcome_notes
        db.commit()
        db.refresh(decision)
        return {
            "decision_id": decision.id,
            "metric": metric_name,
            "predicted": predicted_val,
            "actual": actual_value,
            "absolute_error": round(absolute_error, 2),
            "percentage_error": round(pct_error, 1) if pct_error is not None else None,
            "status": "recorded_unverified",
            "independently_verified": False,
            "advisers_evaluated": [],
        }

    def get_scorecards(self, db: Session, business_id: str) -> List[Dict[str, Any]]:
        """Expose only provable counts, never fabricate empirical percentages."""
        scorecards = db.query(AdviserScorecard).filter(
            AdviserScorecard.business_id == business_id
        ).all()
        return [
            {
                "id": row.id,
                "adviser_name": row.adviser_name,
                "department": row.department,
                "total_recommendations": row.total_recommendations or 0,
                "approved_recommendations": row.approved_recommendations or 0,
                "overridden_recommendations": row.overridden_recommendations or 0,
                "predictions_tracked": row.predictions_tracked or 0,
                # Historical seed/default values have no independent backing.
                # Keep nullable until verifiable evidence-backed scorecards exist.
                "average_prediction_error_pct": None,
                "evidence_completeness_score": None,
                "action_completion_rate": None,
                "verified_outcome_rate": None,
                "last_evaluated": None,
                "verification_status": "not_independently_verified",
            }
            for row in scorecards
        ]

accountability_engine = AccountabilityEngine()
