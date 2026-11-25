from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from pathlib import Path
import logging
from apps.api.core.database import get_db
from apps.api.core.config import settings
from apps.api.services.tenant_resource_budget import consume_tenant_budget
from apps.api.core.auth import get_current_user, enforce_tenant_boundary, require_founder_role
from apps.api.models.business import User
from apps.api.services.memory_engine import memory_engine
from apps.api.services.integrations.local_files import local_files_adapter
from apps.api.models.memory import MemoryDocument, MemoryConflict

router = APIRouter(prefix="/api/memory", tags=["Business Memory"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB limit
MAX_EXTRACTED_CHARS = 2_000_000  # Bound text persisted after compressed document parsing
ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".xlsx", ".pdf"}  # openpyxl cannot parse legacy .xls
logger = logging.getLogger(__name__)

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2048)
    top_k: int = Field(default=5, ge=1, le=20, strict=True)

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Search query must contain non-whitespace text")
        return value

class ResolveConflictRequest(BaseModel):
    resolution: str
    action: str # "confirm_source_a", "confirm_source_b", "custom"

@router.post("/search")
async def search_memory(
    req: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "memory_search")
    results = await memory_engine.search_semantic_memory(
        db=db,
        business_id=current_user.business_id,
        query=req.query,
        top_k=req.top_k
    )
    return {"query": req.query, "results": results}

@router.get("/graph")
def get_entity_graph(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return memory_engine.get_relationship_graph(db=db, business_id=current_user.business_id)

@router.get("/conflicts")
def get_memory_conflicts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return memory_engine.detect_conflicts(db=db, business_id=current_user.business_id)

@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: str,
    req: ResolveConflictRequest,
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db)
):
    conflict = db.query(MemoryConflict).filter(MemoryConflict.id == conflict_id).first()
    if not conflict:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found")

    enforce_tenant_boundary(conflict.business_id, current_user)

    conflict.status = "resolved"
    conflict.suggested_resolution = req.resolution
    db.commit()
    return {"status": "resolved", "conflict_id": conflict_id}

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(require_founder_role),
    db: Session = Depends(get_db)
):
    if settings.ONEBOARD_PRODUCTION_MODE:
        consume_tenant_budget(db, current_user.business_id, "document_upload")
    # Normalize both POSIX and Windows path separators; reject nameless files.
    filename = Path((file.filename or "").replace("\\", "/")).name
    ext = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file extension. Allowed: " + ", ".join(sorted(ALLOWED_EXTENSIONS))
        )

    # Read at most the limit plus one byte, never the full untrusted upload.
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum allowed limit of {MAX_UPLOAD_BYTES // (1024 * 1024)}MB."
        )

    try:
        extracted = local_files_adapter.extract_text(contents, filename)
    except Exception as exc:
        # Avoid returning parser exceptions, internal paths or document contents.
        logger.warning("Rejected document upload (%s parser: %s)", ext, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document could not be parsed as the declared file type."
        ) from None

    # Compressed PDFs/XLSX can expand far beyond their upload byte size.
    # Reject extracted content before chunking, embedding or persistence.
    text = extracted.get("text")
    if not isinstance(text, str) or len(text) > MAX_EXTRACTED_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Extracted document text exceeds the processing limit."
        )

    try:
        doc = memory_engine.add_document_with_chunks(
            db=db,
            business_id=current_user.business_id,
            title=filename,
            raw_content=extracted["text"],
            file_type=extracted["file_type"]
        )
    except Exception:
        db.rollback()
        logger.exception("Document persistence failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document could not be stored."
        ) from None

    return {
        "status": "success",
        "document_id": doc.id,
        "chunks": doc.chunk_count,
        "title": doc.title,
        "file_type": doc.file_type
    }
