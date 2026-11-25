import math
import hashlib
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from apps.api.services.inference_budget import inference_tenant
from apps.api.models.memory import MemoryDocument, MemoryChunk, EntityRelationship, MemoryConflict, MemoryDocumentState
from apps.api.models.entities import Product, Customer, Invoice
from apps.api.services.ollama_gateway import ollama_gateway

class MemoryEngine:
    """
    3-Tier Business Memory Engine:
    1. Structured Memory (Database entities)
    2. Semantic Memory (Chunks + Local Embeddings + Hybrid search)
    3. Relationship Memory (Entity relationship graph)
    With Conflict Detection and Strict Source Provenance.
    """

    @staticmethod
    def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    async def search_semantic_memory(self,db:Session,business_id:str,query:str,top_k:int=5,filters=None):
        """Fuse independently retrieved lexical and genuine-model candidates."""
        if not business_id:raise ValueError("Business ID is required")
        if not isinstance(query,str) or not 1<=len(query.strip())<=2048:raise ValueError("Invalid query length")
        if type(top_k) is not int or not 1<=top_k<=50:raise ValueError("top_k must be between 1 and 50")
        from apps.api.services.semantic_index import retrieve,active_state,state_join
        from apps.api.services.memory_ranking import terms,filter_scope,fuse,feedback_scores
        from apps.api.services.memory_sources import citation
        semantic=await retrieve(db,business_id,query,min(200,max(50,top_k*4)),filters)
        indexed=db.get_bind().dialect.name=="postgresql"
        scope=db.query(MemoryChunk,MemoryDocument,MemoryDocumentState).join(MemoryDocument,
            and_(MemoryChunk.document_id==MemoryDocument.id,MemoryChunk.business_id==MemoryDocument.business_id)
        ).outerjoin(MemoryDocumentState,state_join()).filter(MemoryChunk.business_id==business_id,active_state())
        scope=filter_scope(scope,filters)
        tokens=terms(query)
        cap=200 if indexed else 1000
        if indexed and tokens:
            vector=func.to_tsvector("simple",MemoryChunk.content)
            queries=[func.plainto_tsquery("simple",token) for token in sorted(tokens)[:32]]
            rank=sum(func.ts_rank_cd(vector,q) for q in queries)
            entries=scope.filter(or_(*(vector.op("@@")(q) for q in queries))).order_by(rank.desc(),MemoryChunk.id).limit(cap+1).all()
            strategy="postgresql_indexed_fulltext"
        elif indexed:
            entries=[];strategy="postgresql_indexed_fulltext"
        else:
            entries=scope.order_by(MemoryChunk.created_at.desc(),MemoryChunk.id.desc()).limit(cap+1).all()
            strategy="recent_window_dev"
        lexical=[]
        for chunk,doc,state in entries[:cap]:
            overlap=len(tokens & terms(chunk.content))
            if not overlap:continue
            lexical.append({"chunk_id":chunk.id,"document_id":doc.id,"source_title":doc.title,
              "content":chunk.content,"score":overlap/max(1,len(tokens)),"metadata":chunk.metadata_tags or {},
              "search_strategy":strategy,"candidate_limit_applied":len(entries)>cap,"candidate_count":min(len(entries),cap),
              "citation":citation(doc,chunk,state)})
        lexical.sort(key=lambda row:(-row["score"],row["chunk_id"]))
        if semantic:
            candidates=scope.filter(MemoryChunk.id.in_([x["chunk_id"] for x in semantic])).all()
            sources={c.id:(c,d,state) for c,d,state in candidates}
            semantic=[{**x,"citation":citation(sources[x["chunk_id"]][1],sources[x["chunk_id"]][0],sources[x["chunk_id"]][2])}
                      for x in semantic if x["chunk_id"] in sources and sources[x["chunk_id"]][0].content==x["content"]]
        votes=feedback_scores(db,business_id,query,list({x["chunk_id"] for x in lexical+semantic}))
        return fuse(lexical,semantic,top_k,votes)

    def get_relationship_graph(self,db:Session,business_id:str):
        from apps.api.services.memory_graph import graph
        return graph(db,business_id)

    def detect_conflicts(
        self,
        db: Session,
        business_id: str
    ) -> List[Dict[str, Any]]:
        """
        Inspect across database records and document sources to detect discrepancies.
        e.g. Pricing in product table ($59) vs custom proposal ($49).
        """
        conflicts = db.query(MemoryConflict).filter(MemoryConflict.business_id == business_id).all()
        return [
            {
                "id": c.id,
                "entity_type": c.entity_type,
                "entity_name": c.entity_name,
                "source_a": {"name": c.source_a_name, "value": c.source_a_value},
                "source_b": {"name": c.source_b_name, "value": c.source_b_value},
                "classification": c.discrepancy_classification,
                "explanation": c.explanation,
                "suggested_resolution": c.suggested_resolution,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None
            }
            for c in conflicts
        ]

    def add_document_with_chunks(self,db:Session,business_id:str,title:str,raw_content:str,
                                 file_type:str="txt",source_connector:str="local_file",supersedes_id=None):
        from apps.api.services.memory_sources import ingest
        return ingest(db,business_id,title,raw_content,file_type,source_connector,supersedes_id)

memory_engine = MemoryEngine()
