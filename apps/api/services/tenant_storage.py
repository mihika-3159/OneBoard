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


# Additional growing categories, independently bounded per tenant. The
# before_flush guard covers ORM insertion paths across API and workers.
ROW_LIMITS={
    "customers":10000,"leads":10000,"invoices":20000,"expenses":10000,"products":2000,
    "commitments":10000,"support_tickets":10000,"tasks":20000,"goals":2000,"projects":2000,
    "decisions":10000,"evidence":20000,"entity_relationships":20000,"memory_conflicts":5000,
    "memory_documents":200,"memory_chunks":20000,"memory_document_states":200,"memory_relevance_feedback":20000,
    "workflow_definitions":200,"custom_agents":100,"workflow_runs":20000,"agent_runs":20000,
    "workflow_events":20000,"workflow_revisions":20000,"approval_requests":20000,"side_effect_outbox":20000,
    "council_meetings":5000,"audit_logs":100000,"local_customer_imports":5000,
    "journal_entries":20000,"bank_statement_lines":20000,"settlement_evidence":20000,"finance_forecasts":2000,
    "provider_records":20000,"provider_record_conflicts":5000,"provider_sync_jobs":2000,
    "provider_deliveries":2000,"provider_webhook_receipts":10000,"provider_intents":1000,
    "integration_accounts":100,"alert_snapshots":20000,
}
def check_table_rows(db,tenant,table,adding):
    from sqlalchemy import select
    from apps.api.core.database import Base
    if table not in ROW_LIMITS:return
    if not 0<=adding<=200000:raise ValueError("Invalid quota admission")
    _lock(db,tenant)
    t=Base.metadata.tables[table]
    existing=db.execute(select(func.count()).select_from(t).where(t.c.business_id==tenant)).scalar_one()
    if existing+adding>ROW_LIMITS[table]:_deny()
    return existing

def install_quota_guard():
    from sqlalchemy import event,inspect
    from sqlalchemy.orm import Session
    from collections import Counter
    @event.listens_for(Session,"before_flush")
    def enforce(session,flush_context,instances):
        if not session.info.get("oneboard_request") and not session.info.get("oneboard_enforce_quota"):return
        pending=Counter()
        for obj in session.new:
            table=inspect(obj).mapper.local_table.name
            if table in ROW_LIMITS:
                tenant=getattr(obj,"business_id",None)
                if not tenant:raise ValueError("Tenant required for quota admission")
                pending[tenant,table]+=1
        for (tenant,table),adding in sorted(pending.items()):check_table_rows(session,tenant,table,adding)

install_quota_guard()
