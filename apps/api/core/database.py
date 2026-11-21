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
    if settings.ONEBOARD_PRODUCTION_MODE:
        # Never create an unversioned production schema. Operators must apply
        # and verify Alembic migrations before exposing the service.
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from alembic.config import Config
        from pathlib import Path

        alembic_cfg = Config(str(settings.BASE_DIR / 'alembic.ini'))
        script = ScriptDirectory.from_config(alembic_cfg)
        expected_heads = set(script.get_heads())
        with engine.connect() as connection:
            actual_heads = set(MigrationContext.configure(connection).get_current_heads())
        if not actual_heads or actual_heads != expected_heads:
            raise RuntimeError(
                'Production database migration revision mismatch; run alembic upgrade head before startup'
            )
        return

    import apps.api.models.business
    import apps.api.models.goals_tasks
    import apps.api.models.entities
    import apps.api.models.decision_evidence
    import apps.api.models.agent_council
    import apps.api.models.memory
    import apps.api.models.workflow
    import apps.api.models.integrations
    Base.metadata.create_all(bind=engine)
