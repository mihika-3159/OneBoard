from sqlalchemy import Column, String, Text, DateTime, JSON, Boolean
from datetime import datetime
import uuid
from apps.api.core.database import Base

class IntegrationAccount(Base):
    __tablename__ = "integration_accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    connector_type = Column(String(50), nullable=False) # local_files, demo_crm, demo_email, demo_calendar, github, notion, google
    name = Column(String(100), nullable=False)
    status = Column(String(30), default="connected") # connected, disconnected, auth_required, error
    is_mock = Column(Boolean, default=True)
    
    granted_scopes = Column(JSON, default=list)
    configuration = Column(JSON, default=dict)
    last_sync = Column(DateTime, nullable=True)
    records_synced = Column(JSON, default=dict) # {"customers": 35, "invoices": 42}
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SyncHistory(Base):
    __tablename__ = "sync_history"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    integration_id = Column(String(36), nullable=False)
    status = Column(String(30), default="success") # success, partial, failed
    items_imported = Column(JSON, default=dict)
    details = Column(Text, nullable=True)
    
    timestamp = Column(DateTime, default=datetime.utcnow)
