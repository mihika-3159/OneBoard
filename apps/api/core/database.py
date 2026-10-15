from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from apps.api.core.config import settings
import os

# Ensure data directory exists
os.makedirs(settings.DATA_DIR, exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    import apps.api.models.business
    import apps.api.models.goals_tasks
    import apps.api.models.entities
    import apps.api.models.decision_evidence
    import apps.api.models.agent_council
    import apps.api.models.memory
    import apps.api.models.workflow
    import apps.api.models.integrations
    Base.metadata.create_all(bind=engine)
