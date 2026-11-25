import json
from apps.api.services.council_evidence import adviser_record, synthesis_record, validate_citations


def test_fabricated_cross_tenant_and_misquoted_evidence_rejected():
    inventory = {"chunk:owned": {"text": "Revenue is not independently verified.", "source": "tenant_document"}}
    assert validate_citations([{"id": "chunk:other", "quote": "Revenue is not independently verified."}], inventory) is None
    assert validate_citations([{"id": "chunk:owned", "quote": "Revenue is independently verified."}], inventory) is None
    assert validate_citations([{"id": "chunk:owned", "quote": "not independently verified"}], inventory)


def test_synthesis_requires_real_argument_and_matching_citations():
    inventory = {"chunk:owned": {"text": "Review customer onboarding records.", "source": "tenant_document"},
                 "conflict:c": {"text": "old price versus new price", "source": "unresolved_conflict"}}
    refs = [{"id": "chunk:owned", "quote": "customer onboarding records"}]
    record = adviser_record({"content": json.dumps({"position": "Review customer onboarding records.", "citations": refs})}, inventory)
    transcript = [{"argument_id": "argument-1", "adviser": "Operations", "stage": "independent_analysis",
                   "content": record["position"], **record}]
    response = {"content": json.dumps({"arguments": [{"id": "argument-1", "quote": "customer onboarding records"}], "citations": refs})}
    linked = synthesis_record(response, transcript, inventory)
    assert linked["disposition"] == "resolve_conflict"
    assert not linked["claim_verification"]
    assert synthesis_record({"content": response["content"], "output_limit_reached": True}, transcript, inventory)["status"] == "review_required"
    response["content"] = response["content"].replace("argument-1", "argument-2")
    assert synthesis_record(response, transcript, inventory)["status"] == "review_required"


def test_database_citations_are_tenant_scoped_and_detect_changed_records():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from apps.api.core.database import Base
    from apps.api.models.business import Business
    from apps.api.models.decision_evidence import Evidence
    from apps.api.services.council_evidence import evidence_inventory, references_current
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        a,b=Business(name="A"),Business(name="B")
        db.add_all([a,b]);db.commit()
        owned=Evidence(business_id=a.id,title="Owned",source_connector="fixture",snippet="Recorded customer delay was fourteen days.")
        foreign=Evidence(business_id=b.id,title="Foreign",source_connector="fixture",snippet="Do not disclose this tenant record.")
        db.add_all([owned,foreign]);db.commit()
        inventory=evidence_inventory(db,a.id)
        assert "evidence:"+foreign.id not in inventory
        refs=validate_citations([{"id":"evidence:"+owned.id,"quote":"fourteen days"}],inventory)
        assert references_current(db,a.id,refs)
        assert not references_current(db,b.id,refs)
        owned.snippet="Recorded customer delay was seventeen days.";db.commit()
        assert not references_current(db,a.id,refs)
    engine.dispose()


def test_interrupted_meeting_persists_completed_checkpoint_and_blocks_approval():
    import asyncio
    from unittest.mock import patch
    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from apps.api.core.database import Base
    from apps.api.models.business import Business
    from apps.api.models.agent_council import CouncilMeeting
    from apps.api.services.council_engine import council_engine
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant=Business(name="Interrupted fixture")
        db.add(tenant);db.commit()
        async def execute():
            with patch("apps.api.services.council_engine.ollama_gateway.chat_complete",
                       side_effect=[{"simulated":True,"content":"offline"},asyncio.CancelledError()]):
                await council_engine.conduct_deliberation(db,tenant.id,"Review","custom","Review evidence",
                    ["Strategy Adviser","Operations Adviser"])
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(execute())
        meeting=db.query(CouncilMeeting).filter_by(business_id=tenant.id).one()
        assert meeting.stage=="interrupted"
        assert len(meeting.deliberation_transcript)==1
        assert not meeting.recommended_actions
        with pytest.raises(ValueError):
            council_engine.approve_meeting_decision(db,tenant.id,meeting.id)
    engine.dispose()
