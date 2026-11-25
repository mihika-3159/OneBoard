"""Persist council checkpoints and structured evidence-linked synthesis."""
from alembic import op
import sqlalchemy as sa

revision = "017_batch_h_council"
down_revision = "016_batch_f_relationships"
branch_labels = None
depends_on = None
REGISTRY = "_oneboard_017_added_columns"
COLUMNS = (("structured_synthesis", sa.JSON), ("checkpoint_at", sa.DateTime))


def upgrade():
    conn = op.get_bind()
    op.create_table(REGISTRY, sa.Column("name", sa.String(90), primary_key=True))
    present = {c["name"] for c in sa.inspect(conn).get_columns("council_meetings")}
    for name, kind in COLUMNS:
        if name not in present:
            op.add_column("council_meetings", sa.Column(name, kind(), nullable=True))
            conn.execute(sa.text("INSERT INTO " + REGISTRY + " (name) VALUES (:name)"), {"name": name})


def downgrade():
    conn = op.get_bind()
    added = {r[0] for r in conn.execute(sa.text("SELECT name FROM " + REGISTRY))}
    with op.batch_alter_table("council_meetings") as batch:
        for name, _ in COLUMNS:
            if name in added:
                batch.drop_column(name)
    op.drop_table(REGISTRY)
