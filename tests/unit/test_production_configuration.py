import pytest

from fastapi import HTTPException
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
        "PUBLIC_API_ORIGIN": "https://api.example.test",
        "TRUSTED_PROXY_IPS": "127.0.0.1",
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
    {"PUBLIC_API_ORIGIN": ""},
    {"PUBLIC_API_ORIGIN": "http://api.example.test"},
    {"PUBLIC_API_ORIGIN": "https://api.example.test/auth"},
    {"PUBLIC_API_ORIGIN": "https://username@api.example.test"},
    {"PUBLIC_API_ORIGIN": "https://api.example.test:invalid"},
    {"PUBLIC_API_ORIGIN": "*"},
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


def test_production_startup_rejects_unmigrated_database(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from apps.api.core import database

    isolated = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(database, "engine", isolated)
    monkeypatch.setattr(database.settings, "ONEBOARD_PRODUCTION_MODE", True)
    with pytest.raises(RuntimeError, match="migration revision mismatch"):
        database.init_db()
    from sqlalchemy import inspect
    assert inspect(isolated).get_table_names() == []


def test_production_startup_rejects_stamped_but_incomplete_schema(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from apps.api.core import database

    isolated = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(database, "engine", isolated)
    monkeypatch.setattr(database.settings, "ONEBOARD_PRODUCTION_MODE", True)
    heads = ScriptDirectory.from_config(Config(str(database.settings.BASE_DIR / "alembic.ini"))).get_heads()
    assert len(heads) == 1
    with isolated.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES (:head)"), {"head": heads[0]})
    # An Alembic version stamp alone is not evidence of a complete schema.
    # Startup must fail closed and must not create any missing tables.
    monkeypatch.setattr(database.Base.metadata, "create_all", lambda **kwargs: pytest.fail("create_all called"))
    with pytest.raises(RuntimeError, match="missing required application tables"):
        database.init_db()


@pytest.mark.parametrize("override,expected", [
    ({"SESSION_EXPIRY_SECONDS": 0}, "SESSION_EXPIRY_SECONDS"),
    ({"SESSION_EXPIRY_SECONDS": 31 * 24 * 3600}, "SESSION_EXPIRY_SECONDS"),
    ({"LOGIN_MAX_ATTEMPTS": 0}, "LOGIN_MAX_ATTEMPTS"),
    ({"LOGIN_MAX_ATTEMPTS": 21}, "LOGIN_MAX_ATTEMPTS"),
    ({"LOGIN_LOCKOUT_SECONDS": 0}, "LOGIN_LOCKOUT_SECONDS"),
    ({"LOGIN_LOCKOUT_SECONDS": 86401}, "LOGIN_LOCKOUT_SECONDS"),
    ({"REGISTRATION_SOURCE_MAX_ATTEMPTS": 9}, "REGISTRATION_SOURCE_MAX_ATTEMPTS"),
    ({"REGISTRATION_SOURCE_MAX_ATTEMPTS": 101}, "REGISTRATION_SOURCE_MAX_ATTEMPTS"),
    ({"REGISTRATION_SOURCE_MAX_ATTEMPTS": 10, "LOGIN_MAX_ATTEMPTS": 12}, "REGISTRATION_SOURCE_MAX_ATTEMPTS"),
    ({"LOGIN_SOURCE_MAX_ATTEMPTS": 19}, "LOGIN_SOURCE_MAX_ATTEMPTS"),
    ({"LOGIN_SOURCE_MAX_ATTEMPTS": 201}, "LOGIN_SOURCE_MAX_ATTEMPTS"),
    ({"LOGIN_SOURCE_MAX_ATTEMPTS": 20, "LOGIN_MAX_ATTEMPTS": 20}, "LOGIN_SOURCE_MAX_ATTEMPTS"),
])
def test_production_rejects_dangerous_authentication_limits(override, expected):
    with pytest.raises(RuntimeError, match=expected):
        validate_production_configuration(production_settings(**override))


def test_bounded_production_authentication_limits_are_accepted():
    validate_production_configuration(production_settings(
        SESSION_EXPIRY_SECONDS=3600, LOGIN_MAX_ATTEMPTS=5,
        LOGIN_LOCKOUT_SECONDS=300,
    ))



def test_shared_network_signup_budget_is_separate_from_password_guess_budget(monkeypatch):
    """A five-failure login lockout must not disable all school/office signups."""
    from apps.api.core import auth

    monkeypatch.setattr(auth, "_LOGIN_ATTEMPTS", {})
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", False)
    monkeypatch.setattr(auth.settings, "LOGIN_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(auth.settings, "REGISTRATION_SOURCE_MAX_ATTEMPTS", 30)
    shared_source = "registration-source:198.51.100.7"
    login_source = "source-account:198.51.100.7:founder@example.invalid"

    for _ in range(5):
        auth.check_login_throttle(shared_source)
        auth.record_failed_login(shared_source)
        auth.check_login_throttle(login_source)
        auth.record_failed_login(login_source)

    # The login key has exhausted its own password-guessing allowance.
    with pytest.raises(HTTPException) as throttled:
        auth.check_login_throttle(login_source)
    assert throttled.value.status_code == 429

    # Other users can still register behind the same NAT.
    auth.check_login_throttle(shared_source)
    for _ in range(25):
        auth.check_login_throttle(shared_source)
        auth.record_failed_login(shared_source)

    with pytest.raises(HTTPException) as throttled:
        auth.check_login_throttle(shared_source)
    assert throttled.value.status_code == 429
    # Different source is unaffected.
    auth.check_login_throttle("registration-source:203.0.113.8")



def test_explicit_canonical_https_api_origin_is_allowed_regardless_of_hostname():
    # Production configuration cannot determine who owns a syntactically
    # valid HTTPS domain. Runtime Host validation enforces the operator's
    # exact configured origin, not a hard-coded domain suffix.
    validate_production_configuration(production_settings(
        PUBLIC_API_ORIGIN="https://api.example.test.evil.test"
    ))


def test_login_source_budget_is_distinct_from_single_account_budget(monkeypatch):
    from apps.api.core import auth
    from fastapi import HTTPException

    monkeypatch.setattr(auth, "_LOGIN_ATTEMPTS", {})
    monkeypatch.setattr(auth.settings, "ONEBOARD_PRODUCTION_MODE", False)
    monkeypatch.setattr(auth.settings, "LOGIN_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(auth.settings, "LOGIN_SOURCE_MAX_ATTEMPTS", 60)
    source = "login-source:198.51.100.41"
    account = "source-account:198.51.100.41:founder@example.invalid"

    for _ in range(5):
        auth.check_login_throttle(account)
        auth.record_failed_login(account)
        auth.check_login_throttle(source)
        auth.record_failed_login(source)

    with pytest.raises(HTTPException) as locked:
        auth.check_login_throttle(account)
    assert locked.value.status_code == 429

    # Other accounts behind this NAT retain ample login capacity.
    for _ in range(55):
        auth.check_login_throttle(source)
        auth.record_failed_login(source)
    with pytest.raises(HTTPException) as locked:
        auth.check_login_throttle(source)
    assert locked.value.status_code == 429

    auth.check_login_throttle("login-source:203.0.113.41")
