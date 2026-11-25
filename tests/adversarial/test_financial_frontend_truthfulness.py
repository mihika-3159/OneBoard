"""Prevent the frontend from reintroducing fabricated financial success claims.

These checks complement the actual TypeScript build and browser E2E. Only
the tenant-scoped backend metric snapshot is authorized for live KPIs.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "apps/web/src/components/OverviewTab.tsx"
FINANCE = ROOT / "apps/web/src/components/FinanceTab.tsx"
TYPES = ROOT / "apps/web/src/types.ts"


def test_real_dashboard_does_not_default_to_demo_financial_values():
    source = OVERVIEW.read_text()
    for misleading in (
        "18450", "132840", "12200", "4170", "7.2", "91.4%",
        "38 active SaaS accounts", "Target: $25k MRR",
        "Exporter PR #14",
    ):
        assert misleading not in source
    assert "financial_data_status" in source
    assert "Historical financial trajectory is unavailable" in source
    assert "getMetrics()" in source


def test_finance_tab_never_displays_simulated_adapter_ledger_as_real():
    source = FINANCE.read_text()
    for misleading in (
        "18450", "132840", "12200", "7.2",
        "SVB / Mercury", "Calculations Verified",
        "GitHub Enterprise & Datadog", "38 paying subscribers",
        "3 Overdue ($4,170.00)",
    ):
        assert misleading not in source
    assert "api.getMetrics()" in source
    assert "api.getFinanceLedger()" not in source
    assert "financial_data_verified" in source
    assert "Unverified application records" in source


def test_client_types_require_data_quality_provenance_and_nullable_health():
    source = TYPES.read_text()
    assert "financial_data_status:" in source
    assert "financial_data_verified: boolean" in source
    assert "financial_data_issues: string[]" in source
    assert "health_score: number | null" in source
    assert "runway_months: number | null" in source
