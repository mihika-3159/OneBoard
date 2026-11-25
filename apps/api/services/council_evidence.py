"""Bounded tenant evidence inventory and extractive council synthesis.

A citation proves that the quoted text exists in a supplied tenant record,
not that the source is true or that an inferred recommendation is correct.
"""
import hashlib
import json
from apps.api.models.decision_evidence import Evidence
from apps.api.models.memory import MemoryChunk, MemoryConflict, MemoryDocument


def evidence_inventory(db, tenant):
    records = {}
    # Evidence snippets and stored chunks are user-maintained records, not
    # independently verified external facts. Never pass credentials or files.
    for row in db.query(Evidence).filter_by(business_id=tenant).order_by(Evidence.id).limit(12):
        records["evidence:" + row.id] = {"text": row.snippet[:450], "source": "tenant_evidence"}
    chunks = (db.query(MemoryChunk).join(MemoryDocument, (MemoryChunk.document_id == MemoryDocument.id)
              & (MemoryDocument.business_id == tenant))
              .filter(MemoryChunk.business_id == tenant).order_by(MemoryChunk.id).limit(12))
    for row in chunks:
        records["chunk:" + row.id] = {"text": row.content[:450], "source": "tenant_document"}
    conflicts = db.query(MemoryConflict).filter_by(business_id=tenant, status="unresolved").order_by(MemoryConflict.id).limit(12)
    for row in conflicts:
        records["conflict:" + row.id] = {"text": (row.source_a_value + " versus " + row.source_b_value)[:450],
                                       "source": "unresolved_conflict"}
    return records


def exact_quote(text, quote):
    return isinstance(quote, str) and 8 <= len(quote) <= 450 and quote in text


def validate_citations(citations, inventory):
    if not isinstance(citations, list) or len(citations) > 8:
        return None
    result = []
    for entry in citations:
        if not isinstance(entry, dict):
            return None
        ref, quote = entry.get("id"), entry.get("quote")
        if not isinstance(ref, str) or ref not in inventory or not exact_quote(inventory[ref]["text"], quote):
            return None
        if ref in {item["id"] for item in result}:
            return None
        result.append({"id": ref, "quote": quote, "source": inventory[ref]["source"],
                       "snapshot_sha256": hashlib.sha256(inventory[ref]["text"].encode()).hexdigest()})
    return result


def parse_object(value):
    try:
        obj = json.loads(value)
        return obj if isinstance(obj, dict) else None
    except (TypeError, ValueError):
        return None


def adviser_record(result, inventory):
    if result.get("simulated") or result.get("output_limit_reached"):
        return None
    obj = parse_object(result.get("content"))
    if not obj or not isinstance(obj.get("position"), str) or not 1 <= len(obj["position"]) <= 1000:
        return None
    refs = validate_citations(obj.get("citations"), inventory)
    if refs is None:
        return None
    return {"position": obj["position"], "citations": refs,
            "evidence_status": "reference_verified_not_claim_verified" if refs else "unsupported"}


def synthesis_record(result, transcript, inventory):
    """Accept only extractive links to actual adviser arguments and records.

    Free-form generated recommendations never enter executable tasks.
    The synthesis selects exact quotes and a conservative decision category.
    """
    usable = {entry["argument_id"]: entry for entry in transcript
              if entry.get("stage") == "independent_analysis" and entry.get("evidence_status") == "reference_verified_not_claim_verified"}
    default = {"status": "review_required", "arguments": [], "citations": [],
               "disposition": "collect_evidence", "uncertainty": "high"}
    if result.get("simulated") or result.get("output_limit_reached"):
        return default
    obj = parse_object(result.get("content"))
    if not obj or not isinstance(obj.get("arguments"), list) or not 1 <= len(obj["arguments"]) <= 9:
        return default
    refs = validate_citations(obj.get("citations"), inventory)
    if not refs:
        return default
    arguments = []
    for link in obj["arguments"]:
        if not isinstance(link, dict):
            return default
        key, quote = link.get("id"), link.get("quote")
        if not isinstance(key, str) or key not in usable or not exact_quote(usable[key]["content"], quote):
            return default
        if key in {item["id"] for item in arguments}:
            return default
        arguments.append({"id": key, "adviser": usable[key]["adviser"], "quote": quote})
    permitted = {c["id"] for a in arguments for c in usable[a["id"]]["citations"]}
    if any(c["id"] not in permitted for c in refs):
        return default
    conflict = any(row["source"] == "unresolved_conflict" for row in inventory.values())
    return {"status": "linked_review", "arguments": arguments, "citations": refs,
            "disposition": "resolve_conflict" if conflict else "founder_review",
            "uncertainty": "high" if conflict or len(arguments) < 2 else "unquantified",
            "claim_verification": False}
