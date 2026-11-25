"""Exact legacy money and tenant accounting tables."""
from alembic import op
import sqlalchemy as sa
from decimal import Decimal,ROUND_HALF_UP
from apps.api.models.operations import JournalEntry,AccountingClose,BankStatementLine,FinanceForecast
revision="022_batch_k_finance"
down_revision="021_batch_j_memory"
branch_labels=None
depends_on=None
REGISTRY="_oneboard_022_created_schema"
MODELS=(JournalEntry,AccountingClose,BankStatementLine,FinanceForecast)
FIELDS={"businesses":("monthly_burn_rate","current_cash_balance"),"products":("price",),"customers":("mrr","contract_price"),"leads":("estimated_value",),"invoices":("amount",),"expenses":("amount",)}

def upgrade():
    conn=op.get_bind()
    op.create_table(REGISTRY,sa.Column("name",sa.String(90),primary_key=True))
    for table,fields in FIELDS.items():
        columns={c["name"]:c for c in sa.inspect(conn).get_columns(table)}
        change=[name for name in fields if not isinstance(columns[name]["type"],sa.Integer)]
        if not change:continue
        for name in change:
            # Explicitly reject corrupted/nonfinite/overflow legacy rows rather than silently zeroing them.
            for ident,value in conn.execute(sa.text(f"SELECT id,{name} FROM {table} WHERE {name} IS NOT NULL")):
                d=Decimal(str(value))
                if not d.is_finite() or abs(d)>Decimal("100000000000"):raise RuntimeError(f"Invalid legacy monetary record: {table}.{name} id={ident}")
            conn.execute(sa.text("INSERT INTO "+REGISTRY+" (name) VALUES (:name)"),{"name":table+"."+name})
        if conn.dialect.name=="postgresql":
            for name in change:
                op.alter_column(table,name,type_=sa.BigInteger(),postgresql_using=f"round({name}::numeric*100)::bigint")
        else:
            for name in change:
                conn.execute(sa.text(f"UPDATE {table} SET {name}=round({name}*100) WHERE {name} IS NOT NULL"))
            with op.batch_alter_table(table,recreate="always") as batch:
                for name in change:batch.alter_column(name,existing_type=columns[name]["type"],type_=sa.BigInteger())
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
    # Refuse destructive financial-history downgrade. Restore a pre-upgrade backup instead.
    raise RuntimeError("Financial exact-storage migration is irreversible; restore a pre-upgrade backup")
