from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from apps.api.core.config import settings
import os

# Ensure data directory exists
os.makedirs(settings.DATA_DIR, exist_ok=True)

def engine_options(database_url: str) -> dict:
    """SQLite needs a thread override; PostgreSQL must not receive SQLite-only options."""
    if database_url.startswith("sqlite:"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


engine = create_engine(settings.DATABASE_URL, **engine_options(settings.DATABASE_URL))

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def scope_tenant_session(db, tenant):
    """Pin an authenticated session to one tenant, including after commit."""
    if not isinstance(db, Session):
        return  # unit-test doubles do not own database connections
    if not tenant:
        raise ValueError("Tenant required")
    previous = db.info.get("oneboard_tenant")
    if previous is not None and previous != tenant:
        raise PermissionError("Cannot switch tenant on authenticated session")
    db.info["oneboard_tenant"] = tenant
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT set_config('oneboard.tenant', :tenant, true)"),
                   {"tenant": tenant})


@event.listens_for(Session, "after_begin")
def _restore_tenant_scope(session, transaction, connection):
    tenant = session.info.get("oneboard_tenant")
    if tenant and connection.dialect.name == "postgresql":
        connection.execute(text("SELECT set_config('oneboard.tenant', :tenant, true)"),
                           {"tenant": tenant})


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # Import every model before inspecting its metadata. A database stamped
    # at Alembic head is not safe to serve if application tables are missing.
    import apps.api.models.business
    import apps.api.models.goals_tasks
    import apps.api.models.entities
    import apps.api.models.decision_evidence
    import apps.api.models.agent_council
    import apps.api.models.memory
    import apps.api.models.workflow
    import apps.api.models.integrations
    import apps.api.models.operations

    if settings.ONEBOARD_PRODUCTION_MODE:
        # Never create or silently repair an unversioned production schema.
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from alembic.config import Config
        from sqlalchemy import inspect

        alembic_cfg = Config(str(settings.BASE_DIR / "alembic.ini"))
        expected_heads = set(ScriptDirectory.from_config(alembic_cfg).get_heads())
        with engine.connect() as connection:
            actual_heads = set(MigrationContext.configure(connection).get_current_heads())
            if not actual_heads or actual_heads != expected_heads:
                raise RuntimeError(
                    "Production database migration revision mismatch; run alembic upgrade head before startup"
                )
            inspector = inspect(connection)
            present = set(inspector.get_table_names())
            missing_tables = sorted(set(Base.metadata.tables) - present)
            if missing_tables:
                raise RuntimeError(
                    "Production database missing required application tables: "
                    + ", ".join(missing_tables)
                )
            missing_columns = []
            for name, table in Base.metadata.tables.items():
                actual_columns = {column["name"] for column in inspector.get_columns(name)}
                for column in table.columns:
                    if column.name not in actual_columns:
                        missing_columns.append(f"{name}.{column.name}")
            if missing_columns:
                raise RuntimeError(
                    "Production database missing required application columns: "
                    + ", ".join(sorted(missing_columns))
                )
            # A stamped schema may still be missing security-critical lookup
            # indexes or uniqueness guarantees after a partial/manual migration.
            from sqlalchemy import UniqueConstraint
            missing_indexes = []
            missing_uniques = []
            for name, table in Base.metadata.tables.items():
                actual_indexes = inspector.get_indexes(name)
                indexed = {
                    (tuple(item["column_names"]), bool(item.get("unique")))
                    for item in actual_indexes
                }
                unique_columns = {
                    tuple(sorted(item["column_names"]))
                    for item in inspector.get_unique_constraints(name)
                }
                unique_columns.update(
                    tuple(sorted(item["column_names"]))
                    for item in actual_indexes if item.get("unique")
                )
                for index in table.indexes:
                    signature = (
                        tuple(column.name for column in index.columns),
                        bool(index.unique),
                    )
                    if signature not in indexed:
                        missing_indexes.append(f"{name}:{signature}")
                for constraint in table.constraints:
                    if isinstance(constraint, UniqueConstraint):
                        columns = tuple(sorted(c.name for c in constraint.columns))
                        if columns not in unique_columns:
                            missing_uniques.append(f"{name}:{columns}")
            if missing_indexes or missing_uniques:
                raise RuntimeError(
                    "Production database missing required indexes/unique constraints: "
                    + ", ".join(sorted(missing_indexes + missing_uniques))
                )
            # The legacy auth migration omitted foreign keys entirely.
            # Revision parity and indexes are not proof that session/user
            # ownership is enforced by the production database.
            missing_foreign_keys = []
            for name, table in Base.metadata.tables.items():
                reflected = inspector.get_foreign_keys(name)
                for constraint in table.foreign_key_constraints:
                    local_cols = tuple(element.parent.name for element in constraint.elements)
                    remote_cols = tuple(element.column.name for element in constraint.elements)
                    remote_table = constraint.elements[0].column.table.name
                    expected_delete = (constraint.ondelete or "").upper()
                    if not any(
                        tuple(fk.get("constrained_columns") or ()) == local_cols
                        and fk.get("referred_table") == remote_table
                        and tuple(fk.get("referred_columns") or ()) == remote_cols
                        and ((fk.get("options") or {}).get("ondelete") or "").upper() == expected_delete
                        for fk in reflected
                    ):
                        missing_foreign_keys.append(
                            f"{name}:{local_cols}->{remote_table}{remote_cols} "
                            f"ON DELETE {expected_delete or 'DEFAULT'}"
                        )
            if missing_foreign_keys:
                raise RuntimeError(
                    "Production database missing required foreign-key constraints: "
                    + ", ".join(sorted(missing_foreign_keys))
                )
            # A manually stamped revision 006 could still contain plaintext
            # API keys. Check the actual data without returning or logging a
            # credential. Postgres translate() strips all valid hex digits.
            if connection.dialect.name == "postgresql":
                unsafe_key = connection.execute(text(
                    "SELECT 1 FROM users WHERE api_key IS NOT NULL "
                    "AND (api_key NOT LIKE 'sha256:%' OR length(api_key) <> 71 "
                    "OR translate(substring(api_key from 8), "
                    "'0123456789abcdef', '') <> '') LIMIT 1"
                )).first()
                if unsafe_key is not None:
                    raise RuntimeError(
                        "Production database contains non-hashed API credentials; "
                        "complete migration 006 and rotate invalid legacy keys"
                    )
        return

    Base.metadata.create_all(bind=engine)
