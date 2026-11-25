"""Tenant-scoped durable storage and resource admission.

Locks must be held through the caller's final commit. PostgreSQL uses a
transaction advisory lock; SQLite is a single-worker development fallback.
"""
import hashlib
from fastapi import HTTPException
from sqlalchemy import func, text
from apps.api.models.memory import MemoryDocument, MemoryChunk
from apps.api.models.workflow import WorkflowDefinition, CustomAgent

MAX_DOCUMENTS = 200
MAX_TEXT_BYTES = 50 * 1024 * 1024
MAX_CHUNKS = 20000
RESOURCE_LIMITS = {"workflow": (WorkflowDefinition, 200), "agent": (CustomAgent, 100)}

def _lock(db, tenant):
    if not tenant:
        raise ValueError("Tenant required")
    if db.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(("oneboard:storage:" + tenant).encode()).digest()[:8],
                             "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

def _deny():
    raise HTTPException(status_code=429, detail="Tenant storage or resource quota exhausted.")

def check_resource(db, tenant, resource):
    _lock(db, tenant)
    model, limit = RESOURCE_LIMITS[resource]
    if db.query(model).filter(model.business_id == tenant).count() >= limit:
        _deny()

def check_document(db, tenant, raw_content, paragraphs):
    _lock(db, tenant)
    docs = db.query(MemoryDocument).filter(MemoryDocument.business_id == tenant)
    chunks = db.query(MemoryChunk).filter(MemoryChunk.business_id == tenant)
    if docs.count() >= MAX_DOCUMENTS or chunks.count() + len(paragraphs) > MAX_CHUNKS:
        _deny()
    if db.get_bind().dialect.name == "postgresql":
        size = lambda col: func.octet_length(col)
    else:
        from sqlalchemy import cast, LargeBinary
        size = lambda col: func.length(cast(col, LargeBinary))
    doc_bytes = db.query(func.coalesce(func.sum(size(MemoryDocument.raw_content)), 0)).filter(
        MemoryDocument.business_id == tenant).scalar()
    chunk_bytes = db.query(func.coalesce(func.sum(size(MemoryChunk.content)), 0)).filter(
        MemoryChunk.business_id == tenant).scalar()
    incoming = len(raw_content.encode("utf-8")) + sum(len(p.encode("utf-8")) for p in paragraphs)
    if doc_bytes + chunk_bytes + incoming > MAX_TEXT_BYTES:
        _deny()
