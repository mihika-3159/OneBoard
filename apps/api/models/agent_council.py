from sqlalchemy import Column, String, Text, DateTime, JSON, Float, Integer, Boolean
from datetime import datetime
import uuid
from apps.api.core.database import Base

class CouncilMeeting(Base):
    __tablename__ = "council_meetings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    title = Column(String(255), nullable=False)
    meeting_type = Column(String(50), default="weekly_executive_review") 
    # Types: weekly_executive_review, monthly_financial_review, product_launch_review, 
    # marketing_strategy_review, operational_incident_review, budget_allocation_review, emergency_decision, custom
    
    stage = Column(String(50), default="completed") # context_prep, independent_analysis, challenge_round, synthesis, founder_decision, executed
    topic = Column(Text, nullable=False)
    advisers_present = Column(JSON, default=list) # List of role names
    retrieved_evidence_ids = Column(JSON, default=list)
    
    # Structured outcomes
    deliberation_transcript = Column(JSON, default=list) # Array of adviser speeches and challenge messages
    synthesis_summary = Column(Text, nullable=True)
    areas_of_agreement = Column(JSON, default=list)
    areas_of_disagreement = Column(JSON, default=list)
    recommended_actions = Column(JSON, default=list)
    
    founder_decision = Column(String(50), nullable=True) # approved, rejected, modified
    founder_notes = Column(Text, nullable=True)
    created_tasks = Column(JSON, default=list)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

class AdviserScorecard(Base):
    __tablename__ = "adviser_scorecards"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    adviser_name = Column(String(100), nullable=False) # e.g. "Marketing Adviser", "Finance Adviser"
    department = Column(String(50), nullable=False)
    
    total_recommendations = Column(Integer, default=0)
    approved_recommendations = Column(Integer, default=0)
    overridden_recommendations = Column(Integer, default=0)
    
    # Empirical accuracy
    predictions_tracked = Column(Integer, default=0)
    average_prediction_error_pct = Column(Float, default=0.0)
    evidence_completeness_score = Column(Float, default=0.92) # 0.0 to 1.0
    action_completion_rate = Column(Float, default=0.88)
    verified_outcome_rate = Column(Float, default=0.85)
    
    last_evaluated_at = Column(DateTime, default=datetime.utcnow)

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    agent_id = Column(String(100), nullable=False)
    goal = Column(Text, nullable=False)
    input_context = Column(JSON, default=dict)
    planned_steps = Column(JSON, default=list)
    tool_calls = Column(JSON, default=list)
    tool_results = Column(JSON, default=list)
    errors = Column(JSON, default=list)
    approval_state = Column(String(30), default="approved")
    verification_outcome = Column(JSON, default=dict)
    duration_ms = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
