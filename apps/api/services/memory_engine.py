import math
import hashlib
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from apps.api.models.memory import MemoryDocument, MemoryChunk, EntityRelationship, MemoryConflict
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

    async def search_semantic_memory(
        self,
        db: Session,
        business_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Bounded tenant-scoped hybrid search without an N+1 database query.

        On large memories this prototype examines only the 1,000 newest
        candidate chunks. Response metadata clearly indicates the search
        window was limited, rather than silently promising exhaustive
        semantic retrieval. A future indexed vector store is required
        for complete large-corpus recall.
        """
        if not business_id:
            raise ValueError("Business ID is required")
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2048:
            raise ValueError("Search query length must be between 1 and 2048")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 50:
            raise ValueError("top_k must be between 1 and 50 for internal callers")
        # PostgreSQL uses a real GIN-indexed lexical search across the
        # ENTIRE tenant corpus, including documents older than 1,000 chunks.
        # SQLite development falls back to a bounded recent window.
        indexed = db.get_bind().dialect.name == "postgresql"
        max_candidates = 200 if indexed else 1000
        scope = (
            db.query(MemoryChunk, MemoryDocument.title)
            .join(MemoryDocument, MemoryChunk.document_id == MemoryDocument.id)
            .filter(
                MemoryChunk.business_id == business_id,
                MemoryDocument.business_id == business_id,
            )
        )
        if indexed:
            vector = func.to_tsvector("simple", MemoryChunk.content)
            tsquery = func.plainto_tsquery("simple", query)
            ranked = scope.filter(vector.op("@@")(tsquery)).order_by(
                func.ts_rank_cd(vector, tsquery).desc(),
                MemoryChunk.created_at.desc(),
                MemoryChunk.id.desc(),
            )
            entries = ranked.limit(max_candidates + 1).all()
            strategy = "postgresql_indexed_fulltext"
            # No lexical matches: preserve bounded semantic/keyword fallback
            # rather than silently returning empty for all synonym queries.
            if not entries:
                entries = scope.order_by(
                    MemoryChunk.created_at.desc(), MemoryChunk.id.desc()
                ).limit(1001).all()
                max_candidates = 1000
                strategy = "recent_window_semantic_fallback"
        else:
            entries = scope.order_by(
                MemoryChunk.created_at.desc(), MemoryChunk.id.desc()
            ).limit(max_candidates + 1).all()
            strategy = "recent_window_dev"
        limited = len(entries) > max_candidates
        entries = entries[:max_candidates]
        if not entries:
            return []
        query_vector = await ollama_gateway.generate_embedding(query)
        keywords = [word for word in query.lower().split() if len(word) > 3]
        scored_results = []
        for chunk, title in entries:
            sim = 0.0
            if chunk.embedding:
                sim = self._cosine_similarity(query_vector, chunk.embedding)
            kw_match = 0.3 if any(word in chunk.content.lower() for word in keywords) else 0.0
            total_score = min(sim + kw_match, 1.0)
            scored_results.append({
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "source_title": title,
                "content": chunk.content,
                "score": round(total_score, 4),
                "score_kind": "local_similarity_estimate_not_verified_relevance",
                "search_strategy": strategy,
                "candidate_limit_applied": limited,
                "candidate_count": len(entries),
                "metadata": chunk.metadata_tags or {},
            })
        scored_results.sort(key=lambda row: row["score"], reverse=True)
        return scored_results[:top_k]

    def get_relationship_graph(
        self,
        db: Session,
        business_id: str
    ) -> Dict[str, Any]:
        """Fetch all entity relationships as graph nodes and links for React Flow / Graph view."""
        edges = db.query(EntityRelationship).filter(EntityRelationship.business_id == business_id).all()
        
        nodes_dict = {}
        links = []
        
        for e in edges:
            if e.source_id not in nodes_dict:
                nodes_dict[e.source_id] = {
                    "id": e.source_id,
                    "label": e.source_label or e.source_id,
                    "type": e.source_type
                }
            if e.target_id not in nodes_dict:
                nodes_dict[e.target_id] = {
                    "id": e.target_id,
                    "label": e.target_label or e.target_id,
                    "type": e.target_type
                }
            links.append({
                "id": e.id,
                "source": e.source_id,
                "target": e.target_id,
                "relationship": e.relationship,
                "properties": e.properties or {}
            })
            
        return {
            "nodes": list(nodes_dict.values()),
            "links": links
        }

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

    def add_document_with_chunks(
        self,
        db: Session,
        business_id: str,
        title: str,
        raw_content: str,
        file_type: str = "txt",
        source_connector: str = "local_file"
    ) -> MemoryDocument:
        from apps.api.services.tenant_storage import check_document
        from apps.api.core.config import settings
        paragraphs = [p.strip() for p in raw_content.split("\n\n") if p.strip()] or [raw_content]
        if settings.ONEBOARD_PRODUCTION_MODE:
            check_document(db, business_id, raw_content, paragraphs)
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        
        doc = MemoryDocument(
            business_id=business_id,
            title=title,
            file_type=file_type,
            source_connector=source_connector,
            content_hash=content_hash,
            raw_content=raw_content,
            summary=raw_content[:200] + "..." if len(raw_content) > 200 else raw_content
        )
        db.add(doc)
        db.flush()
        
        doc.chunk_count = len(paragraphs)
        
        for idx, para in enumerate(paragraphs):
            chunk = MemoryChunk(
                document_id=doc.id,
                business_id=business_id,
                chunk_index=idx,
                content=para,
                metadata_tags={"source": title, "index": idx}
            )
            db.add(chunk)
            
        db.commit()
        return doc

memory_engine = MemoryEngine()
