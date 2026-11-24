"""P1 bounded memory search, tenant integrity, and database query budget."""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.goals_tasks
import apps.api.models.decision_evidence
import apps.api.models.agent_council
import apps.api.models.workflow
import apps.api.models.integrations
from apps.api.models.memory import MemoryChunk, MemoryDocument
from apps.api.routers.memory_router import SearchRequest
from apps.api.services.memory_engine import memory_engine
import apps.api.services.memory_engine as memory_module


@pytest.fixture
def isolated():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db, engine
    engine.dispose()


@pytest.mark.asyncio
async def test_search_scans_only_bounded_chunks_without_n_plus_one_queries(
    isolated, monkeypatch
):
    db, engine = isolated
    tenant = str(uuid4())
    doc = MemoryDocument(
        business_id=tenant, title="Tenant-owned synthetic document",
        content_hash="a" * 64, file_type="txt",
    )
    db.add(doc)
    db.flush()
    db.add_all([
        MemoryChunk(
            business_id=tenant, document_id=doc.id,
            chunk_index=i,
            content=f"Synthetic #{i} priority-retrieval", metadata_tags={},
        )
        for i in range(1005)
    ])
    db.commit()
    embedding = AsyncMock(return_value=[0.0, 1.0])
    monkeypatch.setattr(memory_module.ollama_gateway, "generate_embedding", embedding)
    sql = []
    def count_select(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            sql.append(statement)
    event.listen(engine, "before_cursor_execute", count_select)
    try:
        results = await memory_engine.search_semantic_memory(
            db, tenant, "priority-retrieval", top_k=5
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_select)
    assert len(results) == 5
    assert all(x["source_title"] == doc.title for x in results)
    assert all(x["candidate_limit_applied"] is True for x in results)
    assert all(x["candidate_count"] == 1000 for x in results)
    assert all("not_verified_relevance" in x["score_kind"] for x in results)
    assert len(sql) == 1, f"Expected one joined SELECT instead of N+1 lookups: {len(sql)}"
    embedding.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_rejects_cross_tenant_document_id_and_orphan_chunk(
    isolated, monkeypatch
):
    db, _ = isolated
    first, second = str(uuid4()), str(uuid4())
    a = MemoryDocument(
        business_id=first, title="Allowed", content_hash="b" * 64
    )
    b = MemoryDocument(
        business_id=second, title="Private", content_hash="c" * 64
    )
    db.add_all([a, b])
    db.flush()
    db.add_all([
        MemoryChunk(business_id=first, document_id=a.id,
                    chunk_index=0, content="Allowed synthetic information"),
        MemoryChunk(business_id=first, document_id=b.id,
                    chunk_index=1, content="Mismatched cross-tenant document"),
        MemoryChunk(business_id=first, document_id=str(uuid4()),
                    chunk_index=2, content="Orphan chunk"),
        MemoryChunk(business_id=second, document_id=b.id,
                    chunk_index=0, content="Private secret"),
    ])
    db.commit()
    monkeypatch.setattr(
        memory_module.ollama_gateway, "generate_embedding",
        AsyncMock(return_value=[0.1, 0.2])
    )
    results = await memory_engine.search_semantic_memory(
        db, first, "Allowed synthetic", top_k=10
    )
    assert len(results) == 1
    assert results[0]["document_id"] == a.id
    assert "Private" not in repr(results)
    assert "Orphan" not in repr(results)
    assert results[0]["candidate_limit_applied"] is False


@pytest.mark.parametrize("payload", [
    {"query": ""}, {"query": " " * 2049}, {"query": "a" * 2049},
    {"query": "x", "top_k": 0}, {"query": "x", "top_k": -5},
    {"query": "x", "top_k": 21}, {"query": "x", "top_k": 1000000},
])
def test_router_search_params_have_bounded_limits(payload):
    with pytest.raises(ValidationError):
        SearchRequest(**payload)


@pytest.mark.asyncio
async def test_empty_tenant_memory_skips_unnecessary_ollama_call(isolated, monkeypatch):
    db, _ = isolated
    embedding = AsyncMock()
    monkeypatch.setattr(memory_module.ollama_gateway, "generate_embedding", embedding)
    assert await memory_engine.search_semantic_memory(
        db, str(uuid4()), "No records here", top_k=5
    ) == []
    embedding.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("top_k", [-1, 0, 21, True])
async def test_direct_service_rejects_unbounded_search_before_db(
    isolated, top_k
):
    db, _ = isolated
    with pytest.raises(ValueError, match="top_k"):
        await memory_engine.search_semantic_memory(
            db, "tenant-a", "synthetic query", top_k=top_k
        )
