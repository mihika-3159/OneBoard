"""Production runtime is a separate non-owner PostgreSQL login.

The auth directory and global coordination tables are explicitly unscoped
because authentication and scheduler discovery precede a tenant context.
Business content tables require a tenant or their maintenance owner.
"""
from sqlalchemy import text

def verify_runtime_role(engine):
    if engine.dialect.name!="postgresql":
        raise RuntimeError("Production requires a restricted PostgreSQL runtime role")
    with engine.connect() as conn:
        role=conn.execute(text("""SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication
            FROM pg_roles WHERE rolname=current_user""")).one()
        if any(role) or conn.execute(text("SELECT has_schema_privilege(current_user,'public','CREATE')")).scalar_one():
            raise RuntimeError("Production runtime role has prohibited database privileges")
        unsafe=conn.execute(text("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p')
            AND pg_has_role(current_user,c.relowner,'MEMBER') LIMIT 1""")).first()
        if unsafe:
            raise RuntimeError("Production runtime must not own or inherit ownership of application tables")
        # Deny SET ROLE into any privileged role, including predefined
        # broad-read/write roles. This runtime needs no role memberships.
        inherited=conn.execute(text("""SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
            WHERE r.rolname=current_user LIMIT 1""")).first()
        if inherited:
            raise RuntimeError("Production runtime role must have no role memberships")
        from apps.api.core.database import Base
        expected=sorted({t.name for t in Base.metadata.tables.values() if "business_id" in t.c}|{"businesses","sync_history"})
        from apps.api.core.tenant_context import apply_context,context_key
        context_key()
        from apps.api.services.account_security import _key
        _key()
        apply_context(conn,"oneboard-startup-probe")
        if conn.execute(text("SELECT public.ob_scope_valid()")).scalar_one()!="oneboard-startup-probe":
            raise RuntimeError("Runtime tenant context signing key does not match database")
        if conn.execute(text("SELECT has_schema_privilege(current_user,'oneboard_private','USAGE')")).scalar_one():
            raise RuntimeError("Runtime may not access private context schema")
        for column in ("hashed_password","api_key"):
            if conn.execute(text("SELECT has_column_privilege(current_user,'public.users',:column,'SELECT')"),{"column":column}).scalar_one():
                raise RuntimeError("Direct credential-verifier SELECT privileges are prohibited")
        for table in expected:
            rows=conn.execute(text("""SELECT c.relrowsecurity,c.relforcerowsecurity,p.polpermissive,
                 pg_get_expr(p.polqual,c.oid),pg_get_expr(p.polwithcheck,c.oid),p.polname,p.polcmd
                 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                 JOIN pg_policy p ON p.polrelid=c.oid
                 WHERE n.nspname='public' AND c.relname=:table"""),{"table":table}).all()
            if len(rows)!=1 or not all(rows[0][:3]) or rows[0][5:]!=("oneboard_tenant_scope","*") or not all(
                    "ob_scope_valid" in (expr or "").lower() and "current_user" in (expr or "").lower()
                    for expr in rows[0][3:5]):
                raise RuntimeError("Production tenant policy missing or unexpected")
