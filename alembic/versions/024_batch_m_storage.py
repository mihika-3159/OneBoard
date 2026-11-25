"""Portable archives, bounded performance samples and tenant indexes."""
from alembic import op
import sqlalchemy as sa
from apps.api.models.operations import PortableArchive,PortableArchivePage,DatabasePerformanceSample
from apps.api.core.database import Base
revision="024_batch_m_storage"
down_revision="023_batch_l_providers"
branch_labels=None
depends_on=None
MODELS=(PortableArchive,PortableArchivePage,DatabasePerformanceSample)
REGISTRY="_oneboard_024_created_schema"
# Indexed tenant/keyset access and common child references.
INDEXES=(("tasks",("business_id","id")),("customers",("business_id","id")),("invoices",("business_id","id")),
("memory_documents",("business_id","id")),("memory_chunks",("business_id","document_id","id")),
("workflow_runs",("business_id","id")),("agent_runs",("business_id","id")),("audit_logs",("business_id","timestamp","id")),
("provider_records",("business_id","id")),("provider_deliveries",("business_id","state","id")),
("journal_entries",("business_id","period","id")),("sync_history",("integration_id","id")),
("approval_requests",("business_id","task_id")),("tasks",("business_id","goal_id")),("tasks",("business_id","decision_id")),
("settlement_evidence",("business_id","invoice_id")),("invoices",("business_id","customer_id")),
("support_tickets",("business_id","customer_id")))
def upgrade():
    conn=op.get_bind()
    op.create_table(REGISTRY,sa.Column("name",sa.String(100),primary_key=True))
    for model in MODELS:
        t=model.__table__
        if t.name not in sa.inspect(conn).get_table_names():
            t.create(conn)
            conn.execute(sa.text("INSERT INTO "+REGISTRY+" (name) VALUES (:n)"),{"n":t.name})
        if conn.dialect.name=="postgresql":
            name=t.name
            op.execute(f"ALTER TABLE public.{name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{name} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS oneboard_tenant_scope ON public.{name}")
            raw="nullif(current_setting('oneboard.tenant',true),'')"
            owner=f"(current_user=(SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public.{name}'::regclass))"
            pred=f"(business_id=(SELECT public.ob_scope_valid()) OR ({owner} AND ({raw} IS NULL OR business_id={raw})))"
            op.execute(f"CREATE POLICY oneboard_tenant_scope ON public.{name} USING {pred} WITH CHECK {pred}")
    for i,(table,columns) in enumerate(INDEXES):
        name=f"ix_m24_{i}_{table}"
        if name not in {x["name"] for x in sa.inspect(conn).get_indexes(table)}:
            op.create_index(name,table,list(columns))
            conn.execute(sa.text("INSERT INTO "+REGISTRY+" (name) VALUES (:n)"),{"n":name})
def downgrade():
    conn=op.get_bind()
    names={r[0] for r in conn.execute(sa.text("SELECT name FROM "+REGISTRY))}
    for model in MODELS:
        if conn.execute(sa.select(sa.func.count()).select_from(model.__table__)).scalar_one():
            raise RuntimeError("Portable archive history exists; restore a pre-upgrade backup")
    for i,(table,_) in reversed(list(enumerate(INDEXES))):
        name=f"ix_m24_{i}_{table}"
        if name in names:op.drop_index(name,table_name=table)
    for model in reversed(MODELS):
        if model.__table__.name in names:model.__table__.drop(conn)
    op.drop_table(REGISTRY)
