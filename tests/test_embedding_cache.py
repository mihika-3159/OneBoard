import unittest
from apps.api.services.embedding_cache import EmbeddingCache


class CacheTests(unittest.TestCase):
    def test_scope_copy_eviction_and_expiry(self):
        clock = [0]
        cache = EmbeddingCache(1, 2, lambda: clock[0])
        key = cache.key("A", "provider", "model", "digest", "query")
        other = cache.key("B", "provider", "model", "digest", "query")
        cache.put(key, [1.0])
        cache.get(key).clear()
        self.assertEqual(cache.get(key), [1.0])
        self.assertIsNone(cache.get(other))
        cache.put(other, [2.0])
        self.assertIsNone(cache.get(key))
        clock[0] = 2
        self.assertIsNone(cache.get(other))
        self.assertIsNone(cache.key("A", "provider", "model", None, "query"))
