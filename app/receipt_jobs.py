"""Bounded network-only receipt jobs. No worker may touch Streamlit or PDFs."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore
from collections.abc import Callable
from typing import Any

MAX_ACTIVE_RECEIPTS = 2
_SLOTS = BoundedSemaphore(MAX_ACTIVE_RECEIPTS)
_POOL = ThreadPoolExecutor(
    max_workers=MAX_ACTIVE_RECEIPTS, thread_name_prefix="receipt-api"
)


def start_receipt(
    prepare: Callable[[], Any], read: Callable[[Any], Any]
) -> Future | None:
    """Reserve capacity BEFORE decoding; preparation runs on the calling thread.

    There is no unbounded executor queue. Capacity is released even when a
    report is cleared, a queued future is cancelled, or a request fails.
    """
    if not _SLOTS.acquire(blocking=False):
        return None
    try:
        content = prepare()
        # Retain the selected server-side report QA namespace through any
        # optional asynchronous reader work. Never allow a worker thread to
        # revert to production disk merely because contextvars did not flow.
        from app.monthly_report_testing import scope
        if scope() is not None:
            from contextvars import copy_context
            future = _POOL.submit(copy_context().run, read, content)
        else:
            future = _POOL.submit(read, content)
    except BaseException:
        _SLOTS.release()
        raise
    future.add_done_callback(lambda _: _SLOTS.release())
    return future
