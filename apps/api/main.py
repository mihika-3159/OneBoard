from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

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
    logger.info("Initializing OneBoard Database & Seed Fixtures...")
    init_db()
    db = SessionLocal()
    try:
        seed_northstar_studio(db)
    finally:
        db.close()
    
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

# Explicitly authorized origins - no wildcard '*' with allow_credentials=True
TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=TRUSTED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-OneBoard-Mode", "X-OneBoard-Tenant"]
)

@app.middleware("http")
async def add_security_and_tenant_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-OneBoard-Mode"] = "local-single-user-secure"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response

# Mount all core routers
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

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "app": "OneBoard",
        "version": settings.VERSION,
        "default_profile": settings.DEFAULT_MODEL_PROFILE
    }
