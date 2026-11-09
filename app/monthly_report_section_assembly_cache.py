"""Short-lived, owner-isolated native section assembly reuse for preview retries.

Only the disposable unfinished-section DOCX is cached. Final downloads and the
client's saved reports never read from this cache.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic

MAX_ENTRY_BYTES = 24 * 1024 * 1024
TTL_SECONDS = 120
_SCOPE = ContextVar("monthly_section_assembly_owner", default=None)
_LOCK = Lock()
_ENTRY = None


@contextmanager
def owner_scope(owner, asset_versions=()):
    """Bind reuse to one preview-store owner and its current unsaved assets."""
    token = _SCOPE.set((owner, tuple(asset_versions)) if owner else None)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def active():
    return _SCOPE.get() is not None


def _cache_key(revision):
    scope = _SCOPE.get()
    return (scope, revision) if scope is not None else None


def read(revision):
    """Return immutable bytes only for the same owner, revision and assets."""
    global _ENTRY
    key = _cache_key(revision)
    if key is None:
        return None
    with _LOCK:
        if _ENTRY is not None and _ENTRY[1] <= monotonic():
            _ENTRY = None
        if _ENTRY is not None and _ENTRY[0] == key:
            return _ENTRY[2]
    return None


def remember(revision, raw):
    """Keep at most one bounded assembly when the render lease has headroom."""
    global _ENTRY
    key = _cache_key(revision)
    if key is None or type(raw) is not bytes or not 0 < len(raw) <= MAX_ENTRY_BYTES:
        return
    from app import monthly_report_render_jobs as jobs
    headroom = jobs.memory_headroom()
    if headroom is not None and headroom < jobs.PREVIEW_HEADROOM_BYTES + len(raw):
        return
    with _LOCK:
        _ENTRY = (key, monotonic() + TTL_SECONDS, raw)


def clear():
    """Discard disposable bytes (also used by the synthetic benchmark)."""
    global _ENTRY
    with _LOCK:
        _ENTRY = None
