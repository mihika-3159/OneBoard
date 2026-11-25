import os
import logging
import time
from uuid import uuid4
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from apps.api.core.config import settings, validate_production_configuration
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
from apps.api.routers.data_router import router as data_router
from apps.api.routers.diagnostics_router import router as diagnostics_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oneboard")

@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_configuration(settings)
    logger.info("Initializing OneBoard Database Schema...")
    init_db()
    if settings.ONEBOARD_PRODUCTION_MODE:
        from apps.api.core.database import engine
        from apps.api.core.runtime_role import verify_runtime_role
        verify_runtime_role(engine)
    
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

@app.exception_handler(RequestValidationError)
async def redact_sensitive_validation(request, exc):
    if request.url.path in ("/api/integrations/providers/credential", "/api/data/delete-workspace", "/api/business/financial/settlements"):
        return JSONResponse({"detail":"Invalid sensitive request"},status_code=422)
    return await request_validation_exception_handler(request,exc)

# Strict CORS origin allowlist — rejects wildcard with credentials
cors_origins_list = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Security response headers apply to every API response, including errors.
@app.middleware("http")
async def security_response_headers(request, call_next):
    # Production TLS is terminated by the owner's trusted HTTPS reverse
    # proxy. Only the ASGI server's *validated* scope scheme is authoritative.
    # Never infer HTTPS from X-Forwarded-Proto or trust X-Forwarded-Host.
    # Reject plaintext and Host-header poisoning instead of redirecting
    # sensitive requests to attacker-controlled origins. The deployment must
    # configure the ASGI server's forwarded-allow-ips to its actual proxy IP,
    # never a wildcard; this guard alone cannot verify external TLS.
    started = time.monotonic()
    request_id = uuid4().hex
    secure_external_request = False
    if settings.ONEBOARD_PRODUCTION_MODE:
        expected_host = urlsplit(settings.PUBLIC_API_ORIGIN).netloc
        supplied_hosts = request.headers.getlist("host")
        valid_host = (
            len(supplied_hosts) == 1
            and supplied_hosts[0] == expected_host
        )
        secure_external_request = request.scope.get("scheme") == "https"
        if not valid_host:
            response = JSONResponse(
                {"detail": "Unrecognized API host."}, status_code=421
            )
        elif not secure_external_request:
            response = JSONResponse(
                {"detail": "HTTPS is required for production requests."},
                status_code=403,
            )
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)

    route = request.scope.get("route")
    route_template = getattr(route, "path", "unmatched")
    logger.info("request_finished id=%s method=%s route=%s status=%d elapsed_ms=%.1f",
                request_id, request.method, route_template, response.status_code,
                (time.monotonic() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith(("/api/auth/", "/api/data/", "/api/integrations/providers/", "/api/business/financial/", "/api/diagnostics/")):
        response.headers["Cache-Control"] = "no-store"
    if settings.ONEBOARD_PRODUCTION_MODE and secure_external_request:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response

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

app.include_router(data_router)
from apps.api.routers.account_security_router import router as account_security_router
app.include_router(account_security_router)

app.include_router(diagnostics_router)
