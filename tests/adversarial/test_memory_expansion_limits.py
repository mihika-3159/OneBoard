"""Regression checks for bounded post-extraction memory uploads."""
import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from apps.api.routers import memory_router


def test_rejects_expanded_document_before_database_write(monkeypatch):
    monkeypatch.setattr(
        memory_router.local_files_adapter,
        "extract_text",
        lambda content, filename: {"text": "x" * (memory_router.MAX_EXTRACTED_CHARS + 1), "file_type": "xlsx"},
    )
    calls = []
    monkeypatch.setattr(
        memory_router.memory_engine,
        "add_document_with_chunks",
        lambda **kwargs: calls.append(kwargs),
    )
    upload = UploadFile(filename="compressed.xlsx", file=BytesIO(b"small zip fixture"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(memory_router.upload_document(
            file=upload,
            current_user=SimpleNamespace(business_id="tenant-a"),
            db=SimpleNamespace(),
        ))
    assert exc.value.status_code == 413
    assert calls == []


def test_rejects_nontext_parser_output_before_database_write(monkeypatch):
    monkeypatch.setattr(
        memory_router.local_files_adapter,
        "extract_text",
        lambda content, filename: {"text": None, "file_type": "pdf"},
    )
    calls = []
    monkeypatch.setattr(
        memory_router.memory_engine,
        "add_document_with_chunks",
        lambda **kwargs: calls.append(kwargs),
    )
    upload = UploadFile(filename="invalid.pdf", file=BytesIO(b"invalid"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(memory_router.upload_document(
            file=upload,
            current_user=SimpleNamespace(business_id="tenant-a"),
            db=SimpleNamespace(),
        ))
    assert exc.value.status_code == 413
    assert calls == []
