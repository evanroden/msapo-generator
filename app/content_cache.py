"""Session-owned digest cache for immutable uploads; never shared across users."""

from __future__ import annotations

import hashlib
from collections import OrderedDict


class ContentDigests:
    def __init__(self, max_bytes: int = 64 * 1024 * 1024, max_entries: int = 128):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self._entries: OrderedDict[int, tuple[bytes, bytes]] = OrderedDict()
        self._size = 0

    def digest(self, data: bytes) -> bytes:
        # Identity is safe only with a retained immutable object. Never trust a
        # caller-supplied digest, filename, or a recycled object id.
        entry = self._entries.get(id(data))
        if entry is not None and entry[0] is data:
            self._entries.move_to_end(id(data))
            return entry[1]
        result = hashlib.sha256(data).digest()
        if isinstance(data, bytes) and len(data) <= self.max_bytes:
            while self._entries and (
                self._size + len(data) > self.max_bytes
                or len(self._entries) >= self.max_entries
            ):
                _, (old, _) = self._entries.popitem(last=False)
                self._size -= len(old)
            self._entries[id(data)] = (data, result)
            self._size += len(data)
        return result

    def retain(self, payloads) -> None:
        active = {id(data) for data in payloads}
        for key in list(self._entries):
            if key not in active:
                data, _ = self._entries.pop(key)
                self._size -= len(data)
