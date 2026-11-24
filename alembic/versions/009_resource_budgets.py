"""Tenant resource windows (PostgreSQL cross-worker limits).

Revision ID: 009_resource_budgets
Revises: 008_operational_durability

The bootstrap migration may create the table directly via model metadata.
Only remove the table on downgrade if this revision actually created it.
"""
from alembic import op
import sqlalchemy as sa

revision = "009_resource_budgets"
down_revision = "008_operational_durability"
branch_labels = None
depends_on = None

REGISTRY = "_oneboard_009_created_schema"


def upgrade():
    conn = op.get_bind()
    if REGISTRY in sa.inspect(conn).get_table_names():
        raise RuntimeError("Migration 009 journal already exists")
    op.create_table(REGISTRY, sa.Column("name", sa.String(48), primary_key=True))
    if "tenant_resource_windows" not in sa.inspect(conn).get_table_names():
        op.create_table(
            "tenant_resource_windows",
            sa.Column("business_id", sa.String(36), primary_key=True),
            sa.Column("resource", sa.String(60), primary_key=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("window_started_at", sa.Float(), nullable=False),
        )
        conn.execute(sa.text(
            "INSERT INTO _oneboard_009_created_schema (name) VALUES ('table')"
        ))


def downgrade():
    conn = op.get_bind()
    if REGISTRY not in sa.inspect(conn).get_table_names():
        raise RuntimeError("Missing migration 009 journal")
    created = conn.execute(
        sa.text("SELECT name FROM _oneboard_009_created_schema WHERE name='table'")
    ).first()
    if created:
        op.drop_table("tenant_resource_windows")
    op.drop_table(REGISTRY)
