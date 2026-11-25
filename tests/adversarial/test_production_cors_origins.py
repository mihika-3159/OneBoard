"""Adversarial validation of production CORS origin configuration."""
import pytest

from apps.api.core.config import Settings, validate_production_configuration


def production_config(**overrides):
    values = {
        "ONEBOARD_PRODUCTION_MODE": True,
        "ONEBOARD_DEMO_MODE": False,
        "DEBUG": False,
        "COOKIE_SECURE": True,
        "AUTH_SECRET_KEY": "a" * 64,
        "DATABASE_URL": "postgresql://localhost/oneboard",
        "CORS_ORIGINS": "https://app.example.test",
        "PUBLIC_API_ORIGIN": "https://api.example.test",
        "TRUSTED_PROXY_IPS": "127.0.0.1",
    }
    values.update(overrides)
    return Settings(**values)


def test_canonical_https_origin_is_accepted():
    validate_production_configuration(production_config())
    validate_production_configuration(
        production_config(CORS_ORIGINS="https://app.example.test:8443")
    )


@pytest.mark.parametrize("origin", [
    "*", "http://app.example.test", "https://", "https:///",
    "https://app.example.test/path", "https://app.example.test/?q=1",
    "https://app.example.test/#fragment",
    "https://user@app.example.test", "https://user:password@app.example.test",
    "https://app.example.test:99999", "https://app.example.test:notaport",
    "https://APP.EXAMPLE.TEST", "https://app.example.test/",
])
def test_production_rejects_noncanonical_or_unsafe_origins(origin):
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validate_production_configuration(production_config(CORS_ORIGINS=origin))


def test_one_bad_origin_invalidates_entire_allowlist():
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validate_production_configuration(production_config(
            CORS_ORIGINS="https://app.example.test,https://user@evil.example.test"
        ))
