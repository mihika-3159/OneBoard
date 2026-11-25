"""Durable agent runtime; preserve legacy runs and idempotent bootstrap."""
from alembic import op
import sqlalchemy as sa
revision = "018_batch_h_agent_runs"
down_revision = "017_batch_h_council"
branch_labels = None
depends_on = None
REGISTRY = "_oneboard_018_added_columns"
INDEX = "uq_agent_run_tenant_key"
COLUMNS = (
    ("idempotency_key", sa.String(128)), ("request_hash", sa.String(64)),
    ("status", sa.String(30)), ("next_step", sa.Integer()), ("attempt_count", sa.Integer()),
    ("lease_owner", sa.String(36)), ("lease_until", sa.DateTime()),
    ("deadline", sa.DateTime()), ("checkpoint_at", sa.DateTime()),
)


def upgrade():
    conn = op.get_bind()
    op.create_table(REGISTRY, sa.Column("name", sa.String(90), primary_key=True))
    present = {c["name"] for c in sa.inspect(conn).get_columns("agent_runs")}
    for name, kind in COLUMNS:
        if name not in present:
            op.add_column("agent_runs", sa.Column(name, kind, nullable=True))
            conn.execute(sa.text("INSERT INTO " + REGISTRY + " (name) VALUES (:name)"), {"name": name})
    if INDEX not in {i["name"] for i in sa.inspect(conn).get_indexes("agent_runs")}:
        op.create_index(INDEX, "agent_runs", ["business_id", "idempotency_key"], unique=True)
        conn.execute(sa.text("INSERT INTO " + REGISTRY + " (name) VALUES (:name)"), {"name": INDEX})


def downgrade():
    conn = op.get_bind()
    added = {r[0] for r in conn.execute(sa.text("SELECT name FROM " + REGISTRY))}
    if INDEX in added:
        op.drop_index(INDEX, table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        for name, _ in COLUMNS:
            if name in added:
                batch.drop_column(name)
    op.drop_table(REGISTRY)
