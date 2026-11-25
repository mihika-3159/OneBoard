"""Approximate angular LSH retrieval using genuine embeddings only.
Four independent eight-bit random hyperplane bands give indexed candidates
across the tenant corpus. Exact cosine reranks candidates, not every row.
"""
import math
import random
from functools import lru_cache
from sqlalchemy import and_, or_, func, case
from apps.api.models.memory import MemoryChunk, MemoryDocument
from apps.api.models.operations import SemanticVector
from apps.api.services.ollama_gateway import ollama_gateway, OllamaGateway
from apps.api.services.tenant_storage import _lock
from apps.api.core.database import tenant_lifecycle_lock
from apps.api.models.business import Business

@lru_cache(maxsize=8)
def _planes(dimension):
    rng = random.Random(20261125 + dimension)
    return tuple(tuple(rng.gauss(0, 1) for _ in range(dimension)) for _ in range(32))

def signatures(vector):
    if (not isinstance(vector, list) or not 1 <= len(vector) <= 4096
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       and math.isfinite(v) and abs(v) <= 1e6 for v in vector)
            or not any(vector)):
        raise ValueError("Invalid genuine embedding")
    bits = [sum(x*y for x,y in zip(vector, plane)) >= 0 for plane in _planes(len(vector))]
    return [sum(int(bits[i*8+j]) << j for j in range(8)) for i in range(4)]

def cosine(a,b):
    return sum(x*y for x,y in zip(a,b)) / (math.sqrt(sum(x*x for x in a))*math.sqrt(sum(y*y for y in b)))

async def index_pending(db, tenant, limit=8, gateway=None):
    if not tenant or not 1 <= limit <= 32:
        raise ValueError("Invalid indexing request")
    gateway = gateway or ollama_gateway
    model = gateway.get_model_for_task("embedding")
    rows = db.query(MemoryChunk).join(MemoryDocument, and_(
        MemoryDocument.id == MemoryChunk.document_id,
        MemoryDocument.business_id == MemoryChunk.business_id,
    )).outerjoin(SemanticVector, and_(
        SemanticVector.chunk_id == MemoryChunk.id, SemanticVector.business_id == tenant,
        SemanticVector.model == model,
    )).filter(MemoryChunk.business_id == tenant, SemanticVector.chunk_id.is_(None)
    ).order_by(MemoryChunk.created_at, MemoryChunk.id).limit(limit).all()
    work = [(row.id,row.content) for row in rows]
    db.rollback()  # no database transaction is held over provider calls
    indexed = 0
    for chunk_id, content in work:
        vector = await gateway.genuine_embedding(content, model)
        if vector is None:
            break
        bands = signatures(vector)
        tenant_lifecycle_lock(db,tenant)
        _lock(db, tenant)
        chunk = db.query(MemoryChunk).filter_by(id=chunk_id, business_id=tenant).first()
        if chunk is None or chunk.content != content:
            db.rollback()
            continue
        row = db.get(SemanticVector, chunk_id)
        if row is None:
            row = SemanticVector(chunk_id=chunk_id, business_id=tenant)
            db.add(row)
        elif row.business_id != tenant:
            db.rollback()
            raise PermissionError("Vector tenant mismatch")
        row.model, row.dimension, row.vector = model, len(vector), vector
        row.band0, row.band1, row.band2, row.band3 = bands
        db.commit()
        indexed += 1
    return {"indexed": indexed, "attempted": len(work), "model": model,
            "provider_available": bool(indexed) if work else None}

async def retrieve(db, tenant, query, top_k):
    model = ollama_gateway.get_model_for_task("embedding")
    if not db.query(SemanticVector.chunk_id).filter_by(business_id=tenant, model=model).first():
        return []
    vector = await ollama_gateway.genuine_embedding(query, model)
    if vector is None:
        return []
    bands = signatures(vector)
    columns = [SemanticVector.band0, SemanticVector.band1, SemanticVector.band2, SemanticVector.band3]
    # Multi-probe each indexed band at Hamming radius one; prefer exact
    # band collisions and then near collisions before the cosine rerank.
    probes=[[band]+[band^(1<<bit) for bit in range(8)] for band in bands]
    priority=sum(case((col==band,3),(col.in_(near),1),else_=0)
                 for col,band,near in zip(columns,bands,probes))
    rows = db.query(SemanticVector, MemoryChunk, MemoryDocument.title).join(
        MemoryChunk, and_(MemoryChunk.id == SemanticVector.chunk_id,
                          MemoryChunk.business_id == SemanticVector.business_id)
    ).join(MemoryDocument, and_(MemoryDocument.id == MemoryChunk.document_id,
                               MemoryDocument.business_id == MemoryChunk.business_id)
    ).filter(SemanticVector.business_id == tenant, SemanticVector.model == model,
             SemanticVector.dimension == len(vector),
             or_(*(col.in_(near) for col,near in zip(columns,probes)))
    ).order_by(priority.desc(),SemanticVector.chunk_id).limit(201).all()
    scored = [{"chunk_id": c.id, "document_id": c.document_id, "source_title": title,
               "content": c.content, "score": round(cosine(vector, v.vector),4),
               "score_kind": "genuine_model_cosine_not_verified_relevance",
               "search_strategy": "indexed_angular_lsh_approximate",
               "candidate_limit_applied": len(rows)>200, "candidate_count": min(len(rows),200),
               "embedding_model": model, "metadata": c.metadata_tags or {}}
              for v,c,title in rows[:200]]
    return sorted(scored, key=lambda row: row["score"], reverse=True)[:top_k]


async def scheduled_index(db):
    """Durable keyset round-robin; failed/empty tenant cannot starve later tenants."""
    from sqlalchemy.orm import Session
    from apps.api.models.operations import SchedulerCursor
    from apps.api.core.database import scope_tenant_session
    cursor=db.get(SchedulerCursor,"semantic_backfill")
    if cursor is None:
        cursor=SchedulerCursor(key="semantic_backfill",last_tenant="")
        db.add(cursor)
        db.flush()
    last=cursor.last_tenant
    row=db.query(Business.id).filter(Business.id>last).order_by(Business.id).first()
    if row is None:
        row=db.query(Business.id).order_by(Business.id).first()
    if row is None:
        db.rollback()
        return {"indexed":0}
    tenant=row[0]
    cursor.last_tenant=tenant
    db.commit()  # Advance even if the provider is unavailable.
    with Session(bind=db.get_bind()) as scoped:
        scoped.info["oneboard_request"]=True
        scope_tenant_session(scoped,tenant)
        return await index_pending(scoped,tenant,limit=1,gateway=OllamaGateway())
