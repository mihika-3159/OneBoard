"""Tenant-scoped durable idempotency for workflow execution.

Revision ID: 007_workflow_idempotency
Revises: 006_api_key_hashing

Nullable keys preserve existing workflow history. Non-null keys are unique per
business, not globally; retries cannot create duplicate execution records.
No old runs are deleted, changed, or silently assigned idempotency tokens.
"""
from alembic import op
import sqlalchemy as sa

revision = "007_workflow_idempotency"
down_revision = "006_api_key_hashing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(128), nullable=True))
        batch.create_unique_constraint(
            "uq_workflow_run_tenant_idempotency",
            ["business_id", "idempotency_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_runs") as batch:
        batch.drop_constraint("uq_workflow_run_tenant_idempotency", type_="unique")
        batch.drop_column("idempotency_key")
