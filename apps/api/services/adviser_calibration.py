"""Prospective founder-recorded forecasts and honest historical calibration.

Observations are tenant-recorded, not independently verified. No synthetic
seed score or self-reported observation becomes an independent accuracy claim.
"""
from datetime import datetime, timedelta
from math import isfinite, sqrt
from apps.api.models.decision_evidence import Decision
from apps.api.models.goals_tasks import Task
from apps.api.services.council_engine import COUNCIL_ROLES


def finite(value):
    return type(value) in (int, float) and isfinite(value) and abs(value) <= 1e15


def register_forecast(db, tenant, decision_id, adviser, metric, point, lower, upper, confidence, days):
    decision = db.query(Decision).filter_by(business_id=tenant, id=decision_id).with_for_update().first()
    if not decision or adviser not in COUNCIL_ROLES or adviser not in (decision.advisers_consulted or []):
        raise ValueError("Decision or participating adviser unavailable")
    if not isinstance(metric, str) or not metric.strip() or len(metric) > 255:
        raise ValueError("Invalid metric")
    if not all(finite(x) for x in (point, lower, upper, confidence)) or not lower <= point <= upper or not 0 < confidence < 1:
        raise ValueError("Invalid prediction interval")
    if type(days) is not int or not 1 <= days <= 365:
        raise ValueError("Invalid forecast horizon")
    predictions = list(decision.expected_outcomes or [])
    if len(predictions) >= 100 or any(x.get("metric") == metric for x in predictions + (decision.actual_outcomes or [])):
        raise ValueError("Metric already forecast or observed, or forecast limit reached")
    now = datetime.utcnow()
    predictions.append({"metric": metric, "predicted_value": point, "lower": lower, "upper": upper,
        "confidence": confidence, "timeframe_days": days, "adviser": adviser,
        "recorded_at": now.isoformat(), "due_at": (now + timedelta(days=days)).isoformat(),
        "source": "founder_recorded_prospective_forecast"})
    decision.expected_outcomes = predictions
    db.commit()
    return predictions[-1]


def interval_wilson(success, n):
    if not n:
        return None
    p, z = success/n, 1.96
    center = (p + z*z/(2*n))/(1+z*z/n)
    radius = z*sqrt((p*(1-p)+z*z/(4*n))/n)/(1+z*z/n)
    return [round(max(0,center-radius),4), round(min(1,center+radius),4)]


def summarize(decisions, tasks, now=None):
    now = now or datetime.utcnow()
    groups = {}
    for decision in decisions:
        for forecast in decision.expected_outcomes or []:
            if forecast.get("source") != "founder_recorded_prospective_forecast":
                continue
            adviser = forecast.get("adviser")
            if adviser not in COUNCIL_ROLES or adviser not in (decision.advisers_consulted or []):
                continue
            try:
                due = datetime.fromisoformat(forecast["due_at"])
                recorded = datetime.fromisoformat(forecast["recorded_at"])
                point, lower, upper, confidence = (forecast[k] for k in ("predicted_value","lower","upper","confidence"))
                if not all(finite(x) for x in (point,lower,upper,confidence)) or not lower <= point <= upper or not 0 < confidence < 1:
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            row = groups.setdefault(adviser, {"forecasts": 0, "due": 0, "pairs": [], "task_done": 0, "tasks": 0})
            row["forecasts"] += 1
            if due > now:
                continue
            row["due"] += 1
            observations = []
            for observation in decision.actual_outcomes or []:
                if observation.get("metric") != forecast["metric"] or observation.get("source") != "founder_reported_unverified":
                    continue
                try:
                    timestamp = datetime.fromisoformat(observation["recorded_at"])
                    value = observation["actual_value"]
                    if recorded < due <= timestamp <= now and finite(value):
                        observations.append((timestamp,value))
                except (ValueError, TypeError, KeyError):
                    continue
            if observations:
                value = min(observations)[1]  # one observation per forecast, never cherry-pick
                row["pairs"].append((abs(value-point), lower <= value <= upper, confidence, forecast["metric"]))
    decision_ids = {d.id for d in decisions if d.founder_decision == "approved"}
    for task in tasks:
        if task.decision_id not in decision_ids or task.responsible_agent not in COUNCIL_ROLES:
            continue
        row = groups.setdefault(task.responsible_agent, {"forecasts":0,"due":0,"pairs":[],"task_done":0,"tasks":0})
        row["tasks"] += 1
        row["task_done"] += task.status == "done"
    output = []
    for adviser, row in sorted(groups.items()):
        pairs = row["pairs"]; n = len(pairs); hits = sum(p[1] for p in pairs)
        metrics = {}
        for metric in sorted({p[3] for p in pairs}):
            errors = [p[0] for p in pairs if p[3] == metric]
            metrics[metric] = {"n":len(errors),"mean_absolute_error":round(sum(errors)/len(errors),4)}
        output.append({"adviser":adviser,"forecasts":row["forecasts"],"due":row["due"],"observed":n,
            "interval_coverage":hits/n if n else None,"coverage_95pct_wilson":interval_wilson(hits,n),
            "mean_stated_confidence":sum(p[2] for p in pairs)/n if n else None,
            "brier_score":sum((p[2]-float(p[1]))**2 for p in pairs)/n if n else None,
            "errors_by_metric":metrics,"tasks":row["tasks"],"tasks_marked_done":row["task_done"],
            "independently_verified":False,"source":"tenant_recorded_outcomes_not_independently_verified",
            "low_sample":n<20})
    return output


def historical_calibration(db, tenant):
    decisions = db.query(Decision).filter_by(business_id=tenant).order_by(Decision.created_at.desc()).limit(500).all()
    tasks = db.query(Task).filter_by(business_id=tenant).order_by(Task.created_at.desc()).limit(2000).all()
    return summarize(decisions,tasks)
