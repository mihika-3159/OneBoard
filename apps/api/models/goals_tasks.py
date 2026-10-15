from sqlalchemy import Column, String, Text, DateTime, JSON, Float, ForeignKey
from datetime import datetime
import uuid
from apps.api.core.database import Base

class Goal(Base):
    __tablename__ = "goals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    target_metric = Column(String(100), nullable=True) # e.g. "Monthly Recurring Revenue", "Active Users"
    baseline_value = Column(Float, default=0.0)
    target_value = Column(Float, default=0.0)
    current_value = Column(Float, default=0.0)
    unit = Column(String(20), default="$")
    deadline = Column(DateTime, nullable=True)
    priority = Column(String(20), default="high") # critical, high, medium, low
    status = Column(String(30), default="in_progress") # on_track, at_risk, behind, completed
    owner = Column(String(100), default="Founder")
    dependencies = Column(JSON, default=list)
    evidence_sources = Column(JSON, default=list)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    goal_id = Column(String(36), nullable=True)
    decision_id = Column(String(36), nullable=True)
    
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    responsible_agent = Column(String(100), default="Founder") # "Chief of Staff", "Marketing Adviser", "Founder", etc.
    priority = Column(String(20), default="medium")
    deadline = Column(DateTime, nullable=True)
    status = Column(String(30), default="todo") # todo, in_progress, awaiting_approval, done, blocked
    
    requires_approval = Column(String(20), default="none") # none, medium_risk, high_risk
    approval_status = Column(String(30), default="approved") # approved, pending, rejected
    execution_history = Column(JSON, default=list)
    verification_results = Column(JSON, default=dict) # {"verified": true, "timestamp": "...", "method": "..."}
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(30), default="active") # active, completed, on_hold
    deadline = Column(DateTime, nullable=True)
    budget = Column(Float, default=0.0)
    spent = Column(Float, default=0.0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
