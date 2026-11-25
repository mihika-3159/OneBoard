"""Opt-in derived-data retention; never prune financial or audit evidence."""
from alembic import op
import sqlalchemy as sa
revision="013_batch_e_retention"
down_revision="012_batch_e_roles"
branch_labels=None
depends_on=None
REGISTRY="_oneboard_013_added_columns"
COLUMNS=("resolved_alert_days","expired_session_days")
def upgrade():
    conn=op.get_bind()
    op.create_table(REGISTRY,sa.Column("name",sa.String(90),primary_key=True))
    present={c["name"] for c in sa.inspect(conn).get_columns("data_retention_policies")}
    for name in COLUMNS:
        if name not in present:
            op.add_column("data_retention_policies",sa.Column(name,sa.Integer(),nullable=True))
            conn.execute(sa.text("INSERT INTO "+REGISTRY+" (name) VALUES (:name)"),{"name":name})
def downgrade():
    conn=op.get_bind()
    added={r[0] for r in conn.execute(sa.text("SELECT name FROM "+REGISTRY))}
    for name in COLUMNS:
        if name in added:
            with op.batch_alter_table("data_retention_policies") as batch:
                batch.drop_column(name)
    op.drop_table(REGISTRY)
