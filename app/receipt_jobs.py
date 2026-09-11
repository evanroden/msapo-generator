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
        future = _POOL.submit(read, content)
    except BaseException:
        _SLOTS.release()
        raise
    future.add_done_callback(lambda _: _SLOTS.release())
    return future
