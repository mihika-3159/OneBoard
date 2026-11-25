"""Batch J memory acceptance: durable recovery, source identity, relevance and malformed inputs."""
import asyncio, hashlib, io, random, zipfile
from datetime import datetime
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apps.api.core.database import Base
from apps.api.models.memory import MemoryChunk,MemoryDocument,MemoryDocumentState,MemoryRelevanceFeedback,EntityRelationship
from apps.api.models.operations import SemanticVector
from apps.api.models.entities import Customer,Invoice
from apps.api.services import semantic_index as idx,memory_ranking as ranking
from apps.api.services.memory_engine import memory_engine as memory
from apps.api.services.memory_sources import citation,split_text
from apps.api.services.integrations.local_files import local_files_adapter
from apps.api.services.council_evidence import current_record
from apps.api.services.data_lifecycle import delete_documents

@pytest.fixture
def db():
    import apps.api.models.business,apps.api.models.goals_tasks,apps.api.models.agent_council
    import apps.api.models.decision_evidence,apps.api.models.integrations,apps.api.models.workflow
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:yield db
    engine.dispose()

def doc(db,text,title="Fixture",tenant="a",**kwargs):
    return memory.add_document_with_chunks(db,tenant,title,text,**kwargs)

def worker(model="fixture-model",batch=None,single=None):
    return SimpleNamespace(get_model_for_task=lambda task:model,
        genuine_embeddings=batch or AsyncMock(side_effect=lambda texts,model:[[1.,0.1] for _ in texts]),
        genuine_embedding=single or AsyncMock(return_value=[1.,0.1]))

@pytest.mark.asyncio
async def test_batch_index_retry_model_change_and_progress(db,monkeypatch):
    first=doc(db,"quarterly revenue "*150)
    other=doc(db,"private",tenant="b")
    gateway=worker(batch=AsyncMock(side_effect=lambda texts,model:[None]*len(texts)),single=AsyncMock(return_value=None))
    result=await idx.index_pending(db,"a",gateway=gateway)
    assert result["indexed"]==0 and result["attempted"]>1
    state=db.get(MemoryDocumentState,first.id)
    assert state.status=="retry" and state.attempts==1
    assert (await idx.index_pending(db,"a",gateway=gateway))["attempted"]==0
    idx.retry_document(db,"a",first.id)
    gateway=worker()
    result=await idx.index_pending(db,"a",gateway=gateway)
    assert result["indexed"]==first.chunk_count
    assert gateway.genuine_embeddings.await_count==1
    monkeypatch.setattr(idx,"ollama_gateway",gateway)
    assert idx.progress(db,"a")["documents"][0]["status"]=="ready"
    assert db.query(SemanticVector).filter_by(business_id="b").count()==0
    new=worker("fixture-model-v2")
    monkeypatch.setattr(idx,"ollama_gateway",new)
    assert await idx.retrieve(db,"a","turnover",5)==[]
    assert (await idx.index_pending(db,"a",gateway=new))["indexed"]==first.chunk_count
    assert {v.model for v in db.query(SemanticVector).all()}=={"fixture-model-v2"}
    assert idx.progress(db,"a")["documents"][0]["status"]=="ready"
    assert idx.retry_document(db,"a",first.id,reindex=True)["reindex_requested"]
    assert not db.query(SemanticVector).filter_by(business_id="a").count()
    assert await memory.search_semantic_memory(db,"a","revenue",5)
    assert (await idx.index_pending(db,"a",gateway=new))["indexed"]==first.chunk_count

@pytest.mark.asyncio
async def test_crash_claim_retry_expiry_and_superseded_write_fence(db):
    first=doc(db,"old pricing details")
    async def crash(*args):raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await idx.index_pending(db,"a",gateway=worker(single=AsyncMock(side_effect=crash)))
    state=db.get(MemoryDocumentState,first.id)
    assert state.status=="indexing" and state.claim_token
    assert (await idx.index_pending(db,"a",gateway=worker()))["attempted"]==0
    state.lease_until=0;db.commit()
    first_id=first.id
    async def replace(*args):
        # Another transaction replaces a source while provider work is in flight.
        doc(db,"new pricing details",supersedes_id=first_id)
        return [1.,0.1]
    assert (await idx.index_pending(db,"a",gateway=worker(single=AsyncMock(side_effect=replace))))["indexed"]==0
    assert db.query(SemanticVector).count()==0
    assert not db.get(MemoryDocumentState,first_id).active
    assert (await idx.index_pending(db,"a",gateway=worker()))["indexed"]==1

@pytest.mark.asyncio
async def test_source_versions_dedup_offsets_and_stale_consumer(db):
    raw="--- Page 1 ---\nLegacy annual subscription price is 39.\n\n--- Page 2 ---\nA different clause applies."
    boundary=raw.index("--- Page 2")
    segments=[{"start":0,"end":boundary,"location":"Page 1"},{"start":boundary,"end":len(raw),"location":"Page 2"}]
    first=doc(db,raw,file_type="pdf",source_segments=segments)
    assert doc(db,raw,file_type="pdf").id==first.id
    hits=await memory.search_semantic_memory(db,"a","Legacy annual subscription",5)
    assert hits and hits[0]["citation"]["offset_verified"]
    c=hits[0]["citation"]
    assert raw[c["char_start"]:c["char_end"]]==hits[0]["content"]
    assert c["location"]=="Page 1"
    old_chunk=hits[0]["chunk_id"]
    assert current_record(db,"a","chunk:"+old_chunk)
    second=doc(db,"Annual subscription price is now 59.",supersedes_id=first.id)
    assert db.get(MemoryDocumentState,second.id).version==2
    assert doc(db,"Annual subscription price is now 59.",supersedes_id=first.id).id==second.id
    assert current_record(db,"a","chunk:"+old_chunk) is None
    assert not await memory.search_semantic_memory(db,"a","Legacy",5)
    hits=await memory.search_semantic_memory(db,"a","subscription",5)
    assert hits[0]["document_id"]==second.id
    assert not await memory.search_semantic_memory(db,"b","subscription",5)
    with pytest.raises(ValueError):doc(db,"foreign replacement",tenant="b",supersedes_id=second.id)
    db.rollback()
    assert not await memory.search_semantic_memory(db,"a","subscription",5,{"file_type":"pdf"})
    assert await memory.search_semantic_memory(db,"a","subscription",5,{"document_id":second.id})
    ranking.record_feedback(db,"a","user","subscription",hits[0]["chunk_id"],True)
    assert delete_documents(db,"a",[second.id])==1
    db.commit()
    assert not db.query(MemoryRelevanceFeedback).count()
    assert not db.get(MemoryDocumentState,second.id)

@pytest.mark.asyncio
async def test_real_channels_are_fused_and_feedback_improves_repeated_query(db,monkeypatch):
    a=doc(db,"revenue turnover subscription","A")
    b=doc(db,"revenue turnover subscription","B")
    c=doc(db,"different records","C")
    gw=worker()
    monkeypatch.setattr(idx,"ollama_gateway",gw)
    assert (await idx.index_pending(db,"a",gateway=gw))["indexed"]==3
    hits=await memory.search_semantic_memory(db,"a","revenue",5)
    assert hits and hits[0]["search_strategy"]=="hybrid_reciprocal_rank_fusion"
    assert set(hits[0]["channels"])=={"lexical","semantic"}
    target=next(x for x in hits if x["document_id"] in (a.id,b.id) and x["chunk_id"]!=hits[0]["chunk_id"])
    before=next(i for i,x in enumerate(hits,1) if x["chunk_id"]==target["chunk_id"])
    ranking.record_feedback(db,"a","user","Revenue",target["chunk_id"],True)
    ranking.record_feedback(db,"a","user","revenue",target["chunk_id"],True)
    assert db.query(MemoryRelevanceFeedback).count()==1
    after=await memory.search_semantic_memory(db,"a","revenue",5)
    assert 1/next(i for i,x in enumerate(after,1) if x["chunk_id"]==target["chunk_id"])>1/before
    assert ranking.feedback_scores(db,"a","other query",[target["chunk_id"]])=={}
    with pytest.raises(ValueError):ranking.record_feedback(db,"b","user","revenue",target["chunk_id"],True)

def test_graph_resolves_unique_name_but_not_ambiguous_or_foreign_id(db):
    a=Customer(id="a1",business_id="a",name="Acme");b=Customer(id="b1",business_id="b",name="Private")
    dup1=Customer(id="d1",business_id="a",name="Duplicate");dup2=Customer(id="d2",business_id="a",name="duplicate")
    db.add_all([a,b,dup1,dup2]);db.flush()
    for ident,customer_id,name in [("i1","a1","wrong name"),("i2",None," ACME "),("i3",None,"duplicate"),("i4","b1","Acme")]:
        db.add(Invoice(id=ident,business_id="a",customer_id=customer_id,customer_name=name,invoice_number=ident,amount=1,due_date=datetime.utcnow()))
    db.commit()
    graph=memory.get_relationship_graph(db,"a")
    assert {(e["source"],e["target"]) for e in graph["links"]}=={("Invoice:i1","Customer:a1"),("Invoice:i2","Customer:a1")}
    assert "Private" not in repr(graph)

def test_seeded_malformed_inputs_and_lossless_csv():
    rng=random.Random(20261125)
    for _ in range(80):
        data=b"\xff"+rng.randbytes(rng.randrange(1,200))
        for ext in ("txt","md","json","csv"):
            with pytest.raises((ValueError,UnicodeError,RecursionError)):local_files_adapter.extract_text(data,"bad."+ext)
    for data in (b'{"n":NaN}',b'{"n":1e999}',b'{"n":1,"n":2}',b'{"x":',b'[[[[',b'\x00'):
        with pytest.raises(ValueError):local_files_adapter.extract_text(data,"bad.json")
    for data in (b"a,a\n1,2",b"a,b\n1",b"a,b\n1,2,3",b'a,b\n"unclosed,2'):
        with pytest.raises(ValueError):local_files_adapter.extract_text(data,"bad.csv")
    csv="name,value\n"+"\n".join(f"client{i},{i}" for i in range(300))
    result=local_files_adapter.extract_text(csv.encode(),"valid.csv")
    assert "client299,299" in result["text"]
    for ext in ("pdf","xlsx"):
        with pytest.raises(ValueError):local_files_adapter.extract_text(b"invalid compressed document","bad."+ext)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED) as z:z.writestr("bomb.xml",b"0"*(33*1024*1024))
    with pytest.raises(ValueError):local_files_adapter.extract_text(buffer.getvalue(),"bomb.xlsx")

def test_spreadsheet_extracts_late_rows_and_every_sheet():
    from openpyxl import Workbook
    book=Workbook();sheet=book.active;sheet.title="Main"
    for i in range(150):sheet.append([i,"record "+str(i)])
    book.create_sheet("Secondary").append(["secondary important record"])
    buffer=io.BytesIO();book.save(buffer);book.close()
    data=local_files_adapter.extract_text(buffer.getvalue(),"valid.xlsx")
    assert "record 149" in data["text"] and "secondary important record" in data["text"]
    assert data["metadata"]["row_count"]==151
    assert any(p[3]=="Sheet Secondary" for p in split_text(data["text"],"xlsx",data["metadata"]["segments"]))

@pytest.mark.asyncio
async def test_batch_gateway_validates_order_and_charges_every_input(monkeypatch):
    import httpx
    from apps.api.services.ollama_gateway import OllamaGateway
    from apps.api.services.inference_budget import estimated_tokens
    gw=OllamaGateway()
    post=AsyncMock(return_value=httpx.Response(200,json={"embeddings":[[1.,0.1],[0.1,1.]]}))
    monkeypatch.setattr(gw,"_post_inference",post)
    from apps.api.core.config import settings
    from apps.api.services.inference_budget import inference_tenant
    monkeypatch.setattr(settings,"OLLAMA_MODEL_DIGESTS",{"fixture":"sha256:"+("a"*64)})
    with inference_tenant("synthetic"):
        result=await gw.genuine_embeddings(["first","second"],"fixture")
    assert result==[[1.,0.1],[0.1,1.]]
    assert post.call_args.args[0]=="/api/embed"
    assert estimated_tokens(post.call_args.args[1])==11
    with inference_tenant("synthetic"):
        assert await gw.genuine_embeddings(["second","first"],"fixture")==list(reversed(result))
    assert post.await_count==1
    post.return_value=httpx.Response(200,json={"embeddings":[[1.],[1.,2.]]})
    assert await gw.genuine_embeddings(["third","fourth"],"fixture")==[None,None]


def test_parser_location_cannot_be_forged_by_page_marker():
    raw="--- Page 1 ---\nContent\n--- Page 99 ---\nFalse marker"
    assert all(p[3] is None for p in split_text(raw,"pdf"))
    assert all(p[3]=="Page 1" for p in split_text(raw,"pdf",[{"start":0,"end":len(raw),"location":"Page 1"}]))
