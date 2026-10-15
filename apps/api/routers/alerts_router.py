from fastapi import APIRouter
from apps.api.services.scheduler_service import scheduler_service

router = APIRouter(prefix="/api/alerts", tags=["Proactive Alerts"])

@router.get("")
def get_active_alerts():
    return scheduler_service.get_alerts()
