import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.core.config import settings
from apps.api.core.database import init_db, SessionLocal
from apps.api.services.seed_data import seed_northstar_studio
from apps.api.services.scheduler_service import scheduler_service

from apps.api.routers.auth_router import router as auth_router
from apps.api.routers.business_router import router as business_router
from apps.api.routers.council_router import router as council_router
from apps.api.routers.memory_router import router as memory_router
from apps.api.routers.workflow_router import router as workflow_router
from apps.api.routers.agent_studio_router import router as agent_studio_router
from apps.api.routers.accountability_router import router as accountability_router
from apps.api.routers.integrations_router import router as integrations_router
from apps.api.routers.alerts_router import router as alerts_router
from apps.api.routers.model_gateway_router import router as model_gateway_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oneboard")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing OneBoard Database Schema...")
    init_db()
    
    is_demo_mode = (
        os.environ.get("ONEBOARD_DEMO_MODE", "").lower() in ("1", "true", "yes")
        or settings.ONEBOARD_DEMO_MODE
    )
    if is_demo_mode:
        logger.info("ONEBOARD_DEMO_MODE=true: Ensuring Northstar Studio demo fixture is populated...")
        db = SessionLocal()
        try:
            seed_northstar_studio(db)
        finally:
            db.close()
    else:
        logger.info("Production mode: Automatic demo seeding is disabled.")

    logger.info("Starting Proactive Background Monitor...")
    scheduler_service.start()
    
    yield
    
    logger.info("Shutting down OneBoard Services...")
    scheduler_service.shutdown()

app = FastAPI(
    title="OneBoard API",
    description="AI Operating System for a Company of One. Local-first executive council, visual workflows, and accountable business management.",
    version="1.0.0",
    lifespan=lifespan
)

# Strict CORS origin allowlist — rejects wildcard with credentials
cors_origins_list = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Minimal public health endpoint
@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "service": "OneBoard API",
        "version": settings.VERSION
    }

# Mount routers
app.include_router(auth_router)
app.include_router(business_router)
app.include_router(council_router)
app.include_router(memory_router)
app.include_router(workflow_router)
app.include_router(agent_studio_router)
app.include_router(accountability_router)
app.include_router(integrations_router)
app.include_router(alerts_router)
app.include_router(model_gateway_router)
