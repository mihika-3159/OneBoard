"""Short-lived, bounded cache for validated tenant embeddings."""
from collections import OrderedDict
from hashlib import sha256
from threading import Lock
from time import monotonic


class EmbeddingCache:
    def __init__(self, capacity=128, ttl=60, clock=monotonic):
        self._capacity = capacity
        self._ttl = ttl
        self._clock = clock
        self._entries = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def key(tenant, provider, model, digest, prompt):
        if not tenant or not digest:
            return None
        return tenant, provider, model, digest, sha256(prompt.encode()).digest()

    def get(self, key):
        if key is None:
            return None
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            expires, vector = item
            if expires <= self._clock():
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return list(vector)

    def put(self, key, vector):
        if key is None:
            return
        with self._lock:
            self._entries[key] = self._clock() + self._ttl, tuple(vector)
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
