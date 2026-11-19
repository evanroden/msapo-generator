"""Short-lived, owner-isolated native section DOCX preview reuse.

Disposable unfinished assemblies only. Never used for finalized report exports.
A strict process-wide byte budget retains a few sections through navigation.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic

MAX_ENTRY_BYTES = 24 * 1024 * 1024
MAX_TOTAL_BYTES = 24 * 1024 * 1024
MAX_ENTRIES = 4
TTL_SECONDS = 120
_SCOPE = ContextVar("monthly_section_assembly_owner", default=None)
_LOCK = Lock()
_ENTRIES = OrderedDict()
_BYTES = 0


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


def _expire(now):
    """Called while holding _LOCK."""
    global _BYTES
    for key, (expires, raw) in tuple(_ENTRIES.items()):
        if expires <= now:
            del _ENTRIES[key]
            _BYTES -= len(raw)


def read(revision):
    """Return immutable bytes only for the same owner, revision and assets."""
    key = _cache_key(revision)
    if key is None:
        return None
    with _LOCK:
        _expire(monotonic())
        entry = _ENTRIES.pop(key, None)
        if entry is not None:
            _ENTRIES[key] = entry
            return entry[1]
    return None


def remember(revision, raw):
    """Retain a bounded number of sections when the render lease has headroom."""
    global _BYTES
    key = _cache_key(revision)
    if key is None or type(raw) is not bytes or not 0 < len(raw) <= MAX_ENTRY_BYTES:
        return
    from app import monthly_report_render_jobs as jobs
    headroom = jobs.memory_headroom()
    if headroom is not None and headroom < jobs.PREVIEW_HEADROOM_BYTES + len(raw):
        return
    with _LOCK:
        _expire(monotonic())
        previous = _ENTRIES.pop(key, None)
        if previous is not None:
            _BYTES -= len(previous[1])
        while _ENTRIES and (len(_ENTRIES) >= MAX_ENTRIES or _BYTES + len(raw) > MAX_TOTAL_BYTES):
            _, (_, evicted) = _ENTRIES.popitem(last=False)
            _BYTES -= len(evicted)
        _ENTRIES[key] = (monotonic() + TTL_SECONDS, raw)
        _BYTES += len(raw)


def clear():
    """Discard disposable bytes (also used by the synthetic benchmark)."""
    global _BYTES
    with _LOCK:
        _ENTRIES.clear()
        _BYTES = 0


def stats():
    with _LOCK:
        _expire(monotonic())
        return {"entries": len(_ENTRIES), "bytes": _BYTES}
