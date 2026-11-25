"""Validate model identity against a deployment-controlled Ollama manifest."""

import re


def valid_digest(value):
    return isinstance(value, str) and re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", value) is not None


def _digest(value):
    return value.removeprefix("sha256:")


def matches_pin(models, model, expected_digest):
    if not isinstance(models, list) or not valid_digest(expected_digest):
        return False
    matches = [
        entry.get("digest") for entry in models
        if isinstance(entry, dict) and entry.get("name") == model
    ]
    return (
        len(matches) == 1
        and valid_digest(matches[0])
        and _digest(matches[0]) == _digest(expected_digest)
    )
