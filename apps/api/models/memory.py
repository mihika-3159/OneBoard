from sqlalchemy import Column, String, Text, DateTime, JSON, Float, Boolean, Integer, Index, UniqueConstraint
from datetime import datetime
import uuid
from apps.api.core.database import Base

class MemoryDocument(Base):
    __tablename__ = "memory_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    title = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)
    file_type = Column(String(20), default="txt") # pdf, csv, xlsx, md, txt, json
    source_connector = Column(String(50), default="local_file")
    content_hash = Column(String(64), nullable=False)
    raw_content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class MemoryChunk(Base):
    __tablename__ = "memory_chunks"
    __table_args__ = (
        Index("ix_memory_chunks_business_created", "business_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), nullable=False)
    business_id = Column(String(36), nullable=False)
    chunk_index = Column(Integer, default=0)
    content = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=True) # Vector float array
    metadata_tags = Column(JSON, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)

class EntityRelationship(Base):
    __tablename__ = "entity_relationships"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    source_type = Column(String(50), nullable=False) # Product, Customer, Campaign, Decision, Task, etc.
    source_id = Column(String(36), nullable=False)
    source_label = Column(String(255), nullable=True)
    relationship = Column(String(50), nullable=False) # "promotes", "references", "depends_on", "owns", "measures"
    target_type = Column(String(50), nullable=False)
    target_id = Column(String(36), nullable=False)
    target_label = Column(String(255), nullable=True)
    properties = Column(JSON, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)

class MemoryConflict(Base):
    __tablename__ = "memory_conflicts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    entity_type = Column(String(50), nullable=False) # e.g. "Product.price"
    entity_id = Column(String(36), nullable=True)
    entity_name = Column(String(255), nullable=False)
    
    source_a_name = Column(String(100), nullable=False) # e.g. "Pricing Sheet (pricing_v2.xlsx)"
    source_a_value = Column(String(255), nullable=False) # "$59/mo"
    source_b_name = Column(String(100), nullable=False) # e.g. "Sales Proposal (Acme_Proposal.pdf)"
    source_b_value = Column(String(255), nullable=False) # "$49/mo"
    
    discrepancy_classification = Column(String(50), default="contract_specific_pricing") 
    # Options: stale_information, valid_historical_price, customer_specific_contract, sync_error, unauthorized_modification
    explanation = Column(Text, nullable=False)
    suggested_resolution = Column(Text, nullable=False)
    status = Column(String(30), default="unresolved") # unresolved, resolved, ignored
    resolved_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class MemoryDocumentState(Base):
    """Version lineage and durable document-level indexing lifecycle."""
    __tablename__ = "memory_document_states"
    __table_args__ = (
        UniqueConstraint("business_id","root_id","version",name="uq_memory_version"),
        Index("ix_memory_index_due","business_id","active","next_attempt_at"),
    )
    document_id = Column(String(36), primary_key=True)
    business_id = Column(String(36), nullable=False)
    root_id = Column(String(36), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    active = Column(Boolean, nullable=False, default=True)
    supersedes_id = Column(String(36), nullable=True)
    model_key = Column(String(150), nullable=True)
    status = Column(String(24), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    indexed_count = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(Float, nullable=False, default=0)
    lease_until = Column(Float, nullable=False, default=0)
    claim_token = Column(String(36), nullable=True)
    error = Column(String(150), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,onupdate=datetime.utcnow)


class MemoryRelevanceFeedback(Base):
    __tablename__ = "memory_relevance_feedback"
    __table_args__ = (
        UniqueConstraint("business_id","query_hash","chunk_id","user_id",name="uq_memory_feedback_vote"),
        Index("ix_memory_feedback_query","business_id","query_hash","chunk_id"),
    )
    id = Column(String(36), primary_key=True, default=lambda:str(uuid.uuid4()))
    business_id = Column(String(36), nullable=False)
    user_id = Column(String(36), nullable=False)
    query_hash = Column(String(64), nullable=False)
    chunk_id = Column(String(36), nullable=False)
    helpful = Column(Boolean, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
