"""Production must reject a stamped-but-incomplete schema without creating tables."""
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from apps.api.core import database
from apps.api.core.config import settings


def _stamped_incomplete_engine():
    root = Path(__file__).resolve().parents[2]
    head_revision = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_current_head()
    assert head_revision is not None
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        ))
        connection.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES (:revision)"
        ), {"revision": head_revision})
    return engine


def test_production_rejects_missing_tables_even_if_alembic_claims_latest(monkeypatch):
    engine = _stamped_incomplete_engine()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
    try:
        with pytest.raises(RuntimeError, match="missing required application tables"):
            database.init_db()
        with engine.connect() as connection:
            tables = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        assert not any(row[0] == "users" for row in tables)
    finally:
        engine.dispose()


def test_production_schema_validation_never_calls_create_all(monkeypatch):
    engine = _stamped_incomplete_engine()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(settings, "ONEBOARD_PRODUCTION_MODE", True)
    def forbidden_create_all(*args, **kwargs):
        raise AssertionError("Production must never implicitly create application tables")
    monkeypatch.setattr(database.Base.metadata, "create_all", forbidden_create_all)
    try:
        with pytest.raises(RuntimeError, match="missing required application tables"):
            database.init_db()
    finally:
        engine.dispose()
