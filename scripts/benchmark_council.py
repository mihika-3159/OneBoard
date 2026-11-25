"""Paired synthetic recommendation evaluation: single response vs actual council protocol."""
import argparse
import asyncio
import json
from pathlib import Path
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from apps.api.core.database import Base
from apps.api.models.business import Business
from apps.api.models.decision_evidence import Evidence
from apps.api.models.memory import MemoryConflict
from apps.api.services.council_engine import council_engine
from apps.api.services.council_evidence import validate_citations, evidence_inventory, parse_object
from apps.api.services.ollama_gateway import ollama_gateway
from apps.api.services.untrusted_content import DATA_BOUNDARY,quoted_data

CASES=[
 ("pricing","Price differs across documents; review before changing it.","The plan price is 59 USD per month.",True),
 ("onboarding","Review the observed onboarding delay before committing to a target.","Onboarding took fourteen days for the recorded cohort.",False),
 ("support","Investigate the recorded delay without inventing a forecast.","The recorded support response time was 48 hours.",False),
]


def grade(citations, disposition, inventory, conflict):
    checked=validate_citations(citations,inventory)
    # Same rubric: actual evidence reference, conservative review, conflict handling.
    return {"evidence":int(bool(checked)),
        "safe_disposition":int(disposition in ({"resolve_conflict","collect_evidence"} if conflict else {"founder_review","collect_evidence"})),
        "conflict_handling":int(not conflict or disposition=="resolve_conflict")}


async def run():
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    reports=[]
    with Session(engine) as db:
        for name,topic,evidence,conflict in CASES:
            business=Business(name="Synthetic "+name)
            db.add(business);db.commit()
            db.add(Evidence(business_id=business.id,title="Synthetic fixture",source_connector="synthetic",snippet=evidence))
            if conflict:
                db.add(MemoryConflict(business_id=business.id,entity_type="Product",entity_name="Plan",
                    source_a_name="A",source_a_value="59 USD",source_b_name="B",source_b_value="49 USD",
                    explanation="Conflicting source prices",suggested_resolution="Review source records",status="unresolved"))
            db.commit()
            inventory=evidence_inventory(db,business.id)
            prompt=quoted_data("synthetic_evidence",json.dumps(inventory))+"\n"+topic+                '\nReturn JSON {"citations":[{"id":"record id","quote":"exact quote"}],"disposition":"resolve_conflict|founder_review|collect_evidence"}.'
            start=time.monotonic()
            single=await ollama_gateway.chat_complete(messages=[{"role":"user","content":prompt}],system_prompt=DATA_BOUNDARY,format_json=True)
            single_ms=round((time.monotonic()-start)*1000,2)
            parsed=parse_object(single.get("content")) or {}
            single_ok=not single.get("simulated") and not single.get("output_limit_reached")
            single_grade=grade(parsed.get("citations"),parsed.get("disposition"),inventory,conflict) if single_ok else {"evidence":0,"safe_disposition":0,"conflict_handling":0}
            start=time.monotonic()
            meeting=await council_engine.conduct_deliberation(db,business.id,"Synthetic evaluation","custom",topic,["Strategy Adviser","Operations Adviser"])
            structured=meeting.structured_synthesis or {}
            council_ok=meeting.stage=="completed" and not any(a.get("simulated") or a.get("output_limit_reached") for a in meeting.deliberation_transcript)
            council_grade=grade(structured.get("citations"),structured.get("disposition"),inventory,conflict) if council_ok else {"evidence":0,"safe_disposition":0,"conflict_handling":0}
            reports.append({"case":name,"single":{"real_complete":single_ok,"rubric":single_grade,"total":sum(single_grade.values()),"latency_ms":single_ms,"calls":1},
                "council":{"real_complete":council_ok,"rubric":council_grade,"total":sum(council_grade.values()),"latency_ms":round((time.monotonic()-start)*1000,2),"calls":len(meeting.deliberation_transcript)+1}})
    engine.dispose()
    return {"synthetic_only":True,"cases":reports,"paired_delta":sum(x["council"]["total"]-x["single"]["total"] for x in reports),
            "all_real_complete":all(x["single"]["real_complete"] and x["council"]["real_complete"] for x in reports)}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=asyncio.run(run())
    args.output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["all_real_complete"] else 1)
