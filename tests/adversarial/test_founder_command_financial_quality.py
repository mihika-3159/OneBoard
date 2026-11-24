"""Founder Command may not turn incomplete financial records into AI facts."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.goals_tasks
import apps.api.models.agent_council
import apps.api.models.decision_evidence
import apps.api.models.memory
import apps.api.models.workflow
import apps.api.models.integrations
from apps.api.models.business import Business
from apps.api.models.entities import Customer, Expense
from apps.api.routers import model_gateway_router as router


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.mark.asyncio
async def test_invalid_financial_inputs_are_not_sent_to_ai_or_returned_as_recorded(
    db, monkeypatch
):
    a = Business(name="P1 Invalid Data", current_cash_balance=98765, currency="AED")
    b = Business(name="Private Other Tenant", current_cash_balance=999999)
    db.add_all([a, b])
    db.flush()
    db.add_all([
        Customer(
            business_id=a.id, name="Invalid amount", mrr=-9000,
            status="active"
        ),
        Expense(
            business_id=a.id, category="Software", vendor="Ambiguous",
            amount=500, billing_period="quarterly"
        ),
        Customer(
            business_id=b.id, name="Private data", mrr=1111111,
            status="active"
        ),
    ])
    db.commit()
    inference = AsyncMock(return_value={
        "content": "Inference unavailable", "model": "none", "simulated": True,
        "fallback_reason": "provider_unavailable",
    })
    monkeypatch.setattr(router.ollama_gateway, "chat_complete", inference)
    result = await router.handle_founder_command(
        router.FounderCommandRequest(command="Assess the business"),
        SimpleNamespace(business_id=a.id), db,
    )
    prompt = inference.await_args.kwargs["messages"][0]["content"]
    assert "Financial data require correction" in prompt
    assert "Financial record status: needs_review" in prompt
    assert "98765.00" not in prompt
    assert "1111111" not in prompt
    assert "9000.00" not in prompt
    assert "500.00" not in prompt
    assert result["business_state_summary"]["mrr"] is None
    assert result["business_state_summary"]["overdue_receivables"] is None
    assert result["business_state_summary"]["financial_data_verified"] is False
    assert result["business_state_summary"]["financial_data_issues_count"] == 2
    assert result["simulated"] is True


@pytest.mark.asyncio
async def test_unconfigured_finances_do_not_become_claimed_zero_revenue(db, monkeypatch):
    biz = Business(name="P1 New Workspace", current_cash_balance=0)
    db.add(biz)
    db.commit()
    inference = AsyncMock(return_value={
        "content": "No inference", "simulated": True,
        "fallback_reason": "provider_unavailable",
    })
    monkeypatch.setattr(router.ollama_gateway, "chat_complete", inference)
    result = await router.handle_founder_command(
        router.FounderCommandRequest(command="What is my MRR?"),
        SimpleNamespace(business_id=biz.id), db,
    )
    prompt = inference.await_args.kwargs["messages"][0]["content"]
    assert "Financial data have not been configured" in prompt
    assert "MRR: $0" not in prompt
    assert result["business_state_summary"]["mrr"] is None
    assert result["business_state_summary"]["financial_data_status"] == "unconfigured"


@pytest.mark.asyncio
async def test_valid_user_recorded_figures_have_provenance_in_prompt(
    db, monkeypatch
):
    biz = Business(name="P1 Recorded", current_cash_balance=1200, currency="AED")
    db.add(biz)
    db.flush()
    db.add_all([
        Customer(business_id=biz.id, name="Recorded", status="active", mrr=150),
        Expense(business_id=biz.id, category="Infrastructure", vendor="Host",
                amount=300, billing_period="monthly"),
    ])
    db.commit()
    inference = AsyncMock(return_value={
        "content": "Test response", "model": "model", "simulated": False
    })
    monkeypatch.setattr(router.ollama_gateway, "chat_complete", inference)
    result = await router.handle_founder_command(
        router.FounderCommandRequest(command="Show recorded financials"),
        SimpleNamespace(business_id=biz.id), db,
    )
    prompt = inference.await_args.kwargs["messages"][0]["content"]
    assert "User-recorded monthly recurring revenue: AED 150.00" in prompt
    assert "independently reconciled" in prompt
    assert result["business_state_summary"]["mrr"] == 150
    assert result["business_state_summary"]["currency"] == "AED"
    assert result["business_state_summary"]["financial_data_verified"] is False
