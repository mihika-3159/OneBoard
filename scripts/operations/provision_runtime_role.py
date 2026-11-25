"""Owner-approved one-time PostgreSQL role provisioning; never run on import.

Run as migration/table owner with CREATEROLE, after migrations. The HTTP app
uses only the separate runtime DSN. Never give the runtime login owner grants.
Passwords are read from environment and never printed.
"""
import os
import re
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url

def provision(engine, role, password, context_key=None):
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,47}",role) or len(password)<24:
        raise ValueError("Runtime login requires safe identifier and strong password")
    from psycopg import sql
    from apps.api.core.database import Base
    import apps.api.models.business,apps.api.models.entities,apps.api.models.goals_tasks
    import apps.api.models.agent_council,apps.api.models.decision_evidence
    import apps.api.models.memory,apps.api.models.workflow,apps.api.models.integrations,apps.api.models.operations
    if not isinstance(context_key,bytes) or len(context_key)!=32:
        raise ValueError("Separate 32-byte tenant context key required")
    with engine.begin() as conn:
        stored=conn.execute(text("SELECT secret FROM oneboard_private.context_key WHERE singleton")).scalar_one_or_none()
        if stored is None:
            conn.execute(text("INSERT INTO oneboard_private.context_key(singleton,secret) VALUES (true,:key)"),{"key":context_key})
        elif bytes(stored)!=context_key:
            raise RuntimeError("Existing context key differs; explicit rotation required")
        if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"),{"role":role}).first():
            raise RuntimeError("Runtime role already exists; refusing to alter it")
        raw=conn.connection.driver_connection
        with raw.cursor() as cur:
            cur.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}").format(sql.Identifier(role),sql.Literal(password)))
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(conn.execute(text("SELECT current_database()")).scalar_one()),sql.Identifier(role)))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            for table in sorted(Base.metadata.tables):
                if table=="users":
                    cols=[sql.Identifier(c.name) for c in Base.metadata.tables[table].c if c.name not in ("hashed_password","api_key")]
                    cur.execute(sql.SQL("GRANT SELECT ({}) ON TABLE public.users TO {}").format(sql.SQL(",").join(cols),sql.Identifier(role)))
                    cur.execute(sql.SQL("GRANT INSERT,UPDATE,DELETE ON TABLE public.users TO {}").format(sql.Identifier(role)))
                else:
                    cur.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.{} TO {}").format(sql.Identifier(table),sql.Identifier(role)))
            cur.execute(sql.SQL("GRANT SELECT ON TABLE public.alembic_version TO {}").format(sql.Identifier(role)))
            for fn in ("ob_scope_valid()","ob_lookup_email(text)","ob_lookup_key(text)","ob_tenant_ids(text,integer)","ob_password_verifier(text)","ob_key_matches(text,text)","ob_unsafe_api_keys()"):
                cur.execute(sql.SQL("GRANT EXECUTE ON FUNCTION public."+fn+" TO {}").format(sql.Identifier(role)))

def main():
    if os.environ.get("ONEBOARD_ROLE_PROVISION_APPROVED")!="YES":
        raise SystemExit("Explicit owner approval required")
    url=make_url(os.environ["DATABASE_URL"])
    if url.drivername!="postgresql+psycopg":
        raise SystemExit("PostgreSQL psycopg migration-owner connection required")
    if url.host not in ("localhost","127.0.0.1","::1") and url.query.get("sslmode")!="verify-full":
        raise SystemExit("Remote provisioning requires verified TLS")
    engine=create_engine(url,echo=False)
    try:
        import base64
        provision(engine,os.environ["ONEBOARD_RUNTIME_ROLE"],os.environ["ONEBOARD_RUNTIME_PASSWORD"],base64.b64decode(os.environ["TENANT_CONTEXT_KEY"],validate=True))
    finally:
        engine.dispose()
    print("Restricted login provisioned. Configure runtime DSN separately; do not reuse migration credentials.")
if __name__=="__main__":
    main()
