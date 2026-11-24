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
