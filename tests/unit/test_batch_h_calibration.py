from datetime import datetime,timedelta
from types import SimpleNamespace
from apps.api.services.adviser_calibration import summarize,interval_wilson


def test_prospective_pairing_excludes_legacy_and_early_observations_and_reports_uncertainty():
    now=datetime(2026,1,20);start=now-timedelta(days=10);due=now-timedelta(days=5)
    forecast={"metric":"Signups","predicted_value":10,"lower":8,"upper":12,"confidence":0.8,
              "source":"founder_recorded_prospective_forecast","adviser":"Strategy Adviser",
              "recorded_at":start.isoformat(),"due_at":due.isoformat()}
    observations=[{"metric":"Signups","actual_value":10,"source":"founder_reported_unverified","recorded_at":start.isoformat()},
                  {"metric":"Signups","actual_value":15,"source":"founder_reported_unverified","recorded_at":due.isoformat()},
                  {"metric":"Signups","actual_value":10,"source":"founder_reported_unverified","recorded_at":now.isoformat()}]
    decision=SimpleNamespace(id="d",founder_decision="approved",advisers_consulted=["Strategy Adviser"],expected_outcomes=[forecast],actual_outcomes=observations)
    row=summarize([decision],[],now)[0]
    assert row["observed"]==1 and row["interval_coverage"]==0
    assert row["errors_by_metric"]["Signups"]["mean_absolute_error"]==5
    assert row["low_sample"] and not row["independently_verified"]
    assert interval_wilson(0,0) is None
