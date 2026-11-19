"""Ephemeral final-PDF conversion reuse for the same browser and report revision.

No saved report, preview, original source or Word package is persisted here.
Lookups are valid only after final preflight, source-view verification, media
sanitization and construction of the exact disposable LibreOffice input.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic

MAX_ENTRY_BYTES = 24 * 1024 * 1024
TTL_SECONDS = 300
_OWNER = ContextVar("monthly_final_conversion_owner", default=None)
_REVISION = ContextVar("monthly_final_conversion_revision", default=None)
_LOCK = Lock()
_ENTRY = None


@contextmanager
def owner_scope(owner, report, asset_versions=()):
    """A browser token is not authentication; it only prevents cache sharing."""
    valid = (isinstance(owner, str) and bool(owner)
             and isinstance(report, tuple) and len(report) == 3
             and all(isinstance(item, str) and item for item in report))
    value = (owner, report, tuple(asset_versions)) if valid else None
    token = _OWNER.set(value)
    try:
        yield
    finally:
        _OWNER.reset(token)


@contextmanager
def verified_revision(revision):
    """An internal final-generation gate supplies the current manifest identity."""
    token = _REVISION.set(tuple(revision))
    try:
        yield
    finally:
        _REVISION.reset(token)


def _key(conversion):
    owner = _OWNER.get()
    revision = _REVISION.get()
    return (owner, revision, conversion) if owner is not None and revision is not None else None


def read(conversion):
    """Read only an unexpired exact owner/revision/renderer-input result."""
    global _ENTRY
    key = _key(conversion)
    if key is None:
        return None
    with _LOCK:
        if _ENTRY is not None and _ENTRY[1] <= monotonic():
            _ENTRY = None
        if _ENTRY is not None and _ENTRY[0] == key:
            return _ENTRY[2]
    return None


def remember(conversion, pdf):
    """Keep at most one successful bounded PDF, never a failure or partial file."""
    global _ENTRY
    key = _key(conversion)
    if (key is None or type(pdf) is not bytes or not pdf.startswith(b"%PDF-")
            or not 5 <= len(pdf) <= MAX_ENTRY_BYTES):
        return
    from app import monthly_report_render_jobs as jobs
    headroom = jobs.memory_headroom()
    if headroom is not None and headroom < jobs.PREVIEW_HEADROOM_BYTES + len(pdf):
        return
    with _LOCK:
        _ENTRY = (key, monotonic() + TTL_SECONDS, pdf)


def clear():
    """Release the single disposable entry (also used by synthetic tests)."""
    global _ENTRY
    with _LOCK:
        _ENTRY = None
