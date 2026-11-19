import pytest

from apps.api.core.config import Settings, validate_production_configuration


def production_settings(**overrides):
    values = {
        "ONEBOARD_PRODUCTION_MODE": True,
        "ONEBOARD_DEMO_MODE": False,
        "DEBUG": False,
        "COOKIE_SECURE": True,
        "AUTH_SECRET_KEY": "a" * 64,
        "DATABASE_URL": "postgresql://oneboard:placeholder@localhost/oneboard",
        "CORS_ORIGINS": "https://app.example.test",
    }
    values.update(overrides)
    return Settings(**values)


def test_secure_production_configuration_passes():
    validate_production_configuration(production_settings())


@pytest.mark.parametrize("unsafe", [
    {"ONEBOARD_DEMO_MODE": True},
    {"DEBUG": True},
    {"COOKIE_SECURE": False},
    {"AUTH_SECRET_KEY": "short"},
    {"DATABASE_URL": "sqlite:///data/oneboard.db"},
    {"CORS_ORIGINS": "*"},
    {"CORS_ORIGINS": "http://localhost:5173"},
    {"CORS_ORIGINS": ""},
])
def test_unsafe_production_configuration_fails_closed(unsafe):
    with pytest.raises(RuntimeError, match="Unsafe OneBoard production configuration"):
        validate_production_configuration(production_settings(**unsafe))


def test_local_development_configuration_is_not_affected():
    validate_production_configuration(Settings(
        ONEBOARD_PRODUCTION_MODE=False,
        AUTH_SECRET_KEY="",
        DATABASE_URL="sqlite:///local.db",
        COOKIE_SECURE=False,
    ))


def test_api_security_headers_and_auth_cache_controls():
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        public = client.get("/health")
        assert public.status_code == 200
        assert public.headers["x-content-type-options"] == "nosniff"
        assert public.headers["x-frame-options"] == "DENY"
        assert public.headers["referrer-policy"] == "no-referrer"
        assert "camera=()" in public.headers["permissions-policy"]

        private = client.get("/api/auth/me")
        assert private.status_code == 401
        assert private.headers["cache-control"] == "no-store"
        assert private.headers["x-content-type-options"] == "nosniff"
