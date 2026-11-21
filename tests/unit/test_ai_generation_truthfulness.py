"""AI-generated definitions must never silently become unrelated canned business actions."""
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from apps.api.services.natural_language_builder import natural_language_builder
import apps.api.services.natural_language_builder as builder_module


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["workflow", "agent"])
async def test_offline_ai_does_not_fabricate_generated_definition(monkeypatch, kind):
    fake = AsyncMock(return_value={"simulated": True, "content": json.dumps({
        "name": "Unrelated invoice reminder", "nodes": [], "edges": [],
        "system_prompt": "Unrelated onboarding agent"
    })})
    monkeypatch.setattr(builder_module.ollama_gateway, "chat_complete", fake)
    method = (natural_language_builder.generate_workflow_from_prompt if kind == "workflow"
              else natural_language_builder.generate_agent_from_prompt)
    with pytest.raises(HTTPException) as exc:
        await method("Build a warehouse inventory reconciliation system")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["workflow", "agent"])
async def test_invalid_model_schema_rejected_not_replaced(monkeypatch, kind):
    fake = AsyncMock(return_value={"simulated": False, "content": '{"name":"Incomplete"}'})
    monkeypatch.setattr(builder_module.ollama_gateway, "chat_complete", fake)
    method = (natural_language_builder.generate_workflow_from_prompt if kind == "workflow"
              else natural_language_builder.generate_agent_from_prompt)
    with pytest.raises(HTTPException) as exc:
        await method("Build a warehouse inventory reconciliation system")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_valid_agent_model_output_retained(monkeypatch):
    payload = {
        "name": "Inventory Auditor", "role_title": "Inventory Auditor",
        "system_prompt": "Compare warehouse stock counts.",
        "allowed_tools": ["read_inventory"], "requires_approval_for": [],
        "max_steps": 3
    }
    fake = AsyncMock(return_value={"simulated": False, "content": json.dumps(payload)})
    monkeypatch.setattr(builder_module.ollama_gateway, "chat_complete", fake)
    result = await natural_language_builder.generate_agent_from_prompt("Audit warehouse inventory")
    assert result["name"] == "Inventory Auditor"
    assert result["simulated"] is False
    assert result["allowed_tools"] == ["read_inventory"]


@pytest.mark.asyncio
async def test_taught_process_does_not_claim_success_on_offline_model(monkeypatch):
    fake = AsyncMock(return_value={"simulated": True, "content": "{}"})
    monkeypatch.setattr(builder_module.ollama_gateway, "chat_complete", fake)
    with pytest.raises(HTTPException) as exc:
        await natural_language_builder.teach_a_process("Audit stock discrepancies")
    assert exc.value.status_code == 503
