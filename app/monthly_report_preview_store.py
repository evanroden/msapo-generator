"""Private, disposable preview files with process-wide disk and raster bounds.

Session state retains opaque tickets, not every PDF plus its base64 page images.
This cache never reads, evicts or migrates the durable report library.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import ExitStack
from dataclasses import dataclass
import math
from pathlib import Path
import tempfile
from threading import RLock
from time import monotonic
from uuid import uuid4

import pymupdf as fitz

from app.monthly_report_preview_metrics import measured


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
    initial_page: int = 0


@dataclass(frozen=True)
class _Stored:
    owner: str
    path: Path
    size: int
    ticket: PreviewTicket
    used: float
    retired: bool = False


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
        self._prepared = OrderedDict()
        self._disk_bytes = 0
        self._raster_bytes = 0
        self._directory = None
        self._lock = RLock()

    def _remove(self, key):
        entry = self._files.get(key)
        if entry is not None:
            # Revoke access before touching disk. A failed unlink must neither
            # revive this ticket nor hide its bytes from the global budget.
            self._files[key] = _Stored(entry.owner, entry.path, entry.size,
                                       entry.ticket, entry.used, retired=True)
        for raster in [value for value in self._rasters if value[0] == key]:
            self._raster_bytes -= len(self._rasters.pop(raster))
        pending = False
        for raster in [value for value in self._prepared if value[0] == key]:
            path, size = self._prepared[raster]
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # Keep failed deletions accounted, but never serve them after
                # their PDF ticket is revoked.
                pending = True
                continue
            del self._prepared[raster]
            self._disk_bytes -= size
        if pending:
            return
        if entry is not None:
            try:
                entry.path.unlink(missing_ok=True)
            except OSError:
                return
            self._files.pop(key)
            self._disk_bytes -= entry.size

    def _expire(self):
        now = monotonic()
        for key, entry in list(self._files.items()):
            if entry.retired or now - entry.used > self.max_age:
                self._remove(key)

    @measured("preview_store_put")
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
        first = getattr(preview, 'initial_page', 0)
        first = first if isinstance(first, int) and 0 <= first < len(sizes) else 0
        ticket = PreviewTicket(uuid4().hex, len(sizes), sizes, first)
        with self._lock:
            self._expire()
            # Try each owned file at most once; a failed deletion cannot spin
            # eviction or permit a new write beyond the accounted disk limit.
            for key in tuple(self._files):
                if (self._disk_bytes + len(raw) <= self.disk_limit
                        and len(self._files) < self.max_entries):
                    break
                self._remove(key)
            if (self._disk_bytes + len(raw) > self.disk_limit
                    or len(self._files) >= self.max_entries):
                raise OSError('The preview cache is waiting for temporary files to be removed. Retry this preview.')
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
        if entry is None or entry.retired or entry.owner != owner or entry.ticket != ticket:
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

    def _page_prepared(self, key, index, dpi):
        cache_key = (key, index, dpi)
        if cache_key in self._rasters:
            return True
        prepared = self._prepared.get(cache_key)
        if prepared is None:
            return False
        path, size = prepared
        try:
            return path.is_file() and path.stat().st_size == size
        except OSError:
            return False

    def prepared_pages(self, owner, ticket, *, dpi=120):
        """Return verified warm indexes, never infer readiness from a PDF alone."""
        if dpi not in (96, 120, 150):
            raise ValueError('Choose a supported preview resolution.')
        with self._lock:
            if self._get(owner, ticket) is None:
                return None
            return tuple(index for index in range(ticket.pages)
                         if self._page_prepared(ticket.key, index, dpi))

    def prepare_next_page(self, owner, ticket, *, dpi=120, is_current=lambda: True):
        """Warm one missing page without evicting another visitor's raster.

        Completed pages go to the existing private temporary-file budget,
        not an ever-growing in-memory image cache. Visible page decoding still
        uses the shared RAM budget. A bounded miss never claims readiness.
        Callers run this through their existing background admission guard.
        """
        if dpi not in (96, 120, 150):
            raise ValueError('Choose a supported preview resolution.')
        with self._lock:
            entry = self._get(owner, ticket)
            if entry is None or not is_current():
                return 'obsolete'
            missing = next((index for index in range(ticket.pages)
                            if not self._page_prepared(ticket.key, index, dpi)), None)
            if missing is None:
                return 'ready'
            # Reserve the strict maximum encoded page size before decoding.
            # Do not decode a page just to discover there is nowhere to keep it.
            if self._disk_bytes + MAX_PAGE_BYTES > self.disk_limit:
                return 'limited'
            with fitz.open(entry.path) as document:
                page = document[missing]
                scale = min(dpi / 72, math.sqrt(MAX_PAGE_PIXELS / (page.rect.width * page.rect.height)))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
                raw = pixmap.tobytes('jpeg', jpg_quality=88)
                del pixmap
            if len(raw) > MAX_PAGE_BYTES:
                raise ValueError('This preview page is too large to display safely.')
            if not is_current():
                return 'obsolete'
            path = entry.path.with_name(f'{ticket.key}-{missing}-{dpi}.jpg')
            prior = self._prepared.get((ticket.key, missing, dpi))
            if prior is not None:
                # Keep the reservation until damaged-file cleanup succeeds.
                prior[0].unlink(missing_ok=True)
                del self._prepared[(ticket.key, missing, dpi)]
                self._disk_bytes -= prior[1]
            try:
                with path.open('xb') as stream:
                    path.chmod(0o600)
                    stream.write(raw)
            except OSError:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    # Even a partial write whose cleanup fails stays inside
                    # the disk budget. Revoke the entire ticket until cleanup
                    # succeeds; incomplete bytes are never a prepared page.
                    try:
                        retained = path.stat().st_size
                    except OSError:
                        retained = MAX_PAGE_BYTES
                    self._prepared[(ticket.key, missing, dpi)] = (path, retained)
                    self._disk_bytes += retained
                    self._remove(ticket.key)
                raise
            self._prepared[(ticket.key, missing, dpi)] = (path, len(raw))
            self._disk_bytes += len(raw)
            return ('ready' if all(self._page_prepared(ticket.key, index, dpi)
                                   for index in range(ticket.pages)) else 'preparing')

    @measured("preview_store_pages_decode")
    def pages(self, owner, ticket, indexes, *, dpi=120):
        """Decode only the one/two visible pages; never build a whole-page HTML."""
        if dpi not in (96, 120, 150):
            raise ValueError('Choose a supported preview resolution.')
        # Validate the request's shape before consulting the private ticket.
        # A stale/foreign/malformed ticket is an unavailable preview, not
        # trusted page metadata: authenticate it through _get first.
        if (not isinstance(indexes, (list, tuple)) or len(indexes) > 2
                or any(type(index) is not int or index < 0 for index in indexes)):
            raise ValueError('Choose at most two existing preview pages.')
        indexes = tuple(dict.fromkeys(indexes))
        with self._lock:
            entry = self._get(owner, ticket)
            if entry is None:
                return None
            if any(index >= entry.ticket.pages for index in indexes):
                raise ValueError('Choose at most two existing preview pages.')
            result = []
            # Open only for a raster miss. Ownership, expiry and the backing
            # file were checked above, even when every requested page is warm.
            with ExitStack() as resources:
                document = None
                for index in indexes:
                    cache_key = (ticket.key, index, dpi)
                    raw = self._rasters.pop(cache_key, None)
                    if raw is None and cache_key in self._prepared:
                        path, size = self._prepared[cache_key]
                        raw = path.read_bytes()
                        if len(raw) != size or len(raw) > MAX_PAGE_BYTES:
                            raise OSError('The prepared preview page is unavailable.')
                        # Read one bounded JPEG from disk, never decode the PDF.
                        # It can enter RAM only through the normal bounded LRU.
                        while self._rasters and self._raster_bytes + len(raw) > self.raster_limit:
                            _, old = self._rasters.popitem(last=False)
                            self._raster_bytes -= len(old)
                        if len(raw) <= self.raster_limit:
                            self._rasters[cache_key] = raw
                            self._raster_bytes += len(raw)
                        result.append((index, raw))
                        continue
                    if raw is None:
                        if document is None:
                            document = resources.enter_context(fitz.open(entry.path))
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

    def discard_owner_prefix(self, prefix):
        """Expire one complete QA namespace, never a neighboring owner/site."""
        # Only reset_scope uses this API. Require a complete QA owner boundary
        # (qa:<scope>:), not a potentially shared string prefix.
        if (not isinstance(prefix, str) or not prefix.startswith('qa:')
                or not prefix.endswith(':') or prefix.count(':') != 2
                or not prefix[3:-1]):
            raise ValueError('A complete isolated preview owner scope is required.')
        with self._lock:
            for key, item in tuple(self._files.items()):
                if item.owner.startswith(prefix):
                    self._remove(key)

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
                # Directory cleanup may succeed after an individual unlink
                # failed transiently. Only then can its remaining bytes clear.
                self._files.clear()
                self._rasters.clear()
                self._prepared.clear()
                self._disk_bytes = self._raster_bytes = 0


# Live and QA previews must never share a PDF/raster store or entry budget.
_LIVE_STORE = PreviewStore()
_QA_STORE = PreviewStore()


class _ScopedPreviewStore:
    @staticmethod
    def _scoped_owner(owner):
        from app.monthly_report_testing import scope, generation
        selected = scope()
        if selected is None:
            return owner
        # A PDF worker may finish after another tab has reset QA storage.
        # Recheck the namespace generation before every cache operation; a
        # pre-reset worker cannot repopulate an erased test preview cache.
        from app.memory import _data_dir
        _data_dir()
        lease = generation()
        if not lease:
            raise OSError("Isolated preview generation is unavailable; no stale page was cached.")
        return "qa:" + selected + ":" + lease + ":" + owner

    def _active(self):
        from app.monthly_report_testing import scope
        return _QA_STORE if scope() is not None else _LIVE_STORE

    def put(self, owner, preview):
        return self._active().put(self._scoped_owner(owner), preview)

    def available(self, owner, ticket):
        return self._active().available(self._scoped_owner(owner), ticket)

    def discard(self, owner, ticket):
        return self._active().discard(self._scoped_owner(owner), ticket)

    def pages(self, owner, ticket, indexes, *, dpi=120):
        return self._active().pages(self._scoped_owner(owner), ticket, indexes, dpi=dpi)

    def prepared_pages(self, owner, ticket, *, dpi=120):
        return self._active().prepared_pages(self._scoped_owner(owner), ticket, dpi=dpi)

    def prepare_next_page(self, owner, ticket, *, dpi=120, is_current=lambda: True):
        return self._active().prepare_next_page(self._scoped_owner(owner), ticket,
                                               dpi=dpi, is_current=is_current)

    def reset_scope(self):
        from app.monthly_report_testing import scope
        selected = scope()
        if selected is None:
            raise ValueError("QA preview reset requires a verified isolated context.")
        _QA_STORE.discard_owner_prefix("qa:" + selected + ":")

    def stats(self):
        return self._active().stats()

    def close(self):
        self._active().close()


STORE = _ScopedPreviewStore()
