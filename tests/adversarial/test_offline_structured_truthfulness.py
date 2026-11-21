import json

import pytest

from apps.api.services.ollama_gateway import OllamaGateway


@pytest.mark.parametrize("prompt", [
    "boardroom deliberation: should I raise prices?",
    "review my company revenue and cash runway",
    "What is Sarah Chen's customer commitment?",
])
def test_offline_json_does_not_fabricate_financial_evidence(prompt):
    gateway = OllamaGateway(base_url="http://127.0.0.1:1")
    response = json.loads(gateway._generate_simulated_response(
        [{"role": "user", "content": prompt}], None, True
    ))
    assert response["status"] == "unavailable"
    assert response["simulated"] is True
    assert response.get("findings", []) == []
    assert response.get("assumptions", []) == []
    assert response.get("recommendation") is None
    assert response.get("recommended_action") is None
    serialized = json.dumps(response).lower()
    for invented in ("7.2 months", "sarah chen", "$59/mo", "healthy runway"):
        assert invented not in serialized


def test_offline_text_explicitly_disclaims_inference():
    gateway = OllamaGateway(base_url="http://127.0.0.1:1")
    response = gateway._generate_simulated_response(
        [{"role": "user", "content": "Evaluate my finances"}], None, False
    )
    assert "inference was unavailable" in response
    assert "No business facts were independently verified" in response
