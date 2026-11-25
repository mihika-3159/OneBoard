"""Run a required pytest suite and reject missing, skipped, or failed tests.

Usage: python scripts/require_test_suite.py EXPECTED REPORT.xml pytest_args...
The expected inventory is intentional: update it when adding/removing tests.
"""
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

def verify_report(path, expected):
    root=ET.parse(path).getroot()
    cases=list(root.iter("testcase"))
    counts={name:sum(case.find(name) is not None for case in cases)
            for name in ("failure","error","skipped")}
    failed=counts["failure"]+counts["error"]
    passed=len(cases)-failed-counts["skipped"]
    print(f"REQUIRED SUITE: collected={len(cases)} passed={passed} failed={failed} skipped={counts['skipped']} expected={expected}",flush=True)
    if len(cases)!=expected or failed or counts["skipped"] or passed!=expected:
        raise SystemExit("Required suite did not execute every expected test successfully")
    if len({(case.get("classname"),case.get("name")) for case in cases})!=expected:
        raise SystemExit("Duplicate test identities in required report")

def main():
    expected=int(sys.argv[1])
    report=Path(sys.argv[2])
    if expected<1:
        raise SystemExit("Expected inventory must be positive")
    report.unlink(missing_ok=True)
    result=subprocess.run([sys.executable,"-m","pytest","-v",*sys.argv[3:],f"--junitxml={report}"])
    if not report.is_file():
        raise SystemExit("Required test report missing")
    verify_report(report,expected)
    if result.returncode:
        raise SystemExit(result.returncode)
if __name__=="__main__":
    main()
