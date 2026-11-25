"""Durable tenant-scoped operational records for monitoring and local import."""
from datetime import datetime
import uuid
from sqlalchemy import Column, String, DateTime, JSON, Boolean, Integer, Float, Index, UniqueConstraint
from apps.api.core.database import Base


class AlertSnapshot(Base):
    __tablename__ = "alert_snapshots"
    __table_args__ = (
        UniqueConstraint("business_id", "alert_key", name="uq_alert_snapshot_tenant_key"),
        Index("ix_alert_snapshot_tenant_active", "business_id", "is_active"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    alert_key = Column(String(140), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class LocalCustomerImport(Base):
    """An idempotent, user-supplied CSV import, NOT a live provider connection."""
    __tablename__ = "local_customer_imports"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key",
                         name="uq_local_import_tenant_key"),
        Index("ix_local_import_tenant_created", "business_id", "created_at"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    source_name = Column(String(100), nullable=False)
    row_count = Column(Integer, nullable=False)
    customer_ids = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TenantResourceWindow(Base):
    """Cross-worker per-tenant request budget for expensive endpoints."""
    __tablename__ = "tenant_resource_windows"
    business_id = Column(String(36), primary_key=True)
    resource = Column(String(60), primary_key=True)
    attempt_count = Column(Integer, nullable=False)
    window_started_at = Column(Float, nullable=False)


class ScheduledJobLease(Base):
    """Persistent next-due time and crash-recovery ownership."""
    __tablename__ = "scheduled_job_leases"
    job_key = Column(String(100), primary_key=True)
    next_due_at = Column(Float, nullable=False)
    lease_until = Column(Float, nullable=False, default=0)
    owner_token = Column(String(36), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_success_at = Column(Float, nullable=True)


class SideEffectOutbox(Base):
    """Transactional workflow draft intent; never an external delivery receipt."""
    __tablename__ = "side_effect_outbox"
    __table_args__ = (
        UniqueConstraint("business_id", "run_id", "step_id",
                         name="uq_outbox_tenant_run_step"),
        Index("ix_outbox_state_created", "state", "created_at"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    run_id = Column(String(36), nullable=False)
    step_id = Column(String(100), nullable=False)
    kind = Column(String(60), nullable=False)
    payload = Column(JSON, nullable=False)
    state = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)


class SemanticVector(Base):
    """Genuine model embedding and indexed random-hyperplane signatures."""
    __tablename__ = "semantic_vectors"
    __table_args__ = tuple(Index("ix_semantic_band_" + str(i), "business_id", "model", "dimension", "band" + str(i)) for i in range(4))
    chunk_id = Column(String(36), primary_key=True)
    business_id = Column(String(36), nullable=False)
    model = Column(String(150), nullable=False)
    dimension = Column(Integer, nullable=False)
    vector = Column(JSON, nullable=False)
    band0 = Column(Integer, nullable=False)
    band1 = Column(Integer, nullable=False)
    band2 = Column(Integer, nullable=False)
    band3 = Column(Integer, nullable=False)


class SettlementEvidence(Base):
    __tablename__ = "settlement_evidence"
    __table_args__ = (
        UniqueConstraint("business_id", "source_reference", name="uq_settlement_source"),
        Index("ix_settlement_tenant_period", "business_id", "period"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    invoice_id = Column(String(36), nullable=False)
    source_reference = Column(String(128), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    currency = Column(String(3), nullable=False)
    original_amount = Column(String(32), nullable=False)
    base_currency = Column(String(3), nullable=False)
    fx_rate = Column(String(32), nullable=False)
    fx_source = Column(String(200), nullable=False)
    base_amount = Column(String(32), nullable=False)
    settled_on = Column(String(10), nullable=False)
    period = Column(String(7), nullable=False)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("business_id", "provider", name="uq_provider_tenant"),)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    provider = Column(String(30), nullable=False)
    scopes = Column(JSON, nullable=False)
    encrypted_token = Column(String(16000), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ProviderIntent(Base):
    __tablename__ = "provider_intents"
    __table_args__ = (UniqueConstraint("business_id", "provider", "idempotency_key", name="uq_provider_intent"),)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    provider = Column(String(30), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    scope = Column(String(100), nullable=False)
    state = Column(String(30), nullable=False, default="staged_no_dispatch")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DataRetentionPolicy(Base):
    __tablename__ = "data_retention_policies"
    business_id = Column(String(36), primary_key=True)
    document_days = Column(Integer, nullable=True)
    resolved_alert_days = Column(Integer, nullable=True)
    expired_session_days = Column(Integer, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WorkflowSchedule(Base):
    """Opt-in persisted wall-clock schedule; no legacy template auto-enrollment."""
    __tablename__ = "workflow_schedules"
    __table_args__ = (Index("ix_workflow_schedule_tenant_due","business_id","enabled","next_due_at"),)
    workflow_id = Column(String(36), primary_key=True)
    business_id = Column(String(36), nullable=False)
    cron = Column(String(40), nullable=False)
    timezone = Column(String(64), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    next_due_at = Column(Float, nullable=False)
    last_run_id = Column(String(36), nullable=True)
    last_status = Column(String(30), nullable=True)
    coalesced = Column(Boolean, nullable=False, default=False)
    missed_policy = Column(String(20), nullable=True)
    missed_count = Column(Integer, nullable=True)


class SchedulerCursor(Base):
    """Global, non-content cursor for bounded fair background traversal."""
    __tablename__ = "scheduler_cursors"
    key = Column(String(60), primary_key=True)
    last_tenant = Column(String(36), nullable=False, default="")


class WorkflowRevision(Base):
    __tablename__ = "workflow_revisions"
    __table_args__ = (UniqueConstraint("business_id","workflow_id","version",name="uq_workflow_revision_version"),)
    id = Column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    workflow_id = Column(String(36), nullable=False)
    version = Column(Integer, nullable=False)
    definition = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WorkflowTriggerState(Base):
    __tablename__ = "workflow_trigger_states"
    workflow_id = Column(String(36), primary_key=True)
    business_id = Column(String(36), nullable=False)
    config_digest = Column(String(64), nullable=False)
    activated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    state = Column(JSON, nullable=False, default=dict)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("business_id","workflow_id","event_key",name="uq_workflow_event_key"),
        Index("ix_workflow_event_due","business_id","status","next_attempt_at"),
    )
    id = Column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    workflow_id = Column(String(36), nullable=False)
    event_key = Column(String(64), nullable=False)
    kind = Column(String(30), nullable=False)
    payload = Column(JSON, nullable=False)
    definition_digest = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(Float, nullable=False, default=0)
    lease_until = Column(Float, nullable=False, default=0)
    owner_token = Column(String(36), nullable=True)
    run_id = Column(String(36), nullable=True)
    error = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
