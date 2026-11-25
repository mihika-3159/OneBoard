"""Adversarial migration lock tests.

These tests do not claim to reproduce PostgreSQL multi-process contention;
that requires an isolated real PostgreSQL integration environment.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.api.core.migration_lock import (
    ONEBOARD_MIGRATION_LOCK_ID,
    acquire_migration_lock,
)


def fake_connection(dialect, in_transaction=True):
    connection = Mock()
    connection.dialect = SimpleNamespace(name=dialect)
    connection.in_transaction.return_value = in_transaction
    return connection


def test_postgres_lock_uses_transaction_scoped_advisory_lock():
    connection = fake_connection("postgresql")
    assert acquire_migration_lock(connection) is True
    connection.execute.assert_called_once()
    statement, params = connection.execute.call_args.args
    assert str(statement) == "SELECT pg_advisory_xact_lock(:lock_id)"
    assert params == {"lock_id": ONEBOARD_MIGRATION_LOCK_ID}
    assert isinstance(ONEBOARD_MIGRATION_LOCK_ID, int)
    assert -(2 ** 63) <= ONEBOARD_MIGRATION_LOCK_ID < 2 ** 63


def test_postgres_rejects_lock_without_transaction():
    connection = fake_connection("postgresql", in_transaction=False)
    with pytest.raises(RuntimeError, match="active transaction"):
        acquire_migration_lock(connection)
    connection.execute.assert_not_called()


@pytest.mark.parametrize("dialect", ["sqlite", "mysql"])
def test_non_postgres_does_not_attempt_postgres_lock(dialect):
    connection = fake_connection(dialect, in_transaction=False)
    assert acquire_migration_lock(connection) is False
    connection.execute.assert_not_called()


def test_lock_failure_is_not_swallowed():
    connection = fake_connection("postgresql")
    connection.execute.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        acquire_migration_lock(connection)
