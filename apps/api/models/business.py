from sqlalchemy import Column, String, Text, DateTime, JSON, Boolean, Float
from datetime import datetime
import uuid
from apps.api.core.database import Base

class Business(Base):
    __tablename__ = "businesses"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    industry = Column(String(100), default="B2B SaaS")
    currency = Column(String(10), default="USD")
    timezone = Column(String(50), default="UTC")
    business_model = Column(String(100), default="Subscription / SaaS")
    
    # JSON structured attributes
    products_summary = Column(JSON, default=list)
    target_customers = Column(JSON, default=list)
    strategic_objectives = Column(JSON, default=list)
    constraints = Column(JSON, default=dict)
    founder_preferences = Column(JSON, default=dict)
    
    # Financial health baseline cache
    monthly_burn_rate = Column(Float, default=0.0)
    current_cash_balance = Column(Float, default=0.0)
    runway_months = Column(Float, default=0.0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
