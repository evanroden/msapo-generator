"""Bounded same-session handoff, never a substitute for resource admission.

Streamlit can start a new runner while the old one finishes pure source work.
Only those source-review sections share a lock. Other sessions never wait here;
all callers must still acquire the unchanged global work slot afterward.
"""
from contextlib import contextmanager
from threading import Lock
from time import monotonic
from weakref import WeakValueDictionary

from app.monthly_report_render_jobs import RenderBusy

_LOCKS = WeakValueDictionary()
_REGISTRY_LOCK = Lock()
HANDOFF_SECONDS = 20


@contextmanager
def source_review_handoff(session_id, checkpoint, *, wait_seconds=HANDOFF_SECONDS):
    if not session_id:
        yield
        return
    # Strong local references retain the lock only while an owner/waiter uses
    # it. Registry creation is atomic; closed sessions leave no permanent map.
    with _REGISTRY_LOCK:
        lock = _LOCKS.get(session_id)
        if lock is None:
            lock = Lock()
            _LOCKS[session_id] = lock
    deadline = monotonic() + min(HANDOFF_SECONDS, max(0, wait_seconds))
    while not lock.acquire(blocking=False):
        checkpoint()  # Current script thread; obsolete runners stop at yield.
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise RenderBusy('The previous source review is finishing. Retry shortly.')
        if lock.acquire(timeout=min(.25, remaining)):
            break
    try:
        checkpoint()  # Never start proof work for an already superseded run.
        yield
    finally:
        lock.release()
