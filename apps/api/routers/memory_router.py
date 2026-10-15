from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from apps.api.core.database import get_db
from apps.api.services.memory_engine import memory_engine
from apps.api.services.integrations.local_files import local_files_adapter
from apps.api.models.memory import MemoryDocument, MemoryConflict
from apps.api.services.seed_data import DEMO_BUSINESS_ID

router = APIRouter(prefix="/api/memory", tags=["Business Memory"])

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5

class ResolveConflictRequest(BaseModel):
    resolution: str
    action: str # "confirm_source_a", "confirm_source_b", "custom"

@router.post("/search")
async def search_memory(req: SearchRequest, db: Session = Depends(get_db)):
    results = await memory_engine.search_semantic_memory(
        db=db,
        business_id=DEMO_BUSINESS_ID,
        query=req.query,
        top_k=req.top_k
    )
    return {"query": req.query, "results": results}

@router.get("/graph")
def get_entity_graph(db: Session = Depends(get_db)):
    return memory_engine.get_relationship_graph(db=db, business_id=DEMO_BUSINESS_ID)

@router.get("/conflicts")
def get_memory_conflicts(db: Session = Depends(get_db)):
    return memory_engine.detect_conflicts(db=db, business_id=DEMO_BUSINESS_ID)

@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: str, req: ResolveConflictRequest, db: Session = Depends(get_db)):
    conflict = db.query(MemoryConflict).filter(MemoryConflict.id == conflict_id).first()
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict not found")
    conflict.status = "resolved"
    conflict.suggested_resolution = req.resolution
    db.commit()
    return {"status": "resolved", "conflict_id": conflict_id}

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    contents = await file.read()
    filename = file.filename or "uploaded_doc"
    try:
        extracted = local_files_adapter.extract_text(contents, filename)
        doc = memory_engine.add_document_with_chunks(
            db=db,
            business_id=DEMO_BUSINESS_ID,
            title=filename,
            raw_content=extracted["text"],
            file_type=extracted["file_type"]
        )
        return {"status": "success", "document_id": doc.id, "chunks": doc.chunk_count, "title": doc.title}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process document: {e}")
