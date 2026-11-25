"""Account MFA/recovery state and chained security events."""
from alembic import op
import sqlalchemy as sa
from apps.api.models.business import AccountSecurity,SecurityEvent
from sqlalchemy import text

revision="014_batch_f_security"
down_revision="013_batch_e_retention"
branch_labels=None
depends_on=None
REGISTRY="_oneboard_014_created_schema"
MODELS=(AccountSecurity,SecurityEvent)
def upgrade():
    conn=op.get_bind()
    op.create_table(REGISTRY,sa.Column("name",sa.String(90),primary_key=True))
    for model in MODELS:
        t=model.__table__
        if t.name not in sa.inspect(conn).get_table_names():
            t.create(conn)
            conn.execute(text("INSERT INTO "+REGISTRY+" (name) VALUES (:name)"),{"name":t.name})
        if conn.dialect.name=="postgresql":
            op.execute(f"ALTER TABLE {t.name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {t.name} FORCE ROW LEVEL SECURITY")
            predicate=f"(business_id = nullif(current_setting('oneboard.tenant',true),'') OR (nullif(current_setting('oneboard.tenant',true),'') IS NULL AND current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public.{t.name}'::regclass)))"
            op.execute(f"CREATE POLICY oneboard_tenant_scope ON {t.name} USING {predicate} WITH CHECK {predicate}")
    if conn.dialect.name=="postgresql":
        op.execute("ALTER TABLE users ADD CONSTRAINT uq_f_users_tenant_id UNIQUE (business_id,id)")
        op.execute("ALTER TABLE account_security ADD CONSTRAINT fk_f_security_user FOREIGN KEY (business_id,user_id) REFERENCES users(business_id,id) ON DELETE CASCADE NOT VALID")
        op.execute("ALTER TABLE security_events ADD CONSTRAINT uq_f_security_sequence UNIQUE (business_id,sequence)")
def downgrade():
    conn=op.get_bind()
    if conn.dialect.name=="postgresql":
        op.execute("ALTER TABLE security_events DROP CONSTRAINT uq_f_security_sequence")
        op.execute("ALTER TABLE account_security DROP CONSTRAINT fk_f_security_user")
        op.execute("ALTER TABLE users DROP CONSTRAINT uq_f_users_tenant_id")
        for model in MODELS:
            t=model.__table__
            op.execute(f"DROP POLICY oneboard_tenant_scope ON {t.name}")
            op.execute(f"ALTER TABLE {t.name} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {t.name} DISABLE ROW LEVEL SECURITY")
    created={r[0] for r in conn.execute(text("SELECT name FROM "+REGISTRY))}
    for model in reversed(MODELS):
        if model.__table__.name in created:
            model.__table__.drop(conn)
    op.drop_table(REGISTRY)
