"""Explicitly opted-in deterministic text-only results; never cache decisions or actions."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json
from threading import Lock
from time import monotonic


class GenerationCache:
    def __init__(self, capacity=64, ttl=30, clock=monotonic):
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self.entries = OrderedDict()
        self.lock = Lock()

    @staticmethod
    def key(tenant, origin, digest, payload):
        if not tenant or not digest or payload.get("format") or payload.get("stream"):
            return None
        if payload.get("options", {}).get("temperature") != 0:
            return None
        return tenant, origin, digest, sha256(json.dumps(payload, sort_keys=True).encode()).digest()

    def get(self, key):
        if key is None:
            return None
        with self.lock:
            row = self.entries.pop(key, None)
            if row is None or row[0] <= self.clock():
                return None
            self.entries[key] = row
            return {**deepcopy(row[1]), "cache_hit": True, "duration_ms": 0}

    def put(self, key, value):
        if (key is None or value.get("simulated") or value.get("output_limit_reached")
                or not isinstance(value.get("content"), str) or len(value["content"].encode()) > 16384):
            return
        with self.lock:
            self.entries[key] = self.clock() + self.ttl, deepcopy(value)
            self.entries.move_to_end(key)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
