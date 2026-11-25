"""Memory version lineage, index progress and feedback."""
from alembic import op
import sqlalchemy as sa
from apps.api.models.memory import MemoryDocumentState,MemoryRelevanceFeedback
revision="021_batch_j_memory"
down_revision="020_batch_i_schedule"
branch_labels=None
depends_on=None
REGISTRY="_oneboard_021_created_schema"
MODELS=(MemoryDocumentState,MemoryRelevanceFeedback)

def upgrade():
    conn=op.get_bind()
    op.create_table(REGISTRY,sa.Column("name",sa.String(90),primary_key=True))
    for model in MODELS:
        t=model.__table__
        if t.name not in sa.inspect(conn).get_table_names():
            t.create(conn)
            conn.execute(sa.text("INSERT INTO "+REGISTRY+" (name) VALUES (:name)"),{"name":t.name})
        if conn.dialect.name=="postgresql":
            name=t.name
            op.execute(f"ALTER TABLE public.{name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{name} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS oneboard_tenant_scope ON public.{name}")
            raw="nullif(current_setting('oneboard.tenant',true),'')"
            owner=f"(current_user=(SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public.{name}'::regclass))"
            pred=f"(business_id=(SELECT public.ob_scope_valid()) OR ({owner} AND ({raw} IS NULL OR business_id={raw})))"
            op.execute(f"CREATE POLICY oneboard_tenant_scope ON public.{name} USING {pred} WITH CHECK {pred}")

def downgrade():
    conn=op.get_bind()
    added={r[0] for r in conn.execute(sa.text("SELECT name FROM "+REGISTRY))}
    for model in reversed(MODELS):
        if model.__table__.name in added:model.__table__.drop(conn)
    op.drop_table(REGISTRY)
