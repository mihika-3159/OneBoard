"""Auditable, non-self-certifying OneBoard production acceptance evidence.

This produces a CI evidence receipt, NEVER independent production signoff.
No network, deployment, customer data or provider interactions are performed.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path


def build_report(smoke: dict | None = None, sha: str = "") -> dict:
    if smoke is not None:
        if smoke.get("disposable_windows_startup") != "passed":
            raise ValueError("Only a real passing disposable startup receipt can be included")
        if smoke.get("tenant_count") != 2 or smoke.get("isolation") != "passed":
            raise ValueError("Two-tenant smoke and isolation evidence required")
        if smoke.get("production_acceptance") is not False:
            raise ValueError("A synthetic CI smoke cannot certify production")
    return {
        "schema": "oneboard-release-evidence-v1",
        "commit_sha": sha or "unavailable",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "synthetic_windows_smoke": smoke or "not_supplied",
        "financial_source_verification": {
            "code": "evidence_diff_supported",
            "independent_bank_or_auditor_provenance": "not_verified",
            "customer_financial_data": "not_used"
        },
        "multi_tenant_load_security": {
            "code": "adversarial_test_matrix",
            "live_host_load_and_security_audit": "not_verified",
        },
        "windows_installation": {
            "code": "workflow_configured",
            "clean_startup": "passed" if smoke else "pending_or_not_supplied",
        },
        "independent_acceptance": {
            "reviewer": "not_engaged",
            "external_evidence": "missing",
            "deployed_founder_journey": "not_tested",
        },
        "external_operations": {
            "eligible_host": "not_verified",
            "real_https": "not_verified",
            "offsite_encrypted_restore": "not_verified",
            "provider_integrations": "not_verified",
        },
        "production_level_3": "NO_GO",
        "reason": (
            "CI evidence cannot establish independent financial provenance, "
            "a live external security audit, eligible deployment or independent signoff."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    smoke = json.loads(args.smoke_report.read_text(encoding="utf-8")) if args.smoke_report else None
    output = build_report(smoke, sha=os.getenv("GITHUB_SHA", ""))
    if args.out.is_symlink():
        raise RuntimeError("Refusing to replace symlink acceptance evidence")
    args.out.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("Evidence receipt saved; Level 3 production gate remains NO_GO")


if __name__ == "__main__":
    main()
