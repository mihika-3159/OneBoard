"""Founder command input boundaries must fail before inference is invoked."""
import pytest
from pydantic import ValidationError
from apps.api.routers.model_gateway_router import FounderCommandRequest


def test_founder_command_accepts_normal_prompt():
    assert FounderCommandRequest(command="Summarize overdue invoices").command == "Summarize overdue invoices"


@pytest.mark.parametrize("value", ["", "x" * 8001])
def test_founder_command_rejects_empty_or_oversized_input(value):
    with pytest.raises(ValidationError):
        FounderCommandRequest(command=value)


def test_founder_command_accepts_maximum_length():
    assert len(FounderCommandRequest(command="x" * 8000).command) == 8000
