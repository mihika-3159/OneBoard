from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
import hashlib
from sqlalchemy import text
from math import isfinite
from apps.api.core.config import settings
from apscheduler.schedulers.background import BackgroundScheduler
from apps.api.core.database import SessionLocal, tenant_lifecycle_lock, scope_tenant_session
from apps.api.models.entities import Commitment, Invoice
from apps.api.models.memory import MemoryConflict
from apps.api.models.business import Business
from apps.api.models.workflow import AuditLog
from apps.api.models.operations import AlertSnapshot
from apps.api.services.durable_jobs import claim_job, finish_job, execution_lock, process_local_outbox

logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="UTC")
        # Per-business alerts store: Dict[business_id, List[Alert]]
        self.active_alerts_by_business: Dict[str, List[Dict[str, Any]]] = {}

    def start(self):
        if self.scheduler.running:
            return  # Idempotent within this process; do not start duplicate jobs.
        try:
            self.scheduler.add_job(
                self.run_scheduled_checks,
                "interval",
                seconds=settings.SCHEDULER_INTERVAL_SECONDS,
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

    def run_scheduled_checks(self):
        job = "proactive_health_check"
        with SessionLocal() as db:
            with execution_lock(db.get_bind(), job) as acquired:
                if not acquired:
                    return
                token = claim_job(db, job)
                if token is None:
                    return
                try:
                    # Discover only tenant identifiers; all content access uses
                    # a fresh, tenant-scoped transaction. Isolate failures.
                    from apps.api.services.storage_maintenance import cleanup_global
                    cleanup_global(db)
                    failed = self.run_tenant_jobs()
                    if failed:
                        raise RuntimeError("One or more tenant jobs failed")
                except Exception:
                    db.rollback()
                    finish_job(db, job, token, False)
                    raise
                else:
                    finish_job(db, job, token, True, interval_seconds=settings.SCHEDULER_INTERVAL_SECONDS)

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

    def tenant_ids(self):
        with SessionLocal() as db:
            from apps.api.core.tenant_context import tenant_ids
            return tenant_ids(db)

    def next_job_tenants(self,limit=64):
        from apps.api.models.operations import SchedulerCursor
        with SessionLocal() as db:
            cursor=db.get(SchedulerCursor,"tenant_jobs")
            if cursor is None:
                cursor=SchedulerCursor(key="tenant_jobs",last_tenant="")
                db.add(cursor)
                db.flush()
            from apps.api.core.tenant_context import tenant_ids
            ids=tenant_ids(db,cursor.last_tenant,limit)
            if not ids:
                ids=tenant_ids(db,"",limit)
            if ids:
                cursor.last_tenant=ids[-1]
            db.commit()
            return ids

    def run_tenant_jobs(self):
        from apps.api.services.workflow_schedule import run_due
        from apps.api.services.workflow_events import detect,drain
        from apps.api.services.integrations.provider_runtime import run_sync,dispatch_one
        from apps.api.services.storage_maintenance import cleanup_tenant,sample
        def run_tenant(tenant):
            failed=0
            try:
                self.run_proactive_checks(tenant, apply_policy=True)
            except Exception as exc:
                failed+=1
                logger.error("Tenant alerts/retention job failed (%s)",type(exc).__name__)
            for task in (lambda db: process_local_outbox(db,tenant=tenant),lambda db: run_due(db,tenant),lambda db: detect(db,tenant),lambda db: drain(db,tenant),lambda db: run_sync(db,tenant),lambda db: dispatch_one(db,tenant),lambda db: cleanup_tenant(db,tenant),lambda db: sample(db,tenant)):
                try:
                    with SessionLocal() as db:
                        db.info.update(oneboard_request=True,oneboard_worker=True)
                        scope_tenant_session(db,tenant)
                        task(db)
                except Exception as exc:
                    failed+=1
                    logger.error("Tenant background job failed (%s)",type(exc).__name__)
            return failed
        tenants=self.next_job_tenants()
        if settings.ONEBOARD_PRODUCTION_MODE and tenants:
            from concurrent.futures import ThreadPoolExecutor
            # Independent tenant scopes; no shared Session between workers.
            with ThreadPoolExecutor(max_workers=max(1,min(4,(settings.DB_POOL_SIZE+settings.DB_MAX_OVERFLOW-2)//2))) as pool:
                failed=sum(pool.map(run_tenant,tenants))
        else:
            failed=sum(run_tenant(t) for t in tenants)
        if settings.ONEBOARD_PRODUCTION_MODE:
            import asyncio
            from apps.api.services.semantic_index import scheduled_index
            try:
                with SessionLocal() as db:
                    result=asyncio.run(scheduled_index(db))
                    failed+=result.get("failed_tenants",0)
            except Exception as exc:
                failed+=1
                logger.error("Semantic backfill failed (%s)",type(exc).__name__)
        return failed

    def run_proactive_checks(self, business_id: Optional[str] = None, apply_policy=False):
        """Refresh each tenant in an independent scoped transaction."""
        if business_id is None:
            failures=0
            for tenant in self.tenant_ids():
                try:
                    self.run_proactive_checks(tenant,apply_policy=True)
                except Exception as exc:
                    failures+=1
                    logger.error("Tenant alert refresh failed (%s)",type(exc).__name__)
            if failures:
                raise RuntimeError("One or more tenant alert refreshes failed")
            return
        db=SessionLocal()
        try:
            now=datetime.utcnow()
            db.info["oneboard_request"]=True
            if apply_policy:
                db.info["oneboard_worker"]=True
            scope_tenant_session(db,business_id)
            biz=db.query(Business).filter_by(id=business_id).first()
            if biz is None:
                self.active_alerts_by_business.pop(business_id,None)
                return
            for biz in (biz,):
                b_id=biz.id
                tenant_lifecycle_lock(db,b_id)
                # PostgreSQL serializes this tenant's alert update across
                # independent schedulers and HTTP workers. The transaction
                # releases the advisory lock at commit, not process exit.
                if db.get_bind().dialect.name == "postgresql":
                    lock_key = int.from_bytes(
                        hashlib.sha256(("oneboard-alerts:" + b_id).encode()).digest()[:8],
                        "big", signed=True,
                    )
                    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
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
                            from apps.api.services.finance_ledger import invoice_balance
                            value = invoice_balance(db,b_id,invoice)
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
                        from apps.api.services.finance_ledger import precision
                        digits=precision(currency)
                        alerts.append({
                            "id": f"alert_overdue_invoices_{b_id}",
                            "type": "receivables_overdue",
                            "severity": "medium",
                            "title": f"{len(overdue_invs)} Overdue Invoices ({currency} {total_overdue:,.{digits}f})",
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

                self._persist_alerts(db, b_id, alerts, now)
                if apply_policy:
                    from apps.api.services.data_lifecycle import apply_retention
                    apply_retention(db,b_id,now)
                # Keep only an optional process-local presentation cache.
                # Durable AlertSnapshot rows are the source of alert history.
                self.active_alerts_by_business[b_id] = list(alerts)
                db.commit()

        except Exception as exc:
            logger.error("Error in proactive check run (%s)", type(exc).__name__)
            raise  # Do not silently return stale cached alerts as current.
        finally:
            db.close()

    @staticmethod
    def _persist_alerts(db, business_id: str, alerts: List[Dict[str, Any]], now: datetime) -> None:
        """Upsert stable alert keys, resolve missing ones, never delete history."""
        existing = {
            row.alert_key: row
            for row in db.query(AlertSnapshot).filter(
                AlertSnapshot.business_id == business_id
            ).all()
        }
        seen = set()
        for payload in alerts:
            key = payload["id"]
            seen.add(key)
            row = existing.get(key)
            if row is None:
                row = AlertSnapshot(
                    business_id=business_id, alert_key=key,
                    payload=dict(payload), is_active=True,
                    first_seen_at=now, last_seen_at=now,
                )
                db.add(row)
            else:
                row.payload = dict(payload)
                row.is_active = True
                row.last_seen_at = now
                row.resolved_at = None
        for key, row in existing.items():
            if row.is_active and key not in seen:
                row.is_active = False
                row.resolved_at = now

    def get_alert_history(self, business_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Read persistently stored alerts without any scheduler-local cache."""
        if not business_id or not 1 <= limit <= 100:
            raise ValueError("Tenant and history limit 1-100 required")
        db = SessionLocal()
        try:
            scope_tenant_session(db,business_id)
            entries = db.query(AlertSnapshot).filter(
                AlertSnapshot.business_id == business_id
            ).order_by(AlertSnapshot.last_seen_at.desc()).limit(limit).all()
            return [{
                **dict(row.payload or {}),
                "is_active": bool(row.is_active),
                "first_seen_at": row.first_seen_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
            } for row in entries]
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
