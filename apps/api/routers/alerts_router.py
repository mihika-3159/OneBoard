from fastapi import APIRouter, Depends, Query
from apps.api.services.scheduler_service import scheduler_service
from apps.api.core.auth import get_current_user
from apps.api.models.business import User

router = APIRouter(prefix="/api/alerts", tags=["Proactive Alerts"])

@router.get("")
def get_active_alerts(current_user: User = Depends(get_current_user)):
    return scheduler_service.get_alerts(business_id=current_user.business_id)

@router.get("/history")
def get_alert_history(
    limit: int = Query(default=100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    """Persisted tenant alert snapshots, including resolved alerts."""
    return scheduler_service.get_alert_history(current_user.business_id, limit=limit)
