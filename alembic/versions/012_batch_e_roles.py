"""Fail-closed runtime RLS, explicit owner maintenance and durable schedules."""
from alembic import op
import sqlalchemy as sa
from apps.api.core.database import Base
from apps.api.models.operations import WorkflowSchedule,SchedulerCursor

revision="012_batch_e_roles"
down_revision="011_batch_c_data"
branch_labels=None
depends_on=None
REGISTRY="_oneboard_012_created_schema"
AUTH={"users","business_memberships","user_sessions"}

def scoped_tables():
    return sorted(t.name for t in Base.metadata.tables.values()
                  if "business_id" in t.c and t.name not in AUTH)

def owner_predicate(table):
    # A restored database may have a different table owner; do not bake a
    # deployment-specific login or superuser into the policy.
    return f"(nullif(current_setting('oneboard.tenant',true),'') IS NULL AND current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public.{table}'::regclass))"

def upgrade():
    conn=op.get_bind()
    op.create_table(REGISTRY,sa.Column("name",sa.String(90),primary_key=True))
    for model in (WorkflowSchedule,SchedulerCursor):
        t=model.__table__
        if t.name not in sa.inspect(conn).get_table_names():
            t.create(conn)
            conn.execute(sa.text("INSERT INTO "+REGISTRY+" (name) VALUES (:name)"),{"name":t.name})
    if conn.dialect.name=="postgresql":
        for table in scoped_tables():
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS oneboard_tenant_scope ON {table}")
            predicate=f"(business_id = nullif(current_setting('oneboard.tenant',true),'') OR {owner_predicate(table)})"
            op.execute(f"CREATE POLICY oneboard_tenant_scope ON {table} USING {predicate} WITH CHECK {predicate}")
        # Indirect tenant ownership, formerly outside the policy inventory.
        table="sync_history"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        predicate=f"(EXISTS (SELECT 1 FROM integration_accounts i WHERE i.id=integration_id AND i.business_id=nullif(current_setting('oneboard.tenant',true),'')) OR {owner_predicate(table)})"
        op.execute(f"CREATE POLICY oneboard_tenant_scope ON {table} USING {predicate} WITH CHECK {predicate}")
        op.execute("ALTER TABLE workflow_schedules ADD CONSTRAINT fk_e_schedule_tenant FOREIGN KEY (business_id,workflow_id) REFERENCES workflow_definitions(business_id,id) ON DELETE CASCADE NOT VALID")

def downgrade():
    conn=op.get_bind()
    if conn.dialect.name=="postgresql":
        op.execute("ALTER TABLE workflow_schedules DROP CONSTRAINT fk_e_schedule_tenant")
        for table in scoped_tables()+["sync_history"]:
            op.execute(f"DROP POLICY oneboard_tenant_scope ON {table}")
            if table in ("workflow_schedules","sync_history"):
                op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
                op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
            else:
                predicate="(coalesce(current_setting('oneboard.tenant',true),'') = '' OR business_id = current_setting('oneboard.tenant',true))"
                op.execute(f"CREATE POLICY oneboard_tenant_scope ON {table} USING {predicate} WITH CHECK {predicate}")
    created={row[0] for row in conn.execute(sa.text("SELECT name FROM "+REGISTRY))}
    for model in (WorkflowSchedule,SchedulerCursor):
        if model.__table__.name in created:
            model.__table__.drop(conn)
    op.drop_table(REGISTRY)
