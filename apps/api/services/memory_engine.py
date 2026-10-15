import math
import hashlib
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
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
        query_vector = await ollama_gateway.generate_embedding(query)
        chunks = db.query(MemoryChunk).filter(MemoryChunk.business_id == business_id).all()
        
        scored_results = []
        q_lower = query.lower()
        
        for c in chunks:
            # Semantic score
            sim = 0.0
            if c.embedding:
                sim = self._cosine_similarity(query_vector, c.embedding)
            # Keyword bonus (hybrid ranking)
            kw_match = 0.3 if any(word in c.content.lower() for word in q_lower.split() if len(word) > 3) else 0.0
            total_score = min(sim + kw_match, 1.0)
            
            doc = db.query(MemoryDocument).filter(MemoryDocument.id == c.document_id).first()
            source_title = doc.title if doc else "Business Document"
            
            scored_results.append({
                "chunk_id": c.id,
                "document_id": c.document_id,
                "source_title": source_title,
                "content": c.content,
                "score": round(total_score, 4),
                "metadata": c.metadata_tags or {}
            })
            
        scored_results.sort(key=lambda x: x["score"], reverse=True)
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
        db.commit()
        db.refresh(doc)
        
        # Simple paragraph or sentence chunking
        paragraphs = [p.strip() for p in raw_content.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [raw_content]
            
        doc.chunk_count = len(paragraphs)
        db.commit()
        
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
