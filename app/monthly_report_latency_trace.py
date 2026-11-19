"""Opt-in, source-neutral monotonic spans for *synthetic* Monthly QA.

Nothing persists, logs, changes scheduling, or records filenames, identities,
content, model prompts, request parameters or source bytes. Normal application
requests never install a collector; instrumented paths become no-ops.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic_ns, process_time_ns

# Explicit allowlist: a new stage requires a code change and a fixture test.
STAGES = frozenset({
    "upload_received", "hash_cache_lookup", "parse", "optional_visual_read",
    "job_queue", "native_assembly", "conversion", "raster",
    "first_decoded_browser_image",
})
_ACTIVE: ContextVar["TimingTrace | None"] = ContextVar("monthly_synthetic_timing", default=None)


class TimingTrace:
    """Single-request local receipt; all coordinates are relative milliseconds."""

    def __init__(self):
        self._origin = monotonic_ns()
        self._events = []

    def mark(self, stage: str):
        if stage not in STAGES:
            raise ValueError("Unsupported timing stage.")
        now = monotonic_ns()
        self._events.append((now, now, stage, 0, True))

    @contextmanager
    def span(self, stage: str):
        if stage not in STAGES:
            raise ValueError("Unsupported timing stage.")
        started, cpu_started = monotonic_ns(), process_time_ns()
        try:
            yield
        finally:
            finished = monotonic_ns()
            self._events.append((started, finished, stage,
                                 max(0, process_time_ns() - cpu_started), False))

    def receipt(self):
        events = []
        for started, finished, stage, cpu, point in sorted(
                self._events, key=lambda item: (item[0], item[1])):
            assert self._origin <= started <= finished
            events.append({
                "stage": stage,
                "start_ms": round((started - self._origin) / 1_000_000, 3),
                "end_ms": round((finished - self._origin) / 1_000_000, 3),
                "wall_ms": round((finished - started) / 1_000_000, 3),
                "cpu_ms": round(cpu / 1_000_000, 3),
                "point": point,
            })
        return {"clock": "monotonic_ns", "spans": events}


@contextmanager
def synthetic_timing(trace: TimingTrace):
    """Only a synthetic QA harness should activate a timing collector."""
    token = _ACTIVE.set(trace)
    try:
        yield trace
    finally:
        _ACTIVE.reset(token)


def mark(stage: str):
    collector = _ACTIVE.get()
    if collector is not None:
        collector.mark(stage)


@contextmanager
def span(stage: str):
    collector = _ACTIVE.get()
    if collector is None:
        yield
    else:
        with collector.span(stage):
            yield


def traced(stage: str):
    """Wrap a single call without changing parameters or return values."""
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with span(stage):
                return fn(*args, **kwargs)
        return wrapped
    return decorator
