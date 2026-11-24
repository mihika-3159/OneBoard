from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
from math import isfinite
from apps.api.core.config import settings
from apscheduler.schedulers.background import BackgroundScheduler
from apps.api.core.database import SessionLocal
from apps.api.models.entities import Commitment, Invoice
from apps.api.models.memory import MemoryConflict
from apps.api.models.business import Business
from apps.api.models.workflow import AuditLog

logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        # Per-business alerts store: Dict[business_id, List[Alert]]
        self.active_alerts_by_business: Dict[str, List[Dict[str, Any]]] = {}

    def start(self):
        if self.scheduler.running:
            return  # Idempotent within this process; do not start duplicate jobs.
        try:
            self.scheduler.add_job(
                self.run_proactive_checks,
                "interval",
                seconds=60,
                id="proactive_health_check",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            self.scheduler.start()
            logger.info("APScheduler proactive background monitor started.")
        except Exception as exc:
            # An operator must not be told that monitoring is active when
            # APScheduler failed to start. Do not include exception bodies
            # that might contain database URLs, credentials or tenant data.
            logger.error("Scheduler startup failed (%s)", type(exc).__name__)
            if settings.ONEBOARD_PRODUCTION_MODE:
                raise RuntimeError("Required scheduler failed to start") from None

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

    def run_proactive_checks(self, business_id: Optional[str] = None):
        """Scans database for overdue commitments, cash hazards, and unresolved discrepancies per tenant."""
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            
            # Determine which businesses to scan
            if business_id:
                businesses = db.query(Business).filter(Business.id == business_id).all()
            else:
                businesses = db.query(Business).all()

            # Avoid retaining a stale cached list if a tenant was removed.
            if business_id and not businesses:
                self.active_alerts_by_business.pop(business_id, None)
            for biz in businesses:
                b_id = biz.id
                alerts = []

                # 1. Check commitments for this specific business
                due_soon = db.query(Commitment).filter(
                    Commitment.business_id == b_id,
                    Commitment.status == "pending",
                    Commitment.deadline <= now + timedelta(days=5)
                ).all()
                for c in due_soon:
                    days_left = (c.deadline - now).days
                    alerts.append({
                        "id": f"commit_{c.id}",
                        "type": "missed_commitment_risk",
                        "severity": "critical" if days_left <= 2 else "high",
                        "title": f"Commitment Due in {max(days_left, 0)} days",
                        "description": f"Feature '{c.title}' promised to {c.counterparty} has pending deliverables.",
                        "counterparty": c.counterparty,
                        "deadline": str(c.deadline),
                        "created_at": now.isoformat()
                    })

                # 2. Check overdue invoices for this business
                overdue_invs = db.query(Invoice).filter(
                    Invoice.business_id == b_id,
                    Invoice.status == "overdue"
                ).all()
                if overdue_invs:
                    amounts = []
                    invalid_amount = False
                    for invoice in overdue_invs:
                        try:
                            value = float(invoice.amount)
                            if not isfinite(value) or value < 0:
                                raise ValueError("Invalid overdue receivable")
                            amounts.append(value)
                        except (ValueError, TypeError, OverflowError):
                            invalid_amount = True
                    if invalid_amount:
                        alerts.append({
                            "id": f"alert_invoice_data_quality_{b_id}",
                            "type": "financial_data_quality",
                            "severity": "high",
                            "title": "Overdue receivables require data review",
                            "description": "At least one invoice amount is invalid; no total has been inferred.",
                            "created_at": now.isoformat()
                        })
                    else:
                        total_overdue = sum(amounts)
                        currency = (biz.currency or "USD").upper()
                        alerts.append({
                            "id": f"alert_overdue_invoices_{b_id}",
                            "type": "receivables_overdue",
                            "severity": "medium",
                            "title": f"{len(overdue_invs)} Overdue Invoices ({currency} {total_overdue:,.2f})",
                            "description": (
                                "User-recorded overdue invoice amounts, not verified bank balances. "
                                "Review settlement before issuing reminders."
                            ),
                            "created_at": now.isoformat()
                        })

                # 3. Check unresolved data conflicts for this business
                unresolved_conflicts = db.query(MemoryConflict).filter(
                    MemoryConflict.business_id == b_id,
                    MemoryConflict.status == "unresolved"
                ).all()
                for conf in unresolved_conflicts:
                    alerts.append({
                        "id": f"conflict_{conf.id}",
                        "type": "data_conflict",
                        "severity": "high",
                        "title": f"Discrepancy: {conf.entity_name}",
                        "description": f"{conf.source_a_name} ({conf.source_a_value}) vs {conf.source_b_name} ({conf.source_b_value}).",
                        "created_at": now.isoformat()
                    })

                self.active_alerts_by_business[b_id] = alerts

        except Exception:
            logger.exception("Error in proactive check run")
            raise  # Do not silently return stale cached alerts as current.
        finally:
            db.close()

    def get_alerts(self, business_id: str) -> List[Dict[str, Any]]:
        if not business_id:
            raise ValueError("An explicit business ID is required")
        # Alerts are derived from persisted tenant data, not durable jobs. Refresh
        # on every read so status changes and process restarts cannot leave a
        # previously cached alert list falsely displayed as current.
        self.run_proactive_checks(business_id=business_id)
        return list(self.active_alerts_by_business.get(business_id, []))

scheduler_service = SchedulerService()
