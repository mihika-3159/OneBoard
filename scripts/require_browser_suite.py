"""Fail CI on missing, skipped, failed or flaky browser tests."""
import json
import sys
from pathlib import Path
report=json.loads(Path(sys.argv[1]).read_text())
expected=int(sys.argv[2])
stats=report["stats"]
passed=stats["expected"]
failed=stats["unexpected"]
skipped=stats["skipped"]
flaky=stats["flaky"]
print(f"REQUIRED BROWSER: collected={passed+failed+skipped+flaky} passed={passed} failed={failed} skipped={skipped} flaky={flaky} expected={expected}")
if passed!=expected or failed or skipped or flaky:
    raise SystemExit("Mandatory browser coverage incomplete")
