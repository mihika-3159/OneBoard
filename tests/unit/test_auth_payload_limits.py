"""Reject oversized authentication inputs before Argon2 and database access."""
import pytest
from pydantic import ValidationError
from apps.api.routers.auth_router import RegisterRequest, LoginRequest


@pytest.mark.parametrize("field,value", [
    ("name", "x" * 256),
    ("email", "x" * 256),
    ("password", "x" * 1025),
    ("business_name", "x" * 256),
    ("industry", "x" * 101),
    ("password", "short"),
])
def test_registration_rejects_invalid_lengths(field, value):
    payload = {
        "name": "Founder",
        "email": "founder@example.test",
        "password": "SafePassword123!",
        "business_name": "Founder Studio",
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        RegisterRequest(**payload)


@pytest.mark.parametrize("field,value", [
    ("email", "x" * 256),
    ("password", "x" * 1025),
    ("password", ""),
])
def test_login_rejects_invalid_lengths(field, value):
    payload = {"email": "founder@example.test", "password": "SafePassword123!"}
    payload[field] = value
    with pytest.raises(ValidationError):
        LoginRequest(**payload)


def test_valid_registration_and_login_payloads():
    RegisterRequest(name="Founder", email="founder@example.test", password="SafePassword123!")
    LoginRequest(email="founder@example.test", password="SafePassword123!")
