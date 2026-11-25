import base64
import hashlib
from datetime import date,datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apps.api.core.database import Base
from apps.api.core.config import settings
from apps.api.models.business import Business,User
from apps.api.models.entities import Invoice
from apps.api.models.memory import MemoryChunk,MemoryDocument
from apps.api.models.operations import SemanticVector,SettlementEvidence,ProviderCredential,ProviderIntent
from apps.api.services import semantic_index,settlement_evidence,provider_staging,data_lifecycle
from apps.api.services.memory_engine import memory_engine

@pytest.fixture
def db():
    import apps.api.models.goals_tasks
    import apps.api.models.agent_council
    import apps.api.models.decision_evidence
    import apps.api.models.integrations
    import apps.api.models.workflow
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()

@pytest.mark.asyncio
async def test_index_never_uses_fake_embedding_and_retrieves_nonlexical(db,monkeypatch):
    a=memory_engine.add_document_with_chunks(db,"a","first","quarterly revenue")
    b=memory_engine.add_document_with_chunks(db,"b","private","private content")
    monkeypatch.setattr(semantic_index.ollama_gateway,"genuine_embedding",AsyncMock(return_value=None))
    assert (await semantic_index.index_pending(db,"a"))["indexed"]==0
    assert db.query(SemanticVector).count()==0
    monkeypatch.setattr(semantic_index.ollama_gateway,"genuine_embedding",AsyncMock(return_value=[1.,0.2,0.1]))
    assert (await semantic_index.index_pending(db,"a"))["indexed"]==1
    assert (await semantic_index.index_pending(db,"b"))["indexed"]==1
    rows=await semantic_index.retrieve(db,"a","turnover",5)
    assert len(rows)==1 and rows[0]["document_id"]==a.id
    assert rows[0]["document_id"]!=b.id
    assert rows[0]["search_strategy"]=="indexed_angular_lsh_approximate"

def test_settlement_fx_period_provenance_and_replay(db):
    db.add(Business(id="a",name="A",currency="AED"))
    db.add(Invoice(id="i",business_id="a",customer_name="Synthetic",invoice_number="1",
                   amount=100,due_date=datetime.utcnow(),status="overdue"))
    db.commit()
    text="synthetic evidence"
    day=date.today().isoformat()
    args=dict(invoice_id="i",source_reference="reference-1",source_sha256=hashlib.sha256(text.encode()).hexdigest(),
              amount="10.00",currency="USD",fx_rate="3.67",fx_source="user statement",settled_on=day,period=day[:7],
              evidence_text=text)
    row=settlement_evidence.record_settlement(db,"a",**args)
    assert row.base_amount=="36.70"
    assert settlement_evidence.record_settlement(db,"a",**args).id==row.id
    for changed in ({"period":"2000-01"},{"evidence_text":"wrong"},{"amount":"30","source_reference":"reference-2"},
                    {"fx_source":"same_currency"},{"amount":"11.00"}):
        with pytest.raises(ValueError):
            settlement_evidence.record_settlement(db,"a",**(args|changed))
        db.rollback()
    assert db.query(SettlementEvidence).count()==1
    summary=settlement_evidence.period_summary(db,"a",day[:7])
    assert summary["totals_by_currency"]=={"AED":"36.70"}
    assert not summary["bank_settlement_verified"]
    assert db.get(Invoice,"i").status=="overdue"
    with pytest.raises(ValueError):
        settlement_evidence.record_settlement(db,"b",**args)

def test_provider_scope_ciphertext_tenant_binding_and_idempotency(db,monkeypatch):
    monkeypatch.setattr(settings,"PROVIDER_TOKEN_KEY",base64.b64encode(b"k"*32).decode())
    exp=datetime.now(timezone.utc)+timedelta(hours=1)
    result=provider_staging.store_credential(db,"a","github",["repo:metadata:read"],"synthetic-token",exp)
    assert result["grants_verified"] is False
    row=db.query(ProviderCredential).one()
    assert "synthetic-token" not in row.encrypted_token
    assert provider_staging.decrypt_token(row)=="synthetic-token"
    row.business_id="b"
    from cryptography.exceptions import InvalidTag
    with pytest.raises(InvalidTag):
        provider_staging.decrypt_token(row)
    db.rollback()
    args=("github","repo:metadata:read","abcdefgh")
    one=provider_staging.stage_intent(db,"a",*args)
    assert provider_staging.stage_intent(db,"a",*args)==one
    assert not one["provider_contacted"]
    with pytest.raises(ValueError):
        provider_staging.stage_intent(db,"b",*args)
    with pytest.raises(ValueError):
        provider_staging.store_credential(db,"a","github",["repo:write"],"synthetic",exp)
    assert provider_staging.revoke_credential(db,"a","github")["local_credential_removed"]
    assert db.query(ProviderIntent).one().state=="cancelled_local"

def test_owner_export_retention_and_workspace_deletion(db):
    for tenant in ("a","b"):
        db.add(Business(id=tenant,name=tenant,owner_id=tenant+"owner"))
        db.add(User(id=tenant+"owner",business_id=tenant,email=tenant+"@example.test",name=tenant,hashed_password="secret-hash",api_key="secret-key-"+tenant))
    db.commit()
    a=memory_engine.add_document_with_chunks(db,"a","old","old text")
    b=memory_engine.add_document_with_chunks(db,"b","private","private text")
    aid,bid=a.id,b.id
    a.created_at=datetime.utcnow()-timedelta(days=50)
    db.commit()
    actor=SimpleNamespace(id="aowner",business_id="a")
    assert data_lifecycle.owner(db,actor).id=="a"
    page=data_lifecycle.export_page(db,"a","users")
    assert len(page["rows"])==1 and "secret" not in repr(page)
    with pytest.raises(PermissionError):
        data_lifecycle.owner(db,SimpleNamespace(id="bowner",business_id="a"))
    assert data_lifecycle.delete_documents(db,"a",[bid])==0
    assert data_lifecycle.apply_retention(db,"a")==0
    data_lifecycle.set_retention(db,"a",30)
    assert data_lifecycle.apply_retention(db,"a")==1
    db.commit()
    assert db.get(MemoryDocument,aid) is None
    assert db.get(MemoryDocument,bid) is not None
    with pytest.raises(ValueError):
        data_lifecycle.delete_workspace(db,actor,"wrong")
    receipt=data_lifecycle.delete_workspace(db,actor,"DELETE a")
    assert not receipt["backup_copies_deleted"]
    assert db.get(Business,"a") is None and db.get(Business,"b") is not None


def test_ingestion_rolls_back_document_when_chunk_write_fails(db):
    from sqlalchemy import event
    engine=db.get_bind()
    def fail_chunk(conn,cursor,statement,params,context,many):
        if statement.lstrip().upper().startswith("INSERT INTO MEMORY_CHUNKS"):
            raise RuntimeError("synthetic chunk write failure")
    event.listen(engine,"before_cursor_execute",fail_chunk)
    try:
        with pytest.raises(RuntimeError,match="synthetic chunk write failure"):
            memory_engine.add_document_with_chunks(db,"a","atomic","one\n\ntwo")
        db.rollback()
    finally:
        event.remove(engine,"before_cursor_execute",fail_chunk)
    assert db.query(MemoryDocument).filter_by(business_id="a").count()==0
    assert db.query(MemoryChunk).filter_by(business_id="a").count()==0

@pytest.mark.asyncio
async def test_scheduled_index_uses_fresh_gateway_and_only_one_chunk(db,monkeypatch):
    db.add(Business(id="a",name="A"))
    db.commit()
    memory_engine.add_document_with_chunks(db,"a","queued","one\n\ntwo")
    worker=SimpleNamespace(get_model_for_task=lambda task:"nomic-embed-text",
                           genuine_embedding=AsyncMock(return_value=[1.,0.2]))
    monkeypatch.setattr(semantic_index,"OllamaGateway",lambda:worker)
    monkeypatch.setattr(semantic_index.ollama_gateway,"get_model_for_task",lambda task:"nomic-embed-text")
    monkeypatch.setattr(semantic_index.ollama_gateway,"genuine_embedding",AsyncMock(side_effect=AssertionError("API gateway used in worker")))
    assert (await semantic_index.scheduled_index(db))["indexed"]==1
    worker.genuine_embedding.assert_awaited_once()
    assert db.query(SemanticVector).count()==1
