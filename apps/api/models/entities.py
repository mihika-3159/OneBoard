from sqlalchemy import Column, String, Text, DateTime, JSON, Float, Integer, Boolean
from datetime import datetime
import uuid
from apps.api.core.database import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    name = Column(String(255), nullable=False)
    tier = Column(String(50), nullable=True) # Starter, Growth, Enterprise
    price = Column(Float, nullable=False, default=0.0)
    billing_interval = Column(String(20), default="monthly") # monthly, annual, one-time
    description = Column(Text, nullable=True)
    features = Column(JSON, default=list)
    active_customers_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Customer(Base):
    __tablename__ = "customers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    name = Column(String(255), nullable=False)
    company = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    tier = Column(String(50), default="Growth")
    mrr = Column(Float, default=0.0)
    status = Column(String(50), default="active") # active, onboarding, churn_risk, churned
    contract_price = Column(Float, nullable=True) # Specific contractual custom price if applicable
    health_score = Column(Integer, default=85) # 0 to 100
    last_contact_at = Column(DateTime, nullable=True)
    custom_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Lead(Base):
    __tablename__ = "leads"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    name = Column(String(255), nullable=False)
    company = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    source = Column(String(100), default="Inbound") # Inbound, Referral, Cold, Webinar
    pipeline_stage = Column(String(50), default="Qualified") # New, Contacted, Qualified, Proposal, Won, Lost
    estimated_value = Column(Float, default=0.0)
    assigned_campaign = Column(String(255), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    customer_id = Column(String(36), nullable=True)
    customer_name = Column(String(255), nullable=False)
    invoice_number = Column(String(50), nullable=False)
    amount = Column(Float, nullable=False, default=0.0)
    status = Column(String(30), default="draft") # draft, sent, paid, overdue, cancelled
    due_date = Column(DateTime, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    items = Column(JSON, default=list)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Expense(Base):
    __tablename__ = "expenses"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    category = Column(String(100), nullable=False) # Infrastructure, Software, Marketing, Legal, Operations
    vendor = Column(String(255), nullable=False)
    amount = Column(Float, nullable=False, default=0.0)
    billing_period = Column(String(30), default="monthly") # monthly, annual, one-off
    expense_date = Column(DateTime, default=datetime.utcnow)
    description = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Commitment(Base):
    __tablename__ = "commitments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    title = Column(String(255), nullable=False)
    counterparty = Column(String(255), nullable=False) # e.g. "Acme Corp (Sarah Chen)"
    counterparty_email = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    deadline = Column(DateTime, nullable=False)
    status = Column(String(30), default="pending") # pending, delivered, overdue, cancelled
    risk_level = Column(String(20), default="medium") # low, medium, critical
    evidence_source = Column(String(255), nullable=True) # e.g. "Email: Contract addendum", "Meeting notes"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    customer_id = Column(String(36), nullable=True)
    customer_name = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(String(20), default="medium") # low, medium, urgent
    status = Column(String(30), default="open") # open, investigating, waiting_customer, resolved
    proposed_resolution = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
