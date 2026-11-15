"""Workflow AI input boundaries prevent unbounded requests reaching generation."""
import pytest
from pydantic import ValidationError
from apps.api.routers.workflow_router import PromptGenerationRequest, TeachProcessRequest


@pytest.mark.parametrize("prompt", ["", "x" * 8001])
def test_generate_prompt_rejects_invalid_lengths(prompt):
    with pytest.raises(ValidationError):
        PromptGenerationRequest(prompt=prompt)


def test_generate_prompt_accepts_boundary():
    assert len(PromptGenerationRequest(prompt="x" * 8000).prompt) == 8000


@pytest.mark.parametrize("description", ["", "x" * 8001])
def test_teach_process_rejects_invalid_description(description):
    with pytest.raises(ValidationError):
        TeachProcessRequest(description=description)


def test_teach_process_rejects_oversized_examples():
    with pytest.raises(ValidationError):
        TeachProcessRequest(description="Describe the process", examples="x" * 16001)


def test_teach_process_accepts_maximum_examples():
    request = TeachProcessRequest(description="Describe the process", examples="x" * 16000)
    assert len(request.examples) == 16000
