"""Entrypoint and production connection trust must fail closed.

These tests never start a network listener or use any cloud provider.
"""
import pytest

from apps.api.core.config import Settings, validate_production_configuration
from scripts.serve_secure_api import secure_uvicorn_options


def _production(**overrides):
    values = {
        "ONEBOARD_PRODUCTION_MODE": True,
        "ONEBOARD_DEMO_MODE": False,
        "DEBUG": False,
        "COOKIE_SECURE": True,
        "AUTH_SECRET_KEY": "a" * 64,
        "DATABASE_URL": "postgresql+psycopg://ci:placeholder@localhost/oneboard",
        "PUBLIC_API_ORIGIN": "https://api.example.test",
        "CORS_ORIGINS": "https://app.example.test",
        "TRUSTED_PROXY_IPS": "127.0.0.1",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("unsafe", [
    "", "*", "0.0.0.0", "::", "0.0.0.0/0", "127.0.0.1/32",
    "proxy.example.test", "127.0.0.1,127.0.0.1", "224.0.0.1",
])
def test_rejects_unsafe_or_unbounded_forwarded_allow_ips(unsafe):
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_IPS"):
        validate_production_configuration(_production(TRUSTED_PROXY_IPS=unsafe))


@pytest.mark.parametrize("database_url", [
    "postgresql+psycopg://ci:placeholder@db.example.test/oneboard",
    "postgresql+psycopg://ci:placeholder@db.example.test/oneboard?sslmode=require",
    "postgresql+psycopg://ci:placeholder@db.example.test/oneboard?sslmode=prefer",
])
def test_remote_database_requires_verified_postgresql_server_identity(database_url):
    with pytest.raises(RuntimeError, match="sslmode=verify-full"):
        validate_production_configuration(_production(DATABASE_URL=database_url))


def test_valid_remote_database_verification_does_not_create_connection():
    config = _production(
        DATABASE_URL="postgresql+psycopg://ci:placeholder@db.example.test/oneboard?sslmode=verify-full"
    )
    validate_production_configuration(config)


def test_owner_proxy_entrypoint_never_exposes_public_asgi_port():
    config = _production(TRUSTED_PROXY_IPS="127.0.0.1,::1")
    options = secure_uvicorn_options(config)
    assert options == {
        "host": "127.0.0.1",
        "port": 8000,
        "proxy_headers": True,
        "forwarded_allow_ips": "127.0.0.1,::1",
        "reload": False,
        "workers": 1,
    }
    assert "*" not in options["forwarded_allow_ips"]


def test_development_entrypoint_does_not_enable_header_trust():
    config = _production(
        ONEBOARD_PRODUCTION_MODE=False, TRUSTED_PROXY_IPS=""
    )
    options = secure_uvicorn_options(config)
    assert options["host"] == "127.0.0.1"
    assert options["proxy_headers"] is False
    assert options["reload"] is False
