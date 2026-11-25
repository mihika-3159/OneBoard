"""Repair missing model indexes and unique guarantees after legacy auth bootstrap.

Revision ID: 004_schema_indexes
Revises: 003_app_schema

Migration 001 created auth tables with a subset of the current model indexes.
Migration 003 deliberately preserved those tables, so create_all did not add
their missing indexes. Reconcile them in a versioned migration, without
dropping or rewriting existing tenant data.
"""
from alembic import op
import sqlalchemy as sa

from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.goals_tasks
import apps.api.models.entities
import apps.api.models.decision_evidence
import apps.api.models.agent_council
import apps.api.models.memory
import apps.api.models.workflow
import apps.api.models.integrations

revision = "004_schema_indexes"
down_revision = "003_app_schema"
branch_labels = None
depends_on = None

_REGISTRY = "_oneboard_004_created_indexes"


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if _REGISTRY in inspector.get_table_names():
        raise RuntimeError("Unexpected migration 004 registry exists before upgrade")
    op.create_table(
        _REGISTRY,
        sa.Column("table_name", sa.String(128), nullable=False),
        sa.Column("index_name", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint("table_name", "index_name"),
    )
    for table_name, table in Base.metadata.tables.items():
        inspector = sa.inspect(connection)
        existing = inspector.get_indexes(table_name)
        signatures = {
            (tuple(item["column_names"]), bool(item.get("unique")))
            for item in existing
        }
        unique_signatures = {
            tuple(sorted(item["column_names"]))
            for item in inspector.get_unique_constraints(table_name)
        }
        unique_signatures.update(
            tuple(sorted(item["column_names"]))
            for item in existing if item.get("unique")
        )
        for index in sorted(table.indexes, key=lambda item: item.name):
            columns = tuple(column.name for column in index.columns)
            signature = (columns, bool(index.unique))
            if signature in signatures or (
                index.unique and tuple(sorted(columns)) in unique_signatures
            ):
                continue
            op.create_index(index.name, table_name, list(columns), unique=index.unique)
            connection.execute(
                sa.text("INSERT INTO _oneboard_004_created_indexes VALUES (:table, :name)"),
                {"table": table_name, "name": index.name},
            )
            signatures.add(signature)
            if index.unique:
                unique_signatures.add(tuple(sorted(columns)))
        for constraint in table.constraints:
            if not isinstance(constraint, sa.UniqueConstraint):
                continue
            columns = tuple(column.name for column in constraint.columns)
            signature = tuple(sorted(columns))
            if signature in unique_signatures:
                continue
            name = constraint.name or ("uq_" + table_name + "_" + "_".join(columns))
            op.create_index(name, table_name, list(columns), unique=True)
            connection.execute(
                sa.text("INSERT INTO _oneboard_004_created_indexes VALUES (:table, :name)"),
                {"table": table_name, "name": name},
            )
            unique_signatures.add(signature)


def downgrade() -> None:
    connection = op.get_bind()
    if _REGISTRY not in sa.inspect(connection).get_table_names():
        raise RuntimeError("Cannot safely downgrade migration 004 without registry")
    rows = connection.execute(
        sa.text("SELECT table_name, index_name FROM _oneboard_004_created_indexes")
    ).all()
    for table_name, index_name in reversed(rows):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table(_REGISTRY)
