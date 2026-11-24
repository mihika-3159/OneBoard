"""Black-box Windows/Linux clean startup with two synthetic founder tenants.

Uses only stdlib HTTP, never a provider account, payment, or real customer data.
Runs the service in a child process and terminates it on every exit path.
"""
from __future__ import annotations
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18765"


def request(path: str, *, method: str = "GET", body=None, token=None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(BASE + path, method=method, headers=headers, data=data)
    try:
        with urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def run() -> dict:
    if os.getenv("ONEBOARD_TEST_DISPOSABLE_STARTUP") != "1":
        raise RuntimeError("Startup smoke requires disposable CI confirmation")
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("sqlite:///") or "oneboard_windows_ci.sqlite3" not in url:
        raise RuntimeError("Never run black-box smoke against non-disposable database")
    logfile = Path(tempfile.gettempdir()) / ("oneboard-startup-" + uuid4().hex + ".log")
    with logfile.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "apps.api.main:app",
             "--host", "127.0.0.1", "--port", "18765"],
            cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, env=os.environ.copy(),
        )
        try:
            for attempt in range(60):
                if proc.poll() is not None:
                    raise RuntimeError("Fresh API exited before health check")
                try:
                    code, health = request("/health")
                    if code == 200 and health.get("status") == "healthy":
                        break
                except (URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("Fresh API failed to start within smoke bound")
            tokens = []
            business_ids = []
            for n in range(2):
                registration = {
                    "name": "Synthetic Windows Founder",
                    "email": "windows-" + uuid4().hex + "@example.invalid",
                    "password": "StrongSyntheticPassword-1234!",
                    "business_name": "Windows CI tenant " + str(n),
                }
                status, created = request("/api/auth/register", method="POST", body=registration)
                assert status == 201 and created.get("token"), "Registration smoke failed"
                tokens.append(created["token"])
                stat, metrics = request("/api/business/metrics", token=tokens[-1])
                assert stat == 200 and metrics["financial_data_verified"] is False
                business_ids.append(metrics["tenant_id"])
            assert business_ids[0] != business_ids[1], "Tenant ID reused"
            for token in tokens:
                status, outbox = request("/api/integrations/email/outbox", token=token)
                assert status == 200 and outbox.get("outbox") == []
                status, _ = request("/api/integrations/crm/contacts", token=token)
                assert status == 404, "Synthetic fixture leaked into registered tenant"
            evidence = (
                "record_type,record_id,amount,currency,as_of\n"
                "invoice,unknown,5,USD," + date.today().isoformat() + "\n"
            )
            status, report = request(
                "/api/business/financial/reconcile", method="POST",
                token=tokens[0], body={"evidence_csv": evidence}
            )
            assert status == 200 and report["independently_verified"] is False
            assert report["results"][0]["comparison"] == "missing_or_inaccessible"
            return {
                "disposable_windows_startup": "passed",
                "tenant_count": 2, "isolation": "passed",
                "financial_evidence": "not_independently_verified",
                "external_tls": "not_tested", "production_acceptance": False,
            }
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            logfile.unlink(missing_ok=True)


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
