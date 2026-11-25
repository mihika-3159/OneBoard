"""README public-facing claims must match implemented, verifiable features."""
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"


def test_readme_does_not_advertise_nonexistent_cloud_and_vector_infrastructure():
    source = README.read_text(encoding="utf-8")
    for invented in (
        "ChromaDB Vector Vault",
        "CloudLLM[Google Gemini / Claude / OpenAI]",
        "REST + SSE Streaming",
        "Zero Hallucinated Arithmetic",
        "7 Autonomous Domain Advisers",
        "verifiable accountability ledger",
        "immutable audit ledger",
        "Zero-Token Offline Simulation Engine",
        "ensures all workflows, boardroom sessions, and analyses run seamlessly",
        "High-fidelity local simulation",
    ):
        assert invented not in source


def test_readme_labels_source_quality_and_hosting_unverified():
    source = README.read_text(encoding="utf-8")
    assert "not a production-certified SaaS" in source
    assert "not independently reconciled" in source
    assert "Nine-role executive council" in source
    assert "Server-side AI with honest failure states" in source
    assert "not a distributed durable queue" in source
    assert "TEST_REPORT.md" in source
    assert "P1_ENGINEERING_ACCEPTANCE.md" in source


def test_demo_fixtures_are_not_sold_as_live_client_portfolio():
    source = README.read_text(encoding="utf-8")
    assert "verified evidence records (Stripe exports" not in source
    assert "Live executive council meetings with complete deliberation" not in source
    assert "Cloud-model failover" in source
    assert "not implemented or verified" in source
