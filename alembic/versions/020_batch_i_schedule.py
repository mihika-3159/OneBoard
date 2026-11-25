"""Bounded missed-slot scheduling policies."""
from alembic import op
import sqlalchemy as sa
revision="020_batch_i_schedule"
down_revision="019_batch_i_events"
branch_labels=None
depends_on=None
REGISTRY="_oneboard_020_added_columns"
COLUMNS=(("missed_policy",sa.String(20)),("missed_count",sa.Integer()))


def upgrade():
    conn=op.get_bind()
    op.create_table(REGISTRY,sa.Column("name",sa.String(90),primary_key=True))
    present={c["name"] for c in sa.inspect(conn).get_columns("workflow_schedules")}
    for name,kind in COLUMNS:
        if name not in present:
            op.add_column("workflow_schedules",sa.Column(name,kind,nullable=True))
            conn.execute(sa.text("INSERT INTO "+REGISTRY+" (name) VALUES (:name)"),{"name":name})


def downgrade():
    conn=op.get_bind()
    added={r[0] for r in conn.execute(sa.text("SELECT name FROM "+REGISTRY))}
    with op.batch_alter_table("workflow_schedules") as batch:
        for name,_ in COLUMNS:
            if name in added:batch.drop_column(name)
    op.drop_table(REGISTRY)
