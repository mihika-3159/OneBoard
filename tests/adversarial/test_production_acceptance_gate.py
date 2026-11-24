"""Self-authored synthetic CI cannot impersonate independent Level 3 acceptance."""
import json
import pytest
from scripts.production_acceptance import build_report


def test_no_windows_receipt_never_certifies_production():
    report = build_report(sha="synthetic-commit")
    assert report["production_level_3"] == "NO_GO"
    assert report["independent_acceptance"]["reviewer"] == "not_engaged"
    assert report["windows_installation"]["clean_startup"] == "pending_or_not_supplied"


def test_even_a_green_two_tenant_smoke_is_not_independent_signoff():
    report = build_report({
        "disposable_windows_startup": "passed", "tenant_count": 2,
        "isolation": "passed", "production_acceptance": False,
    }, sha="synthetic")
    assert report["windows_installation"]["clean_startup"] == "passed"
    assert report["production_level_3"] == "NO_GO"
    assert report["financial_source_verification"]["independent_bank_or_auditor_provenance"] == "not_verified"
    assert report["multi_tenant_load_security"]["live_host_load_and_security_audit"] == "not_verified"
    assert report["external_operations"]["real_https"] == "not_verified"


@pytest.mark.parametrize("spoof", [
    {"disposable_windows_startup": "passed", "tenant_count": 1,
     "isolation": "passed", "production_acceptance": False},
    {"disposable_windows_startup": "passed", "tenant_count": 2,
     "isolation": "failed", "production_acceptance": False},
    {"disposable_windows_startup": "passed", "tenant_count": 2,
     "isolation": "passed", "production_acceptance": True},
    {"disposable_windows_startup": "not_run", "tenant_count": 2,
     "isolation": "passed", "production_acceptance": False},
])
def test_spoofed_smoke_receipts_are_rejected(spoof):
    with pytest.raises(ValueError):
        build_report(spoof)
