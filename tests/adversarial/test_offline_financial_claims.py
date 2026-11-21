"""Offline fallback must not invent company-specific facts or claim live inference."""
from apps.api.services.ollama_gateway import OllamaGateway


def test_offline_chat_fallback_does_not_fabricate_financials():
    gateway = OllamaGateway(base_url="http://127.0.0.1:1")
    text = gateway._generate_simulated_response(
        [{"role": "user", "content": "What is my company's cash runway?"}],
        None,
        False,
    )
    assert "Offline simulated response" in text
    assert "inference was unavailable" in text
    assert "Northstar Studio" not in text
    assert "$18,450" not in text
    assert "7.2 months" not in text
    assert "Sarah Chen" not in text


def test_offline_chat_fallback_is_independent_of_tenant_prompt():
    gateway = OllamaGateway(base_url="http://127.0.0.1:1")
    a = gateway._generate_simulated_response(
        [{"role": "user", "content": "Company Alpha revenue?"}], None, False
    )
    b = gateway._generate_simulated_response(
        [{"role": "user", "content": "Company Beta payroll?"}], None, False
    )
    assert a == b
    assert "No business facts were independently verified" in a
