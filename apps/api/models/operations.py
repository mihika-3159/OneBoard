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
    retention_redacted_at=Column(DateTime,nullable=True)


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
    completed_sync_days = Column(Integer, nullable=True)
    resolved_conflict_days = Column(Integer, nullable=True)
    completed_draft_days = Column(Integer, nullable=True)
    performance_sample_days = Column(Integer, nullable=True)
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


# Accounting journal, immutable closed periods, and reproducible forecast records.
# Integer amounts represent currency-specific minor units (not floating point).
from sqlalchemy import BigInteger, CheckConstraint, Text

class JournalEntry(Base):
    __tablename__="journal_entries"
    __table_args__=(UniqueConstraint("business_id","reference",name="uq_journal_reference"),
                    Index("ix_journal_period","business_id","period","id"),
                    Index("ix_journal_invoice","business_id","invoice_id"),
                    CheckConstraint("original_minor > 0 AND base_minor > 0",name="ck_journal_positive"),
                    CheckConstraint("debit_account <> credit_account",name="ck_journal_balanced_pair"))
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    reference=Column(String(128),nullable=False)
    request_hash=Column(String(64),nullable=False)
    kind=Column(String(24),nullable=False)
    invoice_id=Column(String(36),nullable=True)
    related_entry_id=Column(String(36),nullable=True)
    invoice_minor_delta=Column(BigInteger,nullable=True)
    carrying_minor=Column(BigInteger,nullable=True)
    debit_account=Column(String(40),nullable=False)
    credit_account=Column(String(40),nullable=False)
    currency=Column(String(3),nullable=False)
    original_minor=Column(BigInteger,nullable=False)
    base_currency=Column(String(3),nullable=False)
    base_minor=Column(BigInteger,nullable=False)
    fx_rate=Column(String(40),nullable=False)
    fx_source=Column(String(200),nullable=False)
    booked_on=Column(String(10),nullable=False)
    period=Column(String(7),nullable=False)
    evidence_hash=Column(String(64),nullable=False)
    actor_id=Column(String(36),nullable=False)
    recorded_at=Column(DateTime,nullable=False,default=datetime.utcnow)

class AccountingClose(Base):
    __tablename__="accounting_closes"
    __table_args__=(UniqueConstraint("business_id","period",name="uq_accounting_close"),)
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    period=Column(String(7),nullable=False)
    snapshot=Column(JSON,nullable=False)
    snapshot_hash=Column(String(64),nullable=False)
    actor_id=Column(String(36),nullable=False)
    closed_at=Column(DateTime,nullable=False,default=datetime.utcnow)

class BankStatementLine(Base):
    __tablename__="bank_statement_lines"
    __table_args__=(UniqueConstraint("business_id","account","reference",name="uq_bank_reference"),
                    UniqueConstraint("business_id","journal_id",name="uq_bank_journal_match"),
                    Index("ix_bank_period","business_id","period"))
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    account=Column(String(80),nullable=False)
    reference=Column(String(128),nullable=False)
    booked_on=Column(String(10),nullable=False)
    period=Column(String(7),nullable=False)
    currency=Column(String(3),nullable=False)
    signed_minor=Column(BigInteger,nullable=False)
    source_hash=Column(String(64),nullable=False)
    journal_id=Column(String(36),nullable=True)
    matched_by=Column(String(36),nullable=True)
    matched_at=Column(DateTime,nullable=True)
    recorded_at=Column(DateTime,nullable=False,default=datetime.utcnow)

class FinanceForecast(Base):
    __tablename__="finance_forecasts"
    __table_args__=(Index("ix_finance_forecast_tenant","business_id","created_at"),)
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    actor_id=Column(String(36),nullable=False)
    assumptions=Column(JSON,nullable=False)
    baseline=Column(JSON,nullable=False)
    baseline_hash=Column(String(64),nullable=False)
    results=Column(JSON,nullable=False)
    due_period=Column(String(7),nullable=False)
    outcome=Column(JSON,nullable=True)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)

class UnitEconomicsObservation(Base):
    __tablename__="unit_economics_observations"
    __table_args__=(UniqueConstraint("business_id","period",name="uq_unit_economics_period"),)
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    period=Column(String(7),nullable=False)
    close_id=Column(String(36),nullable=False)
    source_hash=Column(String(64),nullable=False)
    request_hash=Column(String(64),nullable=False)
    inputs=Column(JSON,nullable=False)
    results=Column(JSON,nullable=False)
    actor_id=Column(String(36),nullable=False)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)


class ProviderConnection(Base):
    __tablename__="provider_connections"
    __table_args__=(UniqueConstraint("business_id","provider",name="uq_live_provider"),)
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    provider=Column(String(30),nullable=False)
    state=Column(String(30),nullable=False,default="disconnected")
    generation=Column(Integer,nullable=False,default=0)
    scopes=Column(JSON,nullable=False,default=list)
    encrypted_credentials=Column(Text,nullable=True)
    expires_at=Column(DateTime,nullable=True)
    remote_account=Column(String(255),nullable=True)
    adapter_fingerprint=Column(String(64),nullable=True)
    checkpoint=Column(Text,nullable=True)
    last_sync=Column(DateTime,nullable=True)
    last_error=Column(String(100),nullable=True)
    updated_at=Column(DateTime,nullable=False,default=datetime.utcnow)

class ProviderAuthorization(Base):
    __tablename__="provider_authorizations"
    __table_args__=(Index("ix_provider_auth_tenant","business_id","expires_at"),)
    state_hash=Column(String(64),primary_key=True)
    business_id=Column(String(36),nullable=False)
    connection_id=Column(String(36),nullable=False)
    actor_id=Column(String(36),nullable=False)
    generation=Column(Integer,nullable=False)
    scopes=Column(JSON,nullable=False)
    encrypted_verifier=Column(Text,nullable=False)
    expires_at=Column(DateTime,nullable=False)
    consumed_at=Column(DateTime,nullable=True)

class ProviderSyncJob(Base):
    __tablename__="provider_sync_jobs"
    __table_args__=(UniqueConstraint("business_id","connection_id","request_key",name="uq_provider_sync_request"),
                    Index("ix_provider_sync_due","business_id","state","next_attempt"))
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    connection_id=Column(String(36),nullable=False)
    generation=Column(Integer,nullable=False)
    request_key=Column(String(128),nullable=False)
    state=Column(String(30),nullable=False,default="queued")
    attempts=Column(Integer,nullable=False,default=0)
    pages=Column(Integer,nullable=False,default=0)
    imported=Column(Integer,nullable=False,default=0)
    duplicates=Column(Integer,nullable=False,default=0)
    conflicts=Column(Integer,nullable=False,default=0)
    next_attempt=Column(DateTime,nullable=False,default=datetime.utcnow)
    error_code=Column(String(100),nullable=True)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    finished_at=Column(DateTime,nullable=True)
    retention_redacted_at=Column(DateTime,nullable=True)


class ProviderRecord(Base):
    __tablename__="provider_records"
    __table_args__=(UniqueConstraint("business_id","connection_id","remote_id",name="uq_provider_record"),
                    Index("ix_provider_record_connection","business_id","connection_id"))
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    connection_id=Column(String(36),nullable=False)
    remote_id=Column(String(255),nullable=False)
    revision=Column(String(128),nullable=False)
    payload=Column(JSON,nullable=False)
    payload_hash=Column(String(64),nullable=False)
    updated_at=Column(DateTime,nullable=False,default=datetime.utcnow)

class ProviderRecordConflict(Base):
    __tablename__="provider_record_conflicts"
    __table_args__=(UniqueConstraint("business_id","record_id","incoming_hash",name="uq_provider_record_conflict"),)
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    connection_id=Column(String(36),nullable=False)
    record_id=Column(String(36),nullable=False)
    incoming_revision=Column(String(128),nullable=False)
    incoming_payload=Column(JSON,nullable=False)
    incoming_hash=Column(String(64),nullable=False)
    state=Column(String(30),nullable=False,default="pending")
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    retention_redacted_at=Column(DateTime,nullable=True)


class ProviderWebhookReceipt(Base):
    __tablename__="provider_webhook_receipts"
    __table_args__=(UniqueConstraint("business_id","connection_id","event_id",name="uq_provider_webhook_event"),)
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    connection_id=Column(String(36),nullable=False)
    event_id=Column(String(128),nullable=False)
    body_hash=Column(String(64),nullable=False)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)

class ProviderDelivery(Base):
    __tablename__="provider_deliveries"
    __table_args__=(UniqueConstraint("business_id","connection_id","request_key",name="uq_provider_delivery_key"),)
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    connection_id=Column(String(36),nullable=False)
    generation=Column(Integer,nullable=False)
    request_key=Column(String(128),nullable=False)
    request_hash=Column(String(64),nullable=False)
    action=Column(String(50),nullable=False)
    payload=Column(JSON,nullable=False)
    actor_id=Column(String(36),nullable=False)
    state=Column(String(30),nullable=False,default="approved")
    remote_reference=Column(String(255),nullable=True)
    error_code=Column(String(100),nullable=True)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    updated_at=Column(DateTime,nullable=False,default=datetime.utcnow)


class PortableArchive(Base):
    __tablename__="portable_archives"
    __table_args__=(Index("ix_portable_archive_tenant_expiry","business_id","expires_at"),UniqueConstraint("business_id","kind",name="uq_portable_archive_tenant_kind"))
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    actor_id=Column(String(36),nullable=False)
    kind=Column(String(12),nullable=False)
    state=Column(String(20),nullable=False)
    manifest=Column(JSON,nullable=True)
    page_count=Column(Integer,nullable=False,default=0)
    row_count=Column(Integer,nullable=False,default=0)
    byte_count=Column(BigInteger,nullable=False,default=0)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    expires_at=Column(DateTime,nullable=False)

class PortableArchivePage(Base):
    __tablename__="portable_archive_pages"
    __table_args__=(Index("ix_portable_page_tenant_archive","business_id","archive_id","page_number"),)
    archive_id=Column(String(36),primary_key=True)
    page_number=Column(Integer,primary_key=True)
    business_id=Column(String(36),nullable=False)
    table_name=Column(String(80),nullable=False)
    content=Column(Text,nullable=False)
    checksum=Column(String(64),nullable=False)
    row_count=Column(Integer,nullable=False)
    byte_count=Column(Integer,nullable=False)

class DatabasePerformanceSample(Base):
    __tablename__="database_performance_samples"
    __table_args__=(Index("ix_database_perf_tenant_time","business_id","created_at"),)
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    business_id=Column(String(36),nullable=False)
    workload=Column(String(60),nullable=False)
    rows_examined=Column(Integer,nullable=False)
    elapsed_ms=Column(Float,nullable=False)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
