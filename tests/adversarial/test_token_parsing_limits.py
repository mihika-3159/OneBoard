"""Adversarial tests for bounded, non-disclosing authentication token parsing."""
import pytest
from fastapi.testclient import TestClient

from apps.api.core.auth import create_access_token, decode_access_token
from apps.api.main import app


def test_legitimate_signed_token_still_decodes():
    token = create_access_token("founder", "tenant")
    payload = decode_access_token(token)
    assert payload["sub"] == "founder"
    assert payload["biz"] == "tenant"


@pytest.mark.parametrize("token", [
    "x" * 100_000,
    "not-a-token",
    "e30.invalid",
    "%%%%.bad",
    "",
])
def test_malformed_tokens_have_generic_bounded_error(token):
    with pytest.raises(ValueError, match="^Invalid access token$"):
        decode_access_token(token)


def test_oversized_bearer_returns_generic_401_without_echoing_token():
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/business", headers={
            "Authorization": "Bearer " + ("X" * 100_000)
        })
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired authentication credentials."
    assert "XXXXX" not in response.text
