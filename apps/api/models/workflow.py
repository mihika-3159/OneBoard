from sqlalchemy import Column, String, Text, DateTime, JSON, Float, Boolean, Integer
from datetime import datetime
import uuid
from apps.api.core.database import Base

class CustomAgent(Base):
    __tablename__ = "custom_agents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    name = Column(String(255), nullable=False)
    role_title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    department = Column(String(50), default="Operations") # Operations, Growth, Finance, Support, Engineering
    
    system_prompt = Column(Text, nullable=False)
    selected_model = Column(String(100), default="qwen2.5:7b")
    status = Column(String(20), default="active") # active, paused, draft
    
    # Permissions and boundaries
    allowed_tools = Column(JSON, default=list) # e.g. ["read_crm", "draft_email", "calculate_metrics"]
    allowed_memory_collections = Column(JSON, default=list)
    requires_approval_for = Column(JSON, default=list) # ["send_email", "update_price"]
    max_steps = Column(Integer, default=5)
    
    # Metadata
    created_via = Column(String(20), default="visual") # visual, natural_language
    version = Column(Integer, default=1)
    execution_count = Column(Integer, default=0)
    last_executed_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), default="Operations")
    
    # Visual React Flow Canvas State
    nodes = Column(JSON, default=list) # React Flow node objects
    edges = Column(JSON, default=list) # React Flow edge objects
    
    # Automation Triggers
    trigger_type = Column(String(50), default="manual") # manual, schedule, new_customer, invoice_overdue, metric_threshold
    trigger_config = Column(JSON, default=dict) # e.g. {"cron": "0 9 * * 5", "threshold_metric": "runway_months"}
    is_active = Column(Boolean, default=True)
    is_template = Column(Boolean, default=False)
    
    # Validation & Dry-Run
    is_valid = Column(Boolean, default=True)
    last_dry_run_result = Column(JSON, default=dict)
    
    # Council recommendations
    recommended_by = Column(String(100), nullable=True) # e.g. "Operations Adviser"
    estimated_time_saved_hours = Column(Float, default=2.5)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id = Column(String(36), nullable=False)
    business_id = Column(String(36), nullable=False)
    workflow_name = Column(String(255), nullable=False)
    
    status = Column(String(30), default="pending") # pending, running, awaiting_approval, completed, failed, paused
    trigger_source = Column(String(50), default="manual")
    
    step_results = Column(JSON, default=dict)
    current_step_id = Column(String(100), nullable=True)
    
    # Outcome Verification
    verified_success = Column(Boolean, default=False)
    verification_details = Column(JSON, default=dict)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, default=0)
    
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    workflow_run_id = Column(String(36), nullable=True)
    task_id = Column(String(36), nullable=True)
    
    action_type = Column(String(100), nullable=False) # e.g. "send_external_email", "apply_pricing_change"
    risk_level = Column(String(20), default="high") # low, medium, high
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    payload = Column(JSON, default=dict)
    
    status = Column(String(20), default="pending") # pending, approved, rejected
    reviewed_at = Column(DateTime, nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    actor = Column(String(100), nullable=False) # "Founder", "Chief of Staff", "Workflow: Invoice Reminders"
    action = Column(String(100), nullable=False)
    target_entity = Column(String(100), nullable=True)
    details = Column(JSON, default=dict)
    risk_level = Column(String(20), default="low")
    ip_address = Column(String(50), default="127.0.0.1")
    
    timestamp = Column(DateTime, default=datetime.utcnow)
