from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
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
        try:
            self.scheduler.add_job(
                self.run_proactive_checks,
                "interval",
                seconds=60,
                id="proactive_health_check",
                replace_existing=True
            )
            self.scheduler.start()
            logger.info("APScheduler proactive background monitor started.")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")

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
                    total_overdue = sum(float(i.amount) for i in overdue_invs)
                    alerts.append({
                        "id": f"alert_overdue_invoices_{b_id}",
                        "type": "receivables_overdue",
                        "severity": "medium",
                        "title": f"{len(overdue_invs)} Overdue Invoices (${total_overdue:,.2f})",
                        "description": "Outstanding customer invoices require reminder dispatch or collection review.",
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

        except Exception as e:
            logger.error(f"Error in proactive check run: {e}")
        finally:
            db.close()

    def get_alerts(self, business_id: str) -> List[Dict[str, Any]]:
        # If no alerts cached for this tenant yet, run check for this business
        if business_id not in self.active_alerts_by_business:
            self.run_proactive_checks(business_id=business_id)
        return self.active_alerts_by_business.get(business_id, [])

scheduler_service = SchedulerService()
