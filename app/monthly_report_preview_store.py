"""Private, disposable preview files with process-wide disk and raster bounds.

Session state retains opaque tickets, not every PDF plus its base64 page images.
This cache never reads, evicts or migrates the durable report library.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from pathlib import Path
import tempfile
from threading import RLock
from time import monotonic
from uuid import uuid4

import fitz


MAX_DISK_BYTES = 64 * 1024 * 1024
MAX_RASTER_BYTES = 8 * 1024 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_PAGE_PIXELS = 2_500_000
MAX_ENTRIES = 64
MAX_AGE_SECONDS = 30 * 60


@dataclass(frozen=True)
class PreviewTicket:
    key: str
    pages: int
    sizes: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class _Stored:
    owner: str
    path: Path
    size: int
    ticket: PreviewTicket
    used: float


class PreviewStore:
    """Bound all visitors together; byte limits are strict even for one entry."""
    def __init__(self, *, disk_bytes=MAX_DISK_BYTES, raster_bytes=MAX_RASTER_BYTES,
                 max_entries=MAX_ENTRIES, max_age=MAX_AGE_SECONDS):
        if min(disk_bytes, raster_bytes, max_entries, max_age) <= 0:
            raise ValueError('Preview cache limits must be positive.')
        self.disk_limit = disk_bytes
        self.raster_limit = raster_bytes
        self.max_entries = max_entries
        self.max_age = max_age
        self._files = OrderedDict()
        self._rasters = OrderedDict()
        self._disk_bytes = 0
        self._raster_bytes = 0
        self._directory = None
        self._lock = RLock()

    def _remove(self, key):
        entry = self._files.pop(key, None)
        if entry is not None:
            self._disk_bytes -= entry.size
            entry.path.unlink(missing_ok=True)
        for raster in [value for value in self._rasters if value[0] == key]:
            self._raster_bytes -= len(self._rasters.pop(raster))

    def _expire(self):
        now = monotonic()
        for key, entry in list(self._files.items()):
            if now - entry.used > self.max_age:
                self._remove(key)

    def put(self, owner, preview):
        if not owner or not isinstance(owner, str):
            raise ValueError('A private preview owner is required.')
        raw = preview.pdf
        if not raw.startswith(b'%PDF-') or not 0 < len(raw) <= min(self.disk_limit, 25 * 1024 * 1024):
            raise ValueError('The preview exceeds its temporary-file budget.')
        with fitz.open(stream=raw, filetype='pdf') as document:
            if document.is_encrypted or not 0 < len(document) <= 150:
                raise ValueError('The preview has no safely readable pages.')
            sizes = tuple((page.rect.width, page.rect.height) for page in document)
            if any(not all(math.isfinite(n) and n > 0 for n in size) for size in sizes):
                raise ValueError('The preview has invalid page dimensions.')
        ticket = PreviewTicket(uuid4().hex, len(sizes), sizes)
        with self._lock:
            self._expire()
            while self._files and (self._disk_bytes + len(raw) > self.disk_limit
                                   or len(self._files) >= self.max_entries):
                self._remove(next(iter(self._files)))
            if self._directory is None:
                self._directory = tempfile.TemporaryDirectory(prefix='monthly-preview-cache-')
            path = Path(self._directory.name) / (ticket.key + '.pdf')
            try:
                with path.open('xb') as stream:
                    path.chmod(0o600)
                    stream.write(raw)
            except OSError:
                path.unlink(missing_ok=True)
                raise
            self._files[ticket.key] = _Stored(owner, path, len(raw), ticket, monotonic())
            self._disk_bytes += len(raw)
        return ticket

    def _get(self, owner, ticket):
        self._expire()
        entry = self._files.get(ticket.key) if isinstance(ticket, PreviewTicket) else None
        if entry is None or entry.owner != owner or entry.ticket != ticket:
            return None
        if not entry.path.is_file():
            self._remove(ticket.key)
            return None
        self._files.pop(ticket.key)
        entry = _Stored(entry.owner, entry.path, entry.size, entry.ticket, monotonic())
        self._files[ticket.key] = entry
        return entry

    def available(self, owner, ticket):
        with self._lock:
            return self._get(owner, ticket) is not None

    def discard(self, owner, ticket):
        with self._lock:
            if self._get(owner, ticket) is not None:
                self._remove(ticket.key)

    def pages(self, owner, ticket, indexes, *, dpi=120):
        """Decode only the one/two visible pages; never build a whole-page HTML."""
        if dpi not in (96, 120, 150):
            raise ValueError('Choose a supported preview resolution.')
        if (not isinstance(indexes, (list, tuple)) or len(indexes) > 2
                or any(type(index) is not int or not 0 <= index < ticket.pages for index in indexes)):
            raise ValueError('Choose at most two existing preview pages.')
        indexes = tuple(dict.fromkeys(indexes))
        with self._lock:
            entry = self._get(owner, ticket)
            if entry is None:
                return None
            result = []
            with fitz.open(entry.path) as document:
                for index in indexes:
                    cache_key = (ticket.key, index, dpi)
                    raw = self._rasters.pop(cache_key, None)
                    if raw is None:
                        page = document[index]
                        scale = min(dpi / 72, math.sqrt(MAX_PAGE_PIXELS / (page.rect.width * page.rect.height)))
                        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
                        raw = pixmap.tobytes('jpeg', jpg_quality=88)
                        del pixmap
                        if len(raw) > MAX_PAGE_BYTES:
                            raise ValueError('This preview page is too large to display safely.')
                        while self._rasters and self._raster_bytes + len(raw) > self.raster_limit:
                            _, old = self._rasters.popitem(last=False)
                            self._raster_bytes -= len(old)
                        if len(raw) <= self.raster_limit:
                            self._rasters[cache_key] = raw
                            self._raster_bytes += len(raw)
                    else:
                        self._rasters[cache_key] = raw
                    result.append((index, raw))
            return tuple(result)

    def stats(self):
        with self._lock:
            self._expire()
            return {'pdf_bytes': self._disk_bytes, 'raster_bytes': self._raster_bytes,
                    'pdf_entries': len(self._files), 'raster_entries': len(self._rasters)}

    def close(self):
        with self._lock:
            for key in list(self._files):
                self._remove(key)
            if self._directory is not None:
                self._directory.cleanup()
                self._directory = None


STORE = PreviewStore()
