from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
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
        return

    Base.metadata.create_all(bind=engine)
