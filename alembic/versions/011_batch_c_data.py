"""Indexed memory, settlement evidence, provider staging and retention."""
from alembic import op
import sqlalchemy as sa
from apps.api.models.operations import (SemanticVector, SettlementEvidence, ProviderCredential, ProviderIntent, DataRetentionPolicy)

revision = "011_batch_c_data"
down_revision = "010_batch_b_durability"
branch_labels = None
depends_on = None
MODELS = (SemanticVector, SettlementEvidence, ProviderCredential, ProviderIntent, DataRetentionPolicy)
REGISTRY = "_oneboard_011_created_schema"

def upgrade():
    conn = op.get_bind()
    op.create_table(REGISTRY, sa.Column("name", sa.String(90), primary_key=True))
    for model in MODELS:
        table = model.__table__
        if table.name not in sa.inspect(conn).get_table_names():
            table.create(conn)
            conn.execute(sa.text("INSERT INTO " + REGISTRY + " (name) VALUES (:name)"), {"name": table.name})
        if conn.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table.name} FORCE ROW LEVEL SECURITY")
            predicate = "(coalesce(current_setting('oneboard.tenant', true), '') = '' OR business_id = current_setting('oneboard.tenant', true))"
            op.execute(f"CREATE POLICY oneboard_tenant_scope ON {table.name} USING {predicate} WITH CHECK {predicate}")

def downgrade():
    conn = op.get_bind()
    created = {row[0] for row in conn.execute(sa.text("SELECT name FROM " + REGISTRY))}
    for model in reversed(MODELS):
        table = model.__table__
        if conn.dialect.name == "postgresql":
            op.execute(f"DROP POLICY oneboard_tenant_scope ON {table.name}")
            op.execute(f"ALTER TABLE {table.name} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table.name} DISABLE ROW LEVEL SECURITY")
        if table.name in created:
            table.drop(conn)
    op.drop_table(REGISTRY)
