"""Session/operation-owned digest cache for immutable bytes, never shared between users.

The logical byte budget and entry limit remain backward-compatible. TTL stops
long-lived sessions retaining old payloads forever. resident_bytes reports the
actual Python object-footprint estimate (including container overhead) for QA;
it is not a cross-session global cache.
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
import sys
import time


class ContentDigests:
    def __init__(self, max_bytes: int = 64 * 1024 * 1024,
                 max_entries: int = 128, ttl_seconds: float = 120.0):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[int, tuple[bytes, bytes, float]] = OrderedDict()
        self._size = 0

    def _discard(self, key: int) -> None:
        data, _, _ = self._entries.pop(key)
        self._size -= len(data)

    def _expire(self, now: float) -> None:
        for key, (_, _, stamped) in tuple(self._entries.items()):
            if now - stamped >= self.ttl_seconds:
                self._discard(key)

    @property
    def resident_bytes(self) -> int:
        """Conservative per-instance Python object estimate for local QA."""
        return (sys.getsizeof(self._entries) +
                sum(sys.getsizeof(k) + sys.getsizeof(data) + sys.getsizeof(digest)
                    + sys.getsizeof(stamp) + sys.getsizeof((data, digest, stamp))
                    for k, (data, digest, stamp) in self._entries.items()))

    def digest(self, data: bytes) -> bytes:
        # Identity is safe only with the exact retained immutable object. Never
        # trust caller-supplied hash, file name, or recycled object ID.
        now = time.monotonic()
        self._expire(now)
        entry = self._entries.get(id(data))
        if entry is not None and entry[0] is data:
            self._entries.move_to_end(id(data))
            return entry[1]
        result = hashlib.sha256(data).digest()
        if isinstance(data, bytes) and len(data) <= self.max_bytes and self.max_entries > 0:
            while self._entries and (
                self._size + len(data) > self.max_bytes
                or len(self._entries) >= self.max_entries
            ):
                self._discard(next(iter(self._entries)))
            self._entries[id(data)] = (data, result, now)
            self._size += len(data)
        return result

    def retain(self, payloads) -> None:
        active = {id(data) for data in payloads}
        for key in list(self._entries):
            if key not in active:
                self._discard(key)
