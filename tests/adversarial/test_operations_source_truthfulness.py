"""Operations must never show mock Northstar customers in a real tenant."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from apps.api.core.database import Base
import apps.api.models.business
import apps.api.models.entities
import apps.api.models.memory
import apps.api.models.workflow
import apps.api.models.goals_tasks
import apps.api.models.agent_council
import apps.api.models.decision_evidence
import apps.api.models.integrations
import apps.api.models.operations
from apps.api.models.business import Business
from apps.api.models.entities import Customer, Commitment, Lead
from apps.api.routers.business_router import get_operations_overview


@pytest.fixture
def seeded():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        a, b = str(uuid4()), str(uuid4())
        db.add_all([Business(id=a, name="Synthetic A", currency="AED"),
                    Business(id=b, name="Synthetic B", currency="USD")])
        db.add_all([
            Customer(business_id=a, name="Alice", company="One", mrr=123.45,
                     status="active", health_score=85),
            Commitment(business_id=a, title="Real recorded task",
                       counterparty="Alice", deadline=datetime.utcnow() + timedelta(days=5),
                       risk_level="critical", status="pending", evidence_source=None),
            Lead(business_id=a, name="Prospect", pipeline_stage="Qualified",
                 estimated_value=250, source="Inbound"),
            Customer(business_id=b, name="Foreign Secret", mrr=9999.99, status="active"),
            Commitment(business_id=b, title="Foreign Sensitive Promise",
                       counterparty="Foreign Secret", deadline=datetime.utcnow()),
            Lead(business_id=b, name="Foreign Lead", estimated_value=99999),
        ])
        db.commit()
        yield db, a, b
    engine.dispose()


def test_operations_are_scoped_and_use_real_counts(seeded):
    db, a, b = seeded
    result = get_operations_overview(current_user=SimpleNamespace(business_id=a), db=db)
    assert result["source"] == "tenant_application_records_unverified"
    assert result["counts"] == {"commitments": 1, "customers": 1, "leads": 1}
    assert result["commitments"][0]["title"] == "Real recorded task"
    assert result["customers"][0]["name"] == "Alice"
    assert result["customers"][0]["mrr"] == 123.45
    assert result["customers"][0]["health_score"] is None
    assert result["leads"][0]["name"] == "Prospect"
    assert "Foreign" not in str(result)
    assert "99999" not in str(result)


def test_new_workspace_has_true_empty_state(seeded):
    db, a, _ = seeded
    empty = str(uuid4())
    db.add(Business(id=empty, name="Empty real workspace", currency="AED"))
    db.commit()
    result = get_operations_overview(current_user=SimpleNamespace(business_id=empty), db=db)
    assert all(count == 0 for count in result["counts"].values())
    assert result["commitments"] == []
    assert result["customers"] == []
    assert result["leads"] == []


def test_unknown_business_cannot_return_foreign_records(seeded):
    from fastapi import HTTPException
    db, a, _ = seeded
    with pytest.raises(HTTPException) as error:
        get_operations_overview(current_user=SimpleNamespace(business_id=str(uuid4())), db=db)
    assert error.value.status_code == 404
