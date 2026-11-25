"""Durable job/outbox tables and PostgreSQL tenant relationship isolation."""
from alembic import op
import sqlalchemy as sa
from apps.api.models.operations import ScheduledJobLease, SideEffectOutbox

revision = "010_batch_b_durability"
down_revision = "009_resource_budgets"
branch_labels = None
depends_on = None
REGISTRY = "_oneboard_010_created_schema"

# PostgreSQL constraints reject new cross-tenant and orphan references.
# NOT VALID retains historical rows for explicit remediation rather than
# deleting user data. New writes are still checked by PostgreSQL.
RELATIONS = (
    ("memory_documents", "memory_chunks", "document_id", "memory"),
    ("workflow_definitions", "workflow_runs", "workflow_id", "workflow"),
    ("workflow_runs", "approval_requests", "workflow_run_id", "approval"),
    ("workflow_runs", "side_effect_outbox", "run_id", "outbox"),
)

def upgrade():
    conn = op.get_bind()
    op.create_table(REGISTRY, sa.Column("name", sa.String(90), primary_key=True))
    for model in (ScheduledJobLease, SideEffectOutbox):
        table = model.__table__
        if table.name not in sa.inspect(conn).get_table_names():
            table.create(conn)
            conn.execute(sa.text("INSERT INTO " + REGISTRY + " (name) VALUES (:name)"),
                         {"name": table.name})
    if conn.dialect.name == "postgresql":
        for parent in sorted({item[0] for item in RELATIONS}):
            op.execute(f"ALTER TABLE {parent} ADD CONSTRAINT uq_b10_{parent}_tenant_id UNIQUE (business_id,id)")
        for parent, child, column, key in RELATIONS:
            cascade = " ON DELETE CASCADE" if key == "outbox" else ""
            op.execute(f"ALTER TABLE {child} ADD CONSTRAINT fk_b10_{key} "
                       f"FOREIGN KEY (business_id,{column}) REFERENCES {parent} (business_id,id)"
                       f"{cascade} NOT VALID")

def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for parent, child, column, key in reversed(RELATIONS):
            op.drop_constraint("fk_b10_" + key, child, type_="foreignkey")
        for parent in sorted({item[0] for item in RELATIONS}):
            op.drop_constraint("uq_b10_" + parent + "_tenant_id", parent, type_="unique")
    created = {row[0] for row in conn.execute(sa.text("SELECT name FROM " + REGISTRY))}
    for model in (SideEffectOutbox, ScheduledJobLease):
        if model.__table__.name in created:
            model.__table__.drop(conn)
    op.drop_table(REGISTRY)
