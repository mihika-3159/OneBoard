"""Verify an Ollama manifest and every referenced blob before serving a model."""

import argparse
import hashlib
import json
from pathlib import Path
import re


def digest_hex(value):
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("Expected a full SHA-256 digest")
    return value[7:]


def verify(manifest, blobs, expected):
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest_hex(expected):
        raise ValueError("Manifest digest mismatch")
    parsed = json.loads(raw)
    layers = parsed["layers"]
    if not isinstance(layers, list) or not layers:
        raise ValueError("Manifest has no layers")
    for descriptor in [parsed["config"], *layers]:
        digest = digest_hex(descriptor["digest"])
        size = descriptor["size"]
        if type(size) is not int or size < 0:
            raise ValueError("Invalid blob size")
        blob = blobs / ("sha256-" + digest)
        if blob.stat().st_size != size:
            raise ValueError("Blob size mismatch")
        with blob.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest:
            raise ValueError("Blob digest mismatch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("blobs", type=Path)
    parser.add_argument("expected_digest")
    args = parser.parse_args()
    verify(args.manifest, args.blobs, args.expected_digest)
