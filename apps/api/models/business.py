from sqlalchemy import Column, String, Text, DateTime, JSON, Boolean, Float, ForeignKey
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
    
    # Ownership
    owner_id = Column(String(36), nullable=True)
    
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


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="founder")  # "founder", "member", "admin"
    business_id = Column(String(36), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    api_key = Column(String(100), unique=True, index=True, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BusinessMembership(Base):
    __tablename__ = "business_memberships"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    business_id = Column(String(36), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(50), default="founder")  # "owner", "founder", "member"
    created_at = Column(DateTime, default=datetime.utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))  # jti / session ID
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    business_id = Column(String(36), nullable=False)
    token_hash = Column(String(64), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
