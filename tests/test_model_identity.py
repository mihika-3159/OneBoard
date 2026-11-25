import unittest

from apps.api.services.model_identity import matches_pin, valid_digest


class ModelIdentityTests(unittest.TestCase):
    def test_matches_the_exact_tag_and_manifest_digest(self):
        digest = "d" * 64
        models = [{"name": "test:1", "digest": digest}]
        self.assertTrue(matches_pin(models, "test:1", "sha256:" + digest))
        self.assertFalse(matches_pin(models, "test:2", digest))
        self.assertFalse(matches_pin(models, "test:1", "f" * 64))

    def test_rejects_duplicate_or_malformed_model_manifest_entries(self):
        entry = {"name": "test:1", "digest": "d" * 64}
        self.assertFalse(matches_pin([entry, entry], "test:1", entry["digest"]))
        self.assertFalse(matches_pin(None, "test:1", entry["digest"]))
        self.assertFalse(valid_digest("sha256:short"))
