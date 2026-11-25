"""Signed transaction-bound scope and ID-only pre-auth directory."""
from alembic import op
from apps.api.core.database import Base
revision="015_batch_f_context"
down_revision="014_batch_f_security"
branch_labels=None
depends_on=None
DIRECTORY=("businesses","users","business_memberships","user_sessions")
FUNCTIONS=("ob_scope_valid()","ob_lookup_email(text)","ob_lookup_key(text)","ob_tenant_ids(text,integer)","ob_password_verifier(text)","ob_key_matches(text,text)","ob_unsafe_api_keys()")
def tables():
    return sorted({t.name for t in Base.metadata.tables.values() if "business_id" in t.c}|set(DIRECTORY)|{"sync_history"})
def owner(table):
    return f"(current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public.{table}'::regclass))"
def upgrade():
    if op.get_bind().dialect.name!="postgresql": return
    op.execute("CREATE SCHEMA oneboard_private")
    op.execute("REVOKE ALL ON SCHEMA oneboard_private FROM PUBLIC")
    op.execute("CREATE TABLE oneboard_private.context_key (singleton boolean PRIMARY KEY CHECK(singleton), secret bytea NOT NULL CHECK(octet_length(secret)=32))")
    op.execute("REVOKE ALL ON oneboard_private.context_key FROM PUBLIC")
    op.execute("""CREATE FUNCTION public.ob_scope_valid() RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,oneboard_private AS $$
    DECLARE tenant text; proof text; key_bytes bytea; inner_pad bytea; outer_pad bytea; i integer; msg bytea;
    BEGIN
      tenant:=nullif(current_setting('oneboard.tenant',true),'');
      proof:=nullif(current_setting('oneboard.proof',true),'');
      IF tenant IS NULL OR length(tenant)>36 OR proof IS NULL OR proof !~ '^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
      SELECT secret INTO key_bytes FROM oneboard_private.context_key WHERE singleton;
      IF key_bytes IS NULL THEN RETURN NULL; END IF;
      inner_pad:=decode(repeat('36',64),'hex'); outer_pad:=decode(repeat('5c',64),'hex');
      FOR i IN 0..31 LOOP
        inner_pad:=set_byte(inner_pad,i,get_byte(key_bytes,i) # 54);
        outer_pad:=set_byte(outer_pad,i,get_byte(key_bytes,i) # 92);
      END LOOP;
      msg:=convert_to(tenant||':'||pg_backend_pid()::text||':'||txid_current()::text,'UTF8');
      IF encode(sha256(outer_pad||sha256(inner_pad||msg)),'hex')=proof THEN RETURN tenant; END IF;
      RETURN NULL;
    END $$""")
    for table in tables():
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS oneboard_tenant_scope ON public.{table}")
        raw="nullif(current_setting('oneboard.tenant',true),'')"
        signed="(SELECT public.ob_scope_valid())"
        if table=="sync_history":
            predicate=f"(({owner(table)} AND {raw} IS NULL) OR EXISTS (SELECT 1 FROM public.integration_accounts i WHERE i.id=integration_id AND (i.business_id={signed} OR ({owner(table)} AND i.business_id={raw}))))"
        else:
            column="id" if table=="businesses" else "business_id"
            predicate=f"({column}={signed} OR ({owner(table)} AND ({raw} IS NULL OR {column}={raw})))"
        op.execute(f"CREATE POLICY oneboard_tenant_scope ON public.{table} USING {predicate} WITH CHECK {predicate}")
    op.execute("""CREATE FUNCTION public.ob_lookup_email(value text) RETURNS TABLE(uid text,tenant text)
      LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public SET oneboard.tenant='' SET oneboard.proof=''
      AS $$ SELECT id::text,business_id::text FROM public.users WHERE email=value AND length(value)<=255 LIMIT 1 $$""")
    op.execute("""CREATE FUNCTION public.ob_lookup_key(value text) RETURNS TABLE(uid text,tenant text)
      LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public SET oneboard.tenant='' SET oneboard.proof=''
      AS $$ SELECT id::text,business_id::text FROM public.users WHERE api_key=value AND value ~ '^sha256:[a-f0-9]{64}$' AND is_active IS TRUE LIMIT 1 $$""")
    op.execute("""CREATE FUNCTION public.ob_tenant_ids(after_id text,max_rows integer) RETURNS SETOF text
      LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public SET oneboard.tenant='' SET oneboard.proof=''
      AS $$ SELECT id::text FROM public.businesses WHERE id>after_id ORDER BY id LIMIT greatest(0,least(max_rows,1000)) $$""")
    op.execute("""CREATE FUNCTION public.ob_password_verifier(uid text) RETURNS text
      LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public
      AS $f$ SELECT hashed_password::text FROM public.users WHERE id=uid AND business_id=public.ob_scope_valid() AND is_active IS TRUE LIMIT 1 $f$""")
    op.execute("""CREATE FUNCTION public.ob_key_matches(uid text,value text) RETURNS boolean
      LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public
      AS $f$ SELECT EXISTS(SELECT 1 FROM public.users WHERE id=uid AND business_id=public.ob_scope_valid() AND is_active IS TRUE AND api_key=value AND NOT EXISTS (SELECT 1 FROM public.account_security a WHERE a.user_id=uid AND a.business_id=public.ob_scope_valid() AND a.api_key_expires_at<=timezone('UTC',now()))) $f$""")
    op.execute("""CREATE FUNCTION public.ob_unsafe_api_keys() RETURNS boolean
      LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public SET oneboard.tenant='' SET oneboard.proof=''
      AS $f$ SELECT EXISTS(SELECT 1 FROM public.users WHERE api_key IS NOT NULL AND api_key !~ '^sha256:[a-f0-9]{64}$') $f$""")
    for fn in FUNCTIONS: op.execute(f"REVOKE ALL ON FUNCTION public.{fn} FROM PUBLIC")

def downgrade():
    if op.get_bind().dialect.name!="postgresql": return
    import sqlalchemy as sa
    for table in set(tables()) & set(sa.inspect(op.get_bind()).get_table_names()):
        op.execute(f"DROP POLICY oneboard_tenant_scope ON public.{table}")
        if table in DIRECTORY:
            op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        else:
            raw="nullif(current_setting('oneboard.tenant',true),'')"
            pred=f"(business_id={raw} OR ({owner(table)} AND {raw} IS NULL))" if table!="sync_history" else f"(EXISTS (SELECT 1 FROM public.integration_accounts i WHERE i.id=integration_id AND i.business_id={raw}) OR ({owner(table)} AND {raw} IS NULL))"
            op.execute(f"CREATE POLICY oneboard_tenant_scope ON public.{table} USING {pred} WITH CHECK {pred}")
    for fn in reversed(FUNCTIONS): op.execute(f"DROP FUNCTION public.{fn}")
    op.execute("DROP TABLE oneboard_private.context_key")
    op.execute("DROP SCHEMA oneboard_private")
