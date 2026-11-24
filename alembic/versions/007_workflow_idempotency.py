"""Reconcile tenant-scoped workflow idempotency on legacy PostgreSQL.

Revision ID: 007_workflow_idempotency
Revises: 006_api_key_hashing

Migration 003 bootstraps from current model metadata, so a fresh database
may already contain the column and unique constraint. Existing databases
may not. Track only objects newly created by *this* revision to preserve
preexisting constraints during rollback.
"""
from alembic import op
import sqlalchemy as sa

revision = "007_workflow_idempotency"
down_revision = "006_api_key_hashing"
branch_labels = None
depends_on = None

_REGISTRY = "_oneboard_007_created_schema"
_TABLE = "workflow_runs"
_UNIQUE = "uq_workflow_run_tenant_idempotency"


def _has_unique(conn):
    inspector = sa.inspect(conn)
    columns = ["business_id", "idempotency_key"]
    return any(
        sorted(item.get("column_names") or []) == sorted(columns)
        for item in (
            inspector.get_unique_constraints(_TABLE)
            + [i for i in inspector.get_indexes(_TABLE) if i.get("unique")]
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    if _REGISTRY in sa.inspect(conn).get_table_names():
        raise RuntimeError("Unexpected migration 007 schema registry")
    op.create_table(_REGISTRY, sa.Column("name", sa.String(32), primary_key=True))

    columns = {item["name"] for item in sa.inspect(conn).get_columns(_TABLE)}
    if "idempotency_key" not in columns:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column("idempotency_key", sa.String(128), nullable=True))
        conn.execute(sa.text(
            "INSERT INTO _oneboard_007_created_schema (name) VALUES ('column')"
        ))

    if not _has_unique(conn):
        with op.batch_alter_table(_TABLE) as batch:
            batch.create_unique_constraint(_UNIQUE, ["business_id", "idempotency_key"])
        conn.execute(sa.text(
            "INSERT INTO _oneboard_007_created_schema (name) VALUES ('unique')"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    if _REGISTRY not in sa.inspect(conn).get_table_names():
        raise RuntimeError("Cannot safely downgrade 007 without schema registry")
    objects = {
        row[0] for row in conn.execute(
            sa.text("SELECT name FROM _oneboard_007_created_schema")
        ).all()
    }
    if "unique" in objects:
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_constraint(_UNIQUE, type_="unique")
    if "column" in objects:
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column("idempotency_key")
    op.drop_table(_REGISTRY)
