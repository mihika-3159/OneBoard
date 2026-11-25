"""Deterministic bounded reciprocal rank fusion; feedback is tenant/query scoped."""
import hashlib,re,unicodedata
from sqlalchemy import func
from apps.api.models.memory import MemoryDocument,MemoryChunk,MemoryRelevanceFeedback
from apps.api.services.tenant_storage import _lock

STOPWORDS=frozenset("a an the is are was were be been being of for to in on at by with as and or but it its this that these those what which who whom when where why how can could should would will do does did has have had from about into their our your my me us they them we you not".split())

def terms(text):
    words=set(re.findall(r"\w+",unicodedata.normalize("NFKC",text).casefold()))
    return words-STOPWORDS or words

def query_hash(query):
    return hashlib.sha256(" ".join(unicodedata.normalize("NFKC",query).casefold().split()).encode()).hexdigest()

def filter_scope(scope,filters):
    filters=filters or {}
    if filters.get("file_type"):scope=scope.filter(MemoryDocument.file_type==filters["file_type"])
    if filters.get("source_connector"):scope=scope.filter(MemoryDocument.source_connector==filters["source_connector"])
    if filters.get("document_id"):scope=scope.filter(MemoryDocument.id==filters["document_id"])
    return scope

def fuse(lexical,semantic,top_k,votes=None,query=""):
    votes=votes or {}
    merged={}
    # Identifier/short queries favor literal matches; longer questions favor
    # semantic similarity. Preserve both signals, without promoting weak
    # overlaps above the strongest independent semantic candidates.
    short=len(terms(query))<=2
    weights={"lexical":1.35 if short else 0.65,"semantic":0.85 if short else 1.35}
    for channel,rows in (("lexical",lexical),("semantic",semantic)):
        for rank,row in enumerate(rows,1):
            key=row["chunk_id"]
            target=merged.setdefault(key,{**row,"score":0.0,"channels":[]})
            target["score"]+=weights[channel]/(12+rank)
            target["channels"].append(channel)
            target.setdefault("channel_details",{})[channel]={"rank":rank,"score":row["score"],"strategy":row["search_strategy"],"candidate_count":row["candidate_count"],"candidate_limit_applied":row["candidate_limit_applied"]}
            if row.get("embedding_model"):target["embedding_model"]=row["embedding_model"]
            target["candidate_limit_applied"]=target["candidate_limit_applied"] or row["candidate_limit_applied"]
    for key,row in merged.items():
        # Bounded user relevance adjustment; never invent a candidate.
        row["score"]+=max(-1,min(1,votes.get(key,0)))*0.025
        row["score"]=round(row["score"],6)
        row["score_kind"]="rank_fusion_not_verified_relevance"
        row["search_strategy"]="hybrid_reciprocal_rank_fusion" if semantic and lexical else row["search_strategy"]
    return sorted(merged.values(),key=lambda row:(-row["score"],row["chunk_id"]))[:top_k]

def feedback_scores(db,tenant,query,ids):
    if not ids:return {}
    rows=db.query(MemoryRelevanceFeedback.chunk_id,MemoryRelevanceFeedback.helpful,func.count()).filter(
        MemoryRelevanceFeedback.business_id==tenant,MemoryRelevanceFeedback.query_hash==query_hash(query),
        MemoryRelevanceFeedback.chunk_id.in_(ids)).group_by(MemoryRelevanceFeedback.chunk_id,MemoryRelevanceFeedback.helpful).all()
    scores={}
    for cid,helpful,count in rows:scores[cid]=scores.get(cid,0)+(count if helpful else -count)
    return scores

def record_feedback(db,tenant,user,query,cid,helpful):
    _lock(db,tenant)
    from apps.api.models.memory import MemoryDocumentState
    from apps.api.services.semantic_index import active_state,state_join
    chunk=db.query(MemoryChunk.id).join(MemoryDocument,(MemoryDocument.id==MemoryChunk.document_id)&(MemoryDocument.business_id==MemoryChunk.business_id)).outerjoin(MemoryDocumentState,state_join()).filter(MemoryChunk.business_id==tenant,MemoryChunk.id==cid,active_state()).first()
    if not chunk:raise ValueError("Source chunk unavailable")
    key=query_hash(query)
    row=db.query(MemoryRelevanceFeedback).filter_by(business_id=tenant,query_hash=key,chunk_id=cid,user_id=user).first()
    if row is None:
        if db.query(MemoryRelevanceFeedback).filter_by(business_id=tenant).count()>=20000:raise ValueError("Feedback storage limit reached")
        row=MemoryRelevanceFeedback(business_id=tenant,query_hash=key,chunk_id=cid,user_id=user)
        db.add(row)
    row.helpful=helpful
    db.commit()
    return {"recorded":True}
