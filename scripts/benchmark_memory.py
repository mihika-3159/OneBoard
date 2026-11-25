"""Real embedding evaluation on 2,048 realistic synthetic business records.

All corpus vectors go through the same durable index worker and local Ollama
provider as the product. Labels come from the fixture, never a model judge.
No customer records, paid services, or remote database access.
"""
import argparse,asyncio,hashlib,json,os,random,statistics,time
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apps.api.core.database import Base
from apps.api.models.memory import MemoryDocument,MemoryChunk
from apps.api.models.operations import SemanticVector
from apps.api.services import semantic_index as idx
from apps.api.services.memory_engine import memory_engine
from apps.api.services.memory_ranking import record_feedback
from apps.api.services.ollama_gateway import OllamaGateway

CASES=[
 ("NOVA4072","The warehouse refrigeration compressor failed after a voltage surge; frozen goods must be moved to backup cold storage.","What should we do when a freezer motor breaks following an electrical spike?"),
 ("ORBIT5193","The quarterly subscription renewal report shows an unexpected decline in recurring revenue caused by cancellations.","Which financial report describes customers ending memberships and falling ongoing sales?"),
 ("CEDAR6284","The payroll reconciliation revealed duplicate overtime payments; reimbursements require employee acknowledgement and HR signoff.","Where are excess wage transfers for extra working hours being corrected?"),
 ("RIVER7345","The engineering incident review identified expired TLS certificates as the reason customers could not establish secure HTTPS connections.","Which technical incident involved outdated encryption credentials preventing secure website access?"),
 ("EMBER8456","The legal team requested a data processing addendum because a supplier transfers personal information across national borders.","What contract amendment concerns overseas handling of customer privacy information?"),
 ("LUNAR9567","The customer onboarding checklist requires accessibility testing with screen readers before releasing the redesigned checkout.","Which launch checklist asks visually impaired users' assistive software to be tested before purchase flow release?"),
 ("MANGO1638","The procurement audit found that the sole supplier of lithium battery cells missed three consecutive delivery milestones.","Which purchasing record identifies a single energy-cell vendor repeatedly shipping late?"),
 ("ATLAS2749","The marketing attribution report found that organic search traffic generated more qualified leads than paid social advertisements.","Which campaign analysis compares unpaid search engine visitors with sponsored social media prospects?"),
 ("DELTA3851","The cash forecast warns of a liquidity shortage caused by overdue enterprise receivables and an approaching tax payment.","Where is the impending cash crunch due to unpaid customer bills and taxes documented?"),
 ("PINE4962","The technical support incident concerns repeated password reset messages being routed to recipients' spam folders.","What service problem explains recovery emails arriving in junk mail?"),
 ("QUARTZ5073","The product quality investigation found contamination from cleaning solvent in the paint coating on manufactured components.","Which manufacturing defect investigation concerns chemical residue in a surface finish?"),
 ("TERRA6184","The commercial property insurance renewal requires proof of a recently inspected fire suppression sprinkler system.","What insurer paperwork asks for evidence that the building's automatic firefighting equipment passed inspection?"),
 ("HARBOR7295","The hiring plan pauses recruitment of external contractors until the board approves next quarter's operating budget.","Where is the decision to suspend freelance hiring until directors approve spending documented?"),
 ("MAPLE8306","The accounts payable dispute arose because a supplier billed for equipment returned before the warranty expiration.","Which vendor invoice disagreement involves returned hardware still covered by a guarantee?"),
 ("SOLAR9417","The sustainability report recommends replacing diesel delivery vehicles with electric vans to reduce fleet emissions.","Which environmental proposal suggests zero-tailpipe-emission transport for the shipping team?"),
 ("IVORY1528","The disaster recovery tabletop exercise exposed an inability to restore encrypted backups without the missing decryption key.","Which continuity drill found that protected backup copies could not be recovered because the unlock credential was absent?")
]
DISTRACTORS=[
 "Facilities inspected office lighting fixtures and approved replacement bulbs for meeting rooms.",
 "Finance reconciled petty cash receipts and reimbursed travel meals.",
 "The sales team scheduled a regional customer introduction and prepared account notes.",
 "Operations revised the packaging label template for domestic shipment.",
 "Engineering reviewed database pagination and improved response time for the dashboard.",
 "Human resources published the annual holiday calendar and team orientation timetable.",
 "Legal approved the standard trademark usage guidelines for presentation slides.",
 "Procurement compared stationery vendors and negotiated volume discounts on printer paper.",
 "Customer success recorded satisfaction survey comments about the welcome webinar.",
 "Marketing prepared a photography brief for an upcoming trade show booth.",
 "The accounting team recorded monthly office lease payments and utility bills.",
 "IT updated laptop inventory and allocated new monitors to the design team.",
 "Product managers prioritized export formatting and icon alignment in the roadmap.",
 "The logistics team confirmed a routine delivery address update for an office furniture order.",
 "The facilities manager arranged routine elevator servicing and lobby cleaning.",
 "The sales enablement group published an introductory product demonstration transcript.",
 "Quality assurance reviewed packaging dimensions and barcode placement for retail units.",
 "Management documented staff meeting attendance and agreed an internal training schedule.",
 "The operations team requested a routine revision to meeting room booking rules.",
 "Finance reviewed depreciation schedules for office equipment and recorded asset tags.",
 "The design team compared typography and spacing for an internal communications template.",
 "The customer care team updated business hours and the general enquiry phone directory.",
 "The procurement specialist reviewed a purchase order for furniture assembly services.",
 "The board reviewed a summary of office relocation expenses and travel arrangements."
]
def digest(text):return hashlib.sha256(text.encode()).hexdigest()

def make_corpus(db,tenant):
    # Place the labelled records first; newer distractors must not hide them.
    records=[(ref+" "+content,ref) for ref,content,query in CASES]
    rng=random.Random(20261125)
    for i in range(2048-len(records)):
        theme=DISTRACTORS[i%len(DISTRACTORS)]
        records.append((f"Record BR{i:06d}. {theme} Department {rng.choice(['North','East','West','Central'])}. Review date 2026-{1+i%11:02d}-{1+i%27:02d}. Owner team {1+i%17}.",None))
    gold={}
    for offset in range(0,len(records),16):
        group=records[offset:offset+16];raw="\n\n".join(row[0] for row in group)
        d=MemoryDocument(business_id=tenant,title=f"Business archive volume {offset//16+1:03d}",file_type="txt",
                         content_hash=digest(raw),raw_content=raw,chunk_count=len(group))
        db.add(d);db.flush()
        cursor=0
        for i,(body,label) in enumerate(group):
            chunk=MemoryChunk(business_id=tenant,document_id=d.id,chunk_index=i,content=body,
                metadata_tags={"char_start":cursor,"char_end":cursor+len(body),"sha256":digest(body)})
            db.add(chunk);db.flush()
            if label:gold[label]=chunk.id
            cursor+=len(body)+2
    db.commit()
    return gold

def score(ids,target):
    rank=next((i for i,cid in enumerate(ids,1) if cid==target),None)
    return {"hit_at_5":int(rank is not None and rank<=5),"rr_at_5":1/rank if rank and rank<=5 else 0,"rank":rank}

async def evaluate(output):
    model=os.getenv("ONEBOARD_CI_EMBEDDING_MODEL","all-minilm")
    gateway=OllamaGateway()
    gateway.get_model_for_task=lambda task:model
    idx.ollama_gateway=gateway
    engine=create_engine("sqlite://")
    # Import the complete schema before creating the disposable database.
    import apps.api.models.business,apps.api.models.entities,apps.api.models.goals_tasks
    import apps.api.models.workflow,apps.api.models.agent_council,apps.api.models.decision_evidence,apps.api.models.integrations
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            gold=make_corpus(db,"memory-benchmark")
            start=time.perf_counter();indexed=0;batch_calls=0
            while indexed<2048:
                result=await idx.index_pending(db,"memory-benchmark",limit=64,gateway=gateway)
                if result["indexed"]!=result["attempted"] or not result["indexed"]:
                    raise RuntimeError("Real provider did not index every fixture chunk: "+str(result))
                indexed+=result["indexed"];batch_calls+=1
            duration=time.perf_counter()-start
            assert db.query(SemanticVector).count()==2048
            rows=[]
            for ref,body,paraphrase in CASES:
                for mode,query in (("exact",ref),("paraphrase",paraphrase)):
                    tick=time.perf_counter()
                    hybrid=await memory_engine.search_semantic_memory(db,"memory-benchmark",query,5)
                    elapsed=time.perf_counter()-tick
                    semantic=await idx.retrieve(db,"memory-benchmark",query,5)
                    # Explicit lexical-only baseline: temporarily disable the
                    # genuine provider query, not the stored semantic index.
                    original=idx.retrieve
                    async def no_semantic(*a,**kw):return []
                    idx.retrieve=no_semantic
                    try:lexical=await memory_engine.search_semantic_memory(db,"memory-benchmark",query,5)
                    finally:idx.retrieve=original
                    rows.append({"case":ref,"mode":mode,"latency_ms":round(elapsed*1000,2),
                                 "hybrid":score([x["chunk_id"] for x in hybrid],gold[ref]),
                                 "semantic":score([x["chunk_id"] for x in semantic],gold[ref]),
                                 "lexical":score([x["chunk_id"] for x in lexical],gold[ref]),
                                 "citation_verified":all(x["citation"]["offset_verified"] for x in hybrid)})
            metrics={}
            for mode in ("exact","paraphrase","all"):
                cases=[r for r in rows if mode=="all" or r["mode"]==mode]
                metrics[mode]={channel:{key:statistics.mean(r[channel][key] for r in cases)
                       for key in ("hit_at_5","rr_at_5")} for channel in ("hybrid","semantic","lexical")}
            # Feedback must measurably improve a repeated query in a controlled
            # ambiguous case. Do not use these votes in the above held-out eval.
            q="office equipment"
            before=await memory_engine.search_semantic_memory(db,"memory-benchmark",q,5)
            assert len(before)>=3
            target=before[2]["chunk_id"]
            record_feedback(db,"memory-benchmark","fixture-reviewer",q,target,True)
            after=await memory_engine.search_semantic_memory(db,"memory-benchmark",q,5)
            feedback_before=score([r["chunk_id"] for r in before],target)["rr_at_5"]
            feedback_after=score([r["chunk_id"] for r in after],target)["rr_at_5"]
            report={"model":model,"corpus_type":"real model embeddings of synthetic realistic business records",
                    "chunks":2048,"documents":128,"labelled_queries":len(rows),"index_seconds":duration,
                    "index_chunks_per_second":2048/duration,"worker_passes":batch_calls,
                    "median_search_ms":statistics.median(r["latency_ms"] for r in rows),
                    "metrics":metrics,"feedback_repeated_query_rr_before":feedback_before,"feedback_repeated_query_rr_after":feedback_after,
                    "cases":rows}
            Path(output).write_text(json.dumps(report,indent=2),encoding="utf-8")
            print(json.dumps({k:v for k,v in report.items() if k!="cases"}),flush=True)
            assert metrics["exact"]["hybrid"]["hit_at_5"]>=0.95,report["metrics"]
            assert metrics["paraphrase"]["hybrid"]["hit_at_5"]>=0.65,report["metrics"]
            assert metrics["paraphrase"]["semantic"]["hit_at_5"]>=0.50,report["metrics"]
            assert metrics["all"]["hybrid"]["hit_at_5"]>=0.80,report["metrics"]
            assert all(r["citation_verified"] for r in rows)
            assert feedback_after>feedback_before
            assert not await memory_engine.search_semantic_memory(db,"foreign-tenant","NOVA4072",5)
    finally:engine.dispose()

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",default="memory-benchmark.json")
    asyncio.run(evaluate(parser.parse_args().output))
