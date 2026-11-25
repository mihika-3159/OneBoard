"""Production HTTPS reverse-proxy boundary tests.

The external origin must match the configured API origin exactly. A client
cannot turn a plaintext request into a trusted HTTPS request by sending raw
X-Forwarded-Proto or X-Forwarded-Host headers. Uvicorn must validate trusted
proxy addresses *before* it populates the ASGI scope in a real deployment.
"""
import pytest
from fastapi.testclient import TestClient

from apps.api.core.config import settings
from apps.api.main import app


@pytest.fixture
def production_scope(monkeypatch):
    # Start the local synthetic test application in development mode; then
    # isolate the request-level production guards from schema validation.
    with TestClient(app, base_url="https://api.example.test") as client:
        monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
        monkeypatch.setattr(settings, "PUBLIC_API_ORIGIN", "https://api.example.test")
        yield client


def test_https_with_exact_expected_host_works_and_sets_hsts(production_scope):
    response = production_scope.get("/health")
    assert response.status_code == 200, response.text
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("host", [
    "evil.example.test",
    "api.example.test.evil.example.test",
    "API.EXAMPLE.TEST",
    "api.example.test:8443",
    "",
])
def test_production_rejects_host_header_poisoning(production_scope, host):
    response = production_scope.get("/health", headers={"host": host})
    assert response.status_code == 421, (host, response.status_code, response.text)
    assert response.headers["x-content-type-options"] == "nosniff"


def test_untrusted_forwarded_host_cannot_override_host(production_scope):
    response = production_scope.get("/health", headers={
        "host": "malicious.example.test",
        "x-forwarded-host": "api.example.test",
        "x-forwarded-proto": "https",
    })
    assert response.status_code == 421


def test_duplicate_host_headers_fail_closed(production_scope):
    response = production_scope.get("/health", headers=[
        ("host", "api.example.test"),
        ("host", "evil.example.test"),
    ])
    assert response.status_code == 421, response.text


def test_production_plaintext_rejected_even_with_spoofed_forwarded_proto(production_scope):
    # Explicit client Request overrides the base URL to produce a real
    # plaintext ASGI scheme; raw forwarded headers are not a trust anchor.
    response = production_scope.get(
        "http://api.example.test/health",
        headers={
            "host": "api.example.test",
            "x-forwarded-proto": "https",
            "x-forwarded-host": "api.example.test",
        },
    )
    assert response.status_code == 403, response.text
    assert "strict-transport-security" not in response.headers
    assert response.headers["x-frame-options"] == "DENY"


def test_insecure_sensitive_auth_endpoint_denied_before_auth(production_scope):
    response = production_scope.post(
        "http://api.example.test/api/auth/login",
        headers={"host": "api.example.test", "x-forwarded-proto": "https"},
        json={"email": "synthetic@example.invalid", "password": "not-a-secret"},
    )
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"

def test_production_csp_is_restrictive_and_applies_to_rejections(production_scope):
    for path,code in (("/health",200),("/api/business/metrics",401)):
        response=production_scope.get(path)
        assert response.status_code==code
        directives=dict((part.strip().split(None,1) for part in response.headers["content-security-policy"].split(";") if part.strip()))
        for name,value in {"default-src":"'none'","script-src":"'self'","connect-src":"'self'","frame-ancestors":"'none'","object-src":"'none'","base-uri":"'none'","form-action":"'self'"}.items():
            assert directives[name]==value
        if path.startswith("/api/"):assert response.headers["cache-control"]=="no-store"
