from sqlalchemy import Column, String, Text, DateTime, JSON, Float, Boolean
from datetime import datetime
import uuid
from apps.api.core.database import Base

class Decision(Base):
    __tablename__ = "decisions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    title = Column(String(255), nullable=False)
    business_context = Column(Text, nullable=False)
    alternatives_considered = Column(JSON, default=list)
    supporting_evidence_ids = Column(JSON, default=list)
    
    # Core accountability attributes
    assumptions = Column(JSON, default=list) # [{"id": "a1", "text": "Lead gen conversion rate holds at 3.5%", "status": "valid"}]
    advisers_consulted = Column(JSON, default=list) # ["Chief of Staff", "Finance Adviser", "Marketing Adviser"]
    recommendations_summary = Column(Text, nullable=True)
    dissenting_opinions = Column(JSON, default=list) # [{"adviser": "Finance Adviser", "objection": "CAC exceeds LTV target by 18%"}]
    
    # Founder Decision & Approval
    founder_decision = Column(String(50), default="approved") # approved, rejected, deferred, modified
    approval_timestamp = Column(DateTime, default=datetime.utcnow)
    founder_notes = Column(Text, nullable=True)
    
    # Execution & Outcome Tracking
    planned_actions = Column(JSON, default=list)
    expected_outcomes = Column(JSON, default=list) # [{"metric": "Signups", "predicted_value": 50, "timeframe_days": 30}]
    actual_outcomes = Column(JSON, default=list) # [{"metric": "Signups", "actual_value": 14, "absolute_error": 36, "percentage_error": 72.0}]
    outcome_review_date = Column(DateTime, nullable=True)
    outcome_verified = Column(Boolean, default=False)
    outcome_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    title = Column(String(255), nullable=False)
    source_connector = Column(String(50), nullable=False) # local_file, csv, xlsx, demo_crm, github, notion, email
    source_record_id = Column(String(255), nullable=True)
    snippet = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=True)
    confidence_score = Column(Float, default=1.0) # 0.0 to 1.0
    provenance_type = Column(String(50), default="verified_fact") # verified_fact, user_statement, calculated_value, model_estimate, assumption
    associated_entities = Column(JSON, default=list)
    retrieval_timestamp = Column(DateTime, default=datetime.utcnow)
    
    created_at = Column(DateTime, default=datetime.utcnow)
