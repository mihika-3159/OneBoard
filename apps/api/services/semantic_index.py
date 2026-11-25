"""Approximate angular LSH retrieval using genuine embeddings only.
Four independent eight-bit random hyperplane bands give indexed candidates
across the tenant corpus. Exact cosine reranks candidates, not every row.
"""
import math
import asyncio
import hashlib
from uuid import uuid4
from datetime import datetime
from apps.api.core.config import settings
from apps.api.services.durable_jobs import _now,execution_lock
import random
from functools import lru_cache
from sqlalchemy import and_, or_, func, case
from apps.api.services.inference_budget import inference_tenant
from apps.api.models.memory import MemoryChunk, MemoryDocument, MemoryDocumentState
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

def model_identity(gateway):
    model=gateway.get_model_for_task("embedding")
    digest=settings.OLLAMA_MODEL_DIGESTS.get(model)
    key=model if not digest else model+"@"+hashlib.sha256(str(digest).encode()).hexdigest()[:24]
    if len(key)>150:raise ValueError("Embedding identity exceeds limit")
    return model,key


def active_state():
    return or_(MemoryDocumentState.document_id.is_(None),MemoryDocumentState.active.is_(True))


def state_join():
    return and_(MemoryDocumentState.document_id==MemoryDocument.id,
                MemoryDocumentState.business_id==MemoryDocument.business_id)


def pending_chunks(db,tenant,model_key):
    return db.query(MemoryChunk).join(MemoryDocument,and_(
        MemoryChunk.document_id==MemoryDocument.id,MemoryChunk.business_id==MemoryDocument.business_id
    )).outerjoin(MemoryDocumentState,state_join()).outerjoin(SemanticVector,and_(
        SemanticVector.chunk_id==MemoryChunk.id,SemanticVector.business_id==tenant,SemanticVector.model==model_key
    )).filter(MemoryChunk.business_id==tenant,active_state(),SemanticVector.chunk_id.is_(None))


def ensure_state(db,tenant,did):
    row=db.query(MemoryDocumentState).filter_by(business_id=tenant,document_id=did).first()
    if row is None:
        row=MemoryDocumentState(business_id=tenant,document_id=did,root_id=did,version=1,active=True)
        db.add(row);db.flush()
    return row


async def index_pending(db,tenant,limit=16,gateway=None):
    if not tenant or type(limit) is not int or not 1<=limit<=64:
        raise ValueError("Invalid indexing request")
    gateway=gateway or ollama_gateway
    model,key=model_identity(gateway)
    with execution_lock(db.get_bind(),"memory-index:"+tenant) as held:
        if not held:return {"indexed":0,"attempted":0,"model":model,"busy":True}
        _lock(db,tenant)
        now=_now(db)
        # Old model rows never participate in the new model's retrieval.
        # Model changes reset durable retry state without deleting old vectors.
        db.query(MemoryDocumentState).filter(MemoryDocumentState.business_id==tenant,
            MemoryDocumentState.active.is_(True),or_(MemoryDocumentState.model_key.is_(None),MemoryDocumentState.model_key!=key)
        ).update({"model_key":key,"status":"pending","attempts":0,"indexed_count":0,
                  "next_attempt_at":0,"lease_until":0,"claim_token":None,"error":None},synchronize_session=False)
        db.flush();db.expire_all()
        candidates=pending_chunks(db,tenant,key).filter(or_(MemoryDocumentState.document_id.is_(None),
            and_(MemoryDocumentState.next_attempt_at<=now,MemoryDocumentState.lease_until<=now,
                 MemoryDocumentState.status!="failed")))
        # Interleave documents so a long report cannot starve small new sources.
        ranked=candidates.with_entities(MemoryChunk.id.label("cid"),func.row_number().over(partition_by=MemoryChunk.document_id,order_by=(MemoryChunk.chunk_index,MemoryChunk.id)).label("rn")).subquery()
        rows=db.query(MemoryChunk).join(ranked,MemoryChunk.id==ranked.c.cid).order_by(ranked.c.rn,MemoryChunk.created_at,MemoryChunk.id).limit(limit).all()
        work=[(row.id,row.document_id,row.content) for row in rows]
        token=str(uuid4())
        for did in set(x[1] for x in work):
            state=ensure_state(db,tenant,did)
            state.model_key=key;state.status="indexing";state.claim_token=token;state.lease_until=now+180
        db.commit()
        if not work:return {"indexed":0,"attempted":0,"model":model,"provider_available":None}
        sem=asyncio.Semaphore(2)
        async def embed(item):
            async with sem:
                try:
                    with inference_tenant(tenant):
                        vector=await gateway.genuine_embedding(item[2],model)
                    return (item,vector,signatures(vector)) if vector is not None else (item,None,None)
                except Exception:
                    return item,None,None
        # Native batched inference reduces provider round trips; fallback for
        # single-chunk jobs and legacy test/adapter contracts only.
        batch=getattr(gateway,"genuine_embeddings",None)
        if callable(batch) and len(work)>1:
            async def embed_batch(items):
                try:
                    with inference_tenant(tenant):
                        vectors=await batch([x[2] for x in items],model)
                    if len(vectors)!=len(items):raise ValueError("Wrong embedding count")
                    return [(item,v,signatures(v)) if v is not None else (item,None,None) for item,v in zip(items,vectors)]
                except Exception:
                    return [(item,None,None) for item in items]
            outcomes=[]
            for offset in range(0,len(work),16):outcomes.extend(await embed_batch(work[offset:offset+16]))
        else:
            outcomes=await asyncio.gather(*(embed(item) for item in work))
        tenant_lifecycle_lock(db,tenant)
        _lock(db,tenant)
        indexed=0
        errors=set()
        doc_ids={x[1] for x in work};chunk_ids={x[0] for x in work}
        states={row.document_id:row for row in db.query(MemoryDocumentState).filter(
            MemoryDocumentState.business_id==tenant,MemoryDocumentState.document_id.in_(doc_ids),
            MemoryDocumentState.active.is_(True),MemoryDocumentState.claim_token==token,MemoryDocumentState.model_key==key).all()}
        chunks={row.id:row for row in db.query(MemoryChunk).filter(MemoryChunk.business_id==tenant,MemoryChunk.id.in_(chunk_ids)).all()}
        stored={row.chunk_id:row for row in db.query(SemanticVector).filter(SemanticVector.business_id==tenant,SemanticVector.chunk_id.in_(chunk_ids)).all()}
        for (cid,did,content),vector,bands in outcomes:
            if did not in states:continue
            if vector is None:
                errors.add(did);continue
            chunk=chunks.get(cid)
            if chunk is None or chunk.content!=content or chunk.document_id!=did:continue
            row=stored.get(cid)
            if row is None:
                row=SemanticVector(chunk_id=cid,business_id=tenant);db.add(row)
            elif row.business_id!=tenant:raise PermissionError("Vector tenant mismatch")
            row.model,row.dimension,row.vector=key,len(vector),vector
            row.band0,row.band1,row.band2,row.band3=bands
            indexed+=1
        db.flush()
        totals=dict(db.query(MemoryChunk.document_id,func.count()).filter(MemoryChunk.business_id==tenant,MemoryChunk.document_id.in_(doc_ids)).group_by(MemoryChunk.document_id).all())
        remaining_counts=dict(pending_chunks(db,tenant,key).with_entities(MemoryChunk.document_id,func.count()).filter(MemoryChunk.document_id.in_(doc_ids)).group_by(MemoryChunk.document_id).all())
        for did,state in states.items():
            total=totals.get(did,0)
            remaining=remaining_counts.get(did,0)
            state.indexed_count=total-remaining;state.claim_token=None;state.lease_until=0
            if not remaining:
                state.status="ready";state.attempts=0;state.error=None;state.next_attempt_at=0
            elif did in errors:
                state.attempts+=1;state.status="failed" if state.attempts>=5 else "retry"
                state.next_attempt_at=_now(db)+min(3600,30*2**state.attempts)
                state.error="Embedding provider unavailable or invalid response"
            else:
                state.status="pending";state.attempts=0;state.error=None;state.next_attempt_at=0
        db.commit()
        return {"indexed":indexed,"attempted":len(work),"model":model,
                "provider_available":bool(indexed),"failed_documents":len(errors)}


def retry_document(db,tenant,did):
    _lock(db,tenant)
    doc=db.query(MemoryDocument).filter_by(business_id=tenant,id=did).first()
    if not doc:raise ValueError("Document unavailable")
    state=ensure_state(db,tenant,did)
    if not state.active or state.lease_until>_now(db):raise ValueError("Document inactive or indexing")
    state.attempts=0;state.next_attempt_at=0;state.lease_until=0;state.claim_token=None;state.status="pending";state.error=None
    db.commit()
    return {"document_id":did,"status":"pending"}


def progress(db,tenant):
    model,key=model_identity(ollama_gateway)
    rows=db.query(MemoryDocument,MemoryDocumentState).outerjoin(MemoryDocumentState,state_join()).filter(
        MemoryDocument.business_id==tenant).order_by(MemoryDocument.created_at.desc()).limit(200).all()
    counts=dict(db.query(MemoryChunk.document_id,func.count()).join(SemanticVector,and_(SemanticVector.chunk_id==MemoryChunk.id,SemanticVector.business_id==MemoryChunk.business_id)).filter(MemoryChunk.business_id==tenant,SemanticVector.model==key).group_by(MemoryChunk.document_id).all())
    return {"model":model,"model_identity":key,"documents":[
        {"document_id":d.id,"title":d.title,"file_type":d.file_type,"source_connector":d.source_connector,
         "version":s.version if s else 1,"root_id":s.root_id if s else d.id,
         "active":s.active if s else True,"total_chunks":d.chunk_count,
         "indexed_chunks":counts.get(d.id,0),
         "status":"superseded" if s and not s.active else "ready" if d.chunk_count and counts.get(d.id,0)==d.chunk_count else s.status if s and s.model_key==key else "pending",
         "attempts":s.attempts if s else 0,"error":s.error if s and s.model_key==key else None}
        for d,s in rows]}


async def retrieve(db, tenant, query, top_k, filters=None):
    model,key = model_identity(ollama_gateway)
    if not db.query(SemanticVector.chunk_id).filter_by(business_id=tenant, model=key).first():
        return []
    db.rollback()
    with inference_tenant(tenant):
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
    ).outerjoin(MemoryDocumentState,state_join()).filter(active_state(),SemanticVector.business_id == tenant, SemanticVector.model == key,
             SemanticVector.dimension == len(vector),
             or_(*(col.in_(near) for col,near in zip(columns,probes)))
    )
    from apps.api.services.memory_ranking import filter_scope
    candidate_cap=600
    rows=filter_scope(rows,filters).order_by(priority.desc(),SemanticVector.chunk_id).limit(candidate_cap+1).all()
    scored = [{"chunk_id": c.id, "document_id": c.document_id, "source_title": title,
               "content": c.content, "score": round(cosine(vector, v.vector),4),
               "score_kind": "genuine_model_cosine_not_verified_relevance",
               "search_strategy": "indexed_angular_lsh_approximate",
               "candidate_limit_applied": len(rows)>candidate_cap, "candidate_count": min(len(rows),candidate_cap),
               "embedding_model": model, "metadata": c.metadata_tags or {}}
              for v,c,title in rows[:candidate_cap]]
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
    from apps.api.core.tenant_context import tenant_ids
    ids=tenant_ids(db,last,1) or tenant_ids(db,"",1)
    if not ids:
        db.rollback()
        return {"indexed":0}
    tenant=ids[0]
    cursor.last_tenant=tenant
    db.commit()  # Advance even if the provider is unavailable.
    with Session(bind=db.get_bind()) as scoped:
        scoped.info.update(oneboard_request=True,oneboard_worker=True)
        scope_tenant_session(scoped,tenant)
        return await index_pending(scoped,tenant,limit=16,gateway=OllamaGateway())
