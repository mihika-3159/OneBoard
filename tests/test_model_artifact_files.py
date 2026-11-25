import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.verify_model_artifacts import verify


class ArtifactVerificationTests(unittest.TestCase):
    def test_detects_same_length_corruption_and_changed_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = hashlib.sha256(b"good").hexdigest()
            blob = root / ("sha256-" + digest)
            blob.write_bytes(b"good")
            descriptor = {"size": 4, "digest": "sha256:" + digest}
            manifest = root / "manifest"
            manifest.write_text(json.dumps({"config": descriptor, "layers": [descriptor]}))
            pin = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
            verify(manifest, root, pin)
            blob.write_bytes(b"evil")
            with self.assertRaisesRegex(ValueError, "Blob digest mismatch"):
                verify(manifest, root, pin)
            manifest.write_bytes(manifest.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "Manifest digest mismatch"):
                verify(manifest, root, pin)
