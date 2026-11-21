"""Persist login throttling across API processes.

Revision ID: 002_shared_login_throttle
Revises: 001_auth_isolation
"""
from alembic import op
import sqlalchemy as sa

revision = "002_shared_login_throttle"
down_revision = "001_auth_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "login_throttle_states" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "login_throttle_states",
            sa.Column("identifier_hash", sa.String(length=64), primary_key=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("window_started_at", sa.Float(), nullable=False),
        )


def downgrade() -> None:
    if "login_throttle_states" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("login_throttle_states")
