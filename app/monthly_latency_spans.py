"""Opt-in, request-local numeric-only timing receipts; no app telemetry."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

_ACTIVE = ContextVar("monthly_latency_capture", default=None)
_NAMES = frozenset({
    "work_queue", "office_thread_queue", "office_process_queue",
    "office_execution", "native_assembly", "source_ingest",
    "source_thumbnail", "source_mapping", "source_extraction", "first_raster",
    "template_import", "ocr_ai_prep", "docx_export", "pdf_export",
    "save_reload", "browser_first_paint", "browser_rerun",
})
_OUTCOMES = frozenset({"ok", "busy", "error"})


@contextmanager
def capture_spans():
    """Isolated context; no source/report/owner identifiers may be emitted."""
    events = []
    token = _ACTIVE.set(events)
    try:
        yield events
    finally:
        _ACTIVE.reset(token)


def record_span(name: str, duration_seconds: float, *, outcome: str = "ok") -> None:
    if name not in _NAMES or outcome not in _OUTCOMES:
        raise ValueError("Unknown latency phase or result")
    events = _ACTIVE.get()
    if events is not None:
        events.append({"phase": name, "elapsed_ms": round(max(0., duration_seconds) * 1000, 3),
                       "result": outcome})


@contextmanager
def measure_span(name: str):
    if name not in _NAMES:
        raise ValueError("Unknown latency phase")
    start = perf_counter()
    try:
        yield
    except BaseException:
        record_span(name, perf_counter() - start, outcome="error")
        raise
    else:
        record_span(name, perf_counter() - start)
