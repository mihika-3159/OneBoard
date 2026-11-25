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
