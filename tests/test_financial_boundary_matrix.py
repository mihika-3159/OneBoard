"""Boundary regression matrix for deterministic financial calculations."""
import pytest
from types import SimpleNamespace
from apps.api.services.financial_metrics import runway_from_records, monthly_expense_amount


@pytest.mark.parametrize("cash,burn,mrr,expected_months,expected_status,expected_net", [
    (0, 100, 0, 0.0, "critical_depleted", 100),
    (-10, 100, 0, 0.0, "critical_depleted", 100),
    (600, 100, 0, 6.0, "warning", 100),
    (1200, 100, 0, 12.0, "healthy", 100),
    (300, 100, 0, 3.0, "critical", 100),
    (599, 100, 0, 6.0, "warning", 100),
    (100, 100, 100, None, "breakeven", 0),
    (100, 100, 200, None, "profitable", -100),
    (0, 100, 200, None, "profitable", -100),
    (500, 150, 100, 10.0, "warning", 50),
])
def test_runway_boundaries(cash, burn, mrr, expected_months, expected_status, expected_net):
    assert runway_from_records(cash, burn, mrr) == (expected_months, expected_status, expected_net)


@pytest.mark.parametrize("period,amount,expected", [
    ("annual", 1200, 100),
    ("monthly", 100, 100),
    ("one-off", 100, 0),
    ("one_time", 100, 0),
    ("one-time", 100, 0),
])
def test_expense_periods(period, amount, expected):
    assert monthly_expense_amount(SimpleNamespace(billing_period=period, amount=amount)) == expected
