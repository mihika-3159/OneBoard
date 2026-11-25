from apps.api.core.database import engine_options


def test_sqlite_uses_thread_override():
    assert engine_options("sqlite:///local.db") == {
        "connect_args": {"check_same_thread": False}
    }


def test_postgresql_uses_connection_health_check_without_sqlite_arguments():
    for url in (
        "postgresql://user:password@localhost/oneboard",
        "postgresql+psycopg://user:password@localhost/oneboard",
    ):
        options = engine_options(url)
        from apps.api.core.config import settings
        assert options == {"pool_pre_ping": True,"pool_size":settings.DB_POOL_SIZE,"max_overflow":settings.DB_MAX_OVERFLOW,"pool_timeout":settings.DB_POOL_TIMEOUT_SECONDS,"pool_recycle":settings.DB_POOL_RECYCLE_SECONDS,"connect_args":{"connect_timeout":settings.OPERATOR_DB_CONNECT_TIMEOUT}}
        assert "check_same_thread" not in options["connect_args"]
