"""Bounded, cross-process serialization of monthly report office conversions."""
import os
import threading
import time
from contextlib import contextmanager

from app import pdf_converter
from app.monthly_latency_spans import measure_span, record_span
from app.monthly_report_library import _root
from app.monthly_report_latency_trace import span

_SLOT = threading.Lock()
_CONVERSION_LOCAL = threading.local()


class RenderBusy(pdf_converter.PDFConversionError):
    pass


@contextmanager
def conversion_slot(*, wait_seconds=10):
    """Reentrant conversion gate, with an opt-in cgroup-bounded second lane."""
    if getattr(_CONVERSION_LOCAL, 'active', False):
        yield
        return
    from app.office_conversion_admission import OfficeLaneBusy, conversion_lane
    from app import office_process
    from contextlib import ExitStack
    try:
        with ExitStack() as stack:
            # Waiting for a conversion lane is queue time, not conversion time.
            with span("job_queue"):
                lane, parallel = stack.enter_context(conversion_lane(
                    wait_seconds=wait_seconds, serial_lock=_SLOT,
                    folder=_root() / 'render-jobs', memory_headroom=memory_headroom))
            office_process._OFFICE_MARKER_LOCAL.slot = lane
            office_process._OFFICE_MARKER_LOCAL.serial = not parallel
            try:
                from app.office_process import OfficeCleanupPending, require_idle
                try:
                    require_idle()
                except OfficeCleanupPending as exc:
                    raise RenderBusy(str(exc)) from exc
                _CONVERSION_LOCAL.active = True
                import gc
                gc.collect()
                if preview_memory_guard() is not None:
                    _reclaim_preview_heap()
                yield
            finally:
                _CONVERSION_LOCAL.active = False
                del office_process._OFFICE_MARKER_LOCAL.slot
                del office_process._OFFICE_MARKER_LOCAL.serial
    except OfficeLaneBusy as exc:
        raise RenderBusy(str(exc)) from exc


def _reclaim_preview_heap():
    """Release no-longer-live glibc arenas before a capped preview conversion.

    Only a memory reclamation hint; the real cgroup headroom guard remains
    authoritative and must still reject a conversion under pressure.
    """
    if os.name != "posix":
        return
    try:
        import ctypes
        trim = ctypes.CDLL(None).malloc_trim
    except (AttributeError, OSError):
        return
    trim.argtypes = [ctypes.c_size_t]
    trim.restype = ctypes.c_int
    trim(0)


def _reclaimed_headroom():
    """Collect garbage, return freed heap to the OS, then measure headroom again."""
    import gc
    gc.collect()
    _reclaim_preview_heap()
    return memory_headroom()


def convert_to_pdf(path, *, wait_seconds=10, lossless_images=False):
    with conversion_slot(wait_seconds=wait_seconds):
        # Do not count thread/process-lock admission as office execution.
        with span("conversion"), measure_span("office_execution"):
            if lossless_images is not False:
                return pdf_converter.convert_to_pdf(path, lossless_images=lossless_images)
            return pdf_converter.convert_to_pdf(path)


# Assembly can hold decoded pictures and an entire OOXML package. Serialize that
# phase separately from the backend lock: a metafile helper may itself convert a
# document, so holding the conversion lock around assembly would deadlock it.
from app.monthly_preview_memory_budget import preview_worker_budget, required_free_bytes


class _ParallelWorkSlots:
    """Capped, in-process slots; keep .locked() for diagnostic/test callers."""
    def __init__(self, capacity):
        self._slots = threading.BoundedSemaphore(capacity)
        self._state_lock = threading.Lock()
        self._held = 0

    def acquire(self, blocking=True, timeout=None):
        acquired = self._slots.acquire(blocking=blocking, timeout=timeout)
        if acquired:
            with self._state_lock:
                self._held += 1
        return acquired

    def release(self):
        with self._state_lock:
            self._slots.release()
            self._held -= 1

    def locked(self):
        with self._state_lock:
            return self._held > 0


# Default remains the identical single mutex. Explicit higher tiers require
# finite cgroup CPU/RAM quotas and use the measured eight-photo peak budget.
_WORK_CAPACITY = preview_worker_budget()
_WORK_SLOT = (threading.Lock() if _WORK_CAPACITY == 1
              else _ParallelWorkSlots(_WORK_CAPACITY))
_ADMISSION_LOCK = threading.Lock()
_ACTIVE_WORK = 0
_WORK_LOCAL = threading.local()
_PRIORITY_LOCK = threading.Lock()
_FOREGROUND_WAITING = 0
_FOREGROUND_ACTIVE = 0
_REVIEW_WAITING = 0
PREVIEW_HEADROOM_BYTES = 160 * 1024 * 1024


def _memory_status():
    """Distinguish absent/unlimited cgroups from a broken finite counter."""
    from pathlib import Path
    unavailable = False
    unlimited = False
    for folder, limit_name, used_name in (
        (Path('/sys/fs/cgroup'), 'memory.max', 'memory.current'),
        (Path('/sys/fs/cgroup/memory'), 'memory.limit_in_bytes', 'memory.usage_in_bytes'),
    ):
        try:
            raw_limit = (folder / limit_name).read_text().strip()
        except FileNotFoundError:
            continue
        except OSError:
            unavailable = True
            continue
        try:
            if raw_limit == 'max' and limit_name == 'memory.max':
                unlimited = True
                continue
            limit = int(raw_limit)
            if limit >= 1 << 60:
                unlimited = True
                continue
            used = int((folder / used_name).read_text().strip())
        except (OSError, ValueError):
            unavailable = True
            continue
        if 0 < limit < 1 << 60 and used >= 0:
            return 'finite', max(0, limit - used)
        unavailable = True
    return ('unavailable' if unavailable else 'unlimited' if unlimited else 'unsupported'), None


def memory_headroom():
    """Use the container's actual limit, not host RAM or a guessed service plan."""
    return _memory_status()[1]


class _PreviewMemoryGuard:
    """One thread's active work lease, never an unrelated converter's cancel."""
    def __init__(self, headroom):
        self.owner = threading.get_ident()
        self.finite = headroom is not None

    def __call__(self):
        if (threading.get_ident() != self.owner or not getattr(_WORK_LOCAL, 'active', False)
                or getattr(_WORK_LOCAL, 'preview_guard', None) is not self):
            raise RenderBusy('The preview work lease is no longer current. Your edits are still here.')
        headroom = memory_headroom()
        if headroom is None:
            state, headroom = _memory_status()
            if state == 'unavailable' or (state == 'unsupported' and self.finite):
                raise RenderBusy('Preview memory could not be checked. Your edits are still here.')
        if headroom is not None:
            self.finite = True
            required = PREVIEW_HEADROOM_BYTES
            if _WORK_CAPACITY > 1:
                with _ADMISSION_LOCK:
                    required = required_free_bytes(max(0, _ACTIVE_WORK - 1))
            if headroom < required:
                raise RenderBusy('Preview is queued while the service is busy. Your edits are still here. Retry shortly.')


def preview_memory_guard():
    """Inherited only by a nested operation inside this exact preview lease."""
    return getattr(_WORK_LOCAL, 'preview_guard', None) if getattr(_WORK_LOCAL, 'active', False) else None


def _wait_for_review_slot(wait_seconds):
    """Reserve a short Review turn; final exports keep first claim.

    Automatic section previews must yield while this deliberate request waits.
    Never stop an existing job, and never hold the priority lock while waiting.
    """
    global _REVIEW_WAITING
    deadline = time.monotonic() + max(0, min(float(wait_seconds), 10))
    with _PRIORITY_LOCK:
        _REVIEW_WAITING += 1
    try:
        while True:
            with _PRIORITY_LOCK:
                if not _FOREGROUND_WAITING and not _FOREGROUND_ACTIVE and _WORK_SLOT.acquire(blocking=False):
                    return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(.05, remaining))
    finally:
        with _PRIORITY_LOCK:
            _REVIEW_WAITING -= 1


@contextmanager
def work_slot(*, preview=False, review=False, wait_seconds=130):
    """Admit one heavy job: final export, deliberate Review, automatic preview."""
    if review and not preview:
        raise ValueError("Review priority requires the preview memory guard.")
    global _FOREGROUND_WAITING, _FOREGROUND_ACTIVE
    if getattr(_WORK_LOCAL, 'active', False):
        yield
        return
    queue_started = time.monotonic()
    with span("job_queue"):
        acquired = False
        if preview:
            headroom = memory_headroom()
            if headroom is not None and headroom < PREVIEW_HEADROOM_BYTES:
                # Freed Python/glibc heap stays charged to the cgroup until it
                # is trimmed, and the trim otherwise runs only inside an
                # admitted conversion. Without this, memory freed by earlier
                # sessions keeps every later preview refused. Reclaim once and
                # measure again; the cgroup measure stays authoritative.
                headroom = _reclaimed_headroom()
            if headroom is not None and headroom < PREVIEW_HEADROOM_BYTES:
                record_span("work_queue", time.monotonic() - queue_started, outcome="busy")
                raise RenderBusy('Preview is queued while the service is busy. Your edits are still here.')
            if review:
                acquired = _wait_for_review_slot(wait_seconds)
            else:
                with _PRIORITY_LOCK:
                    if _FOREGROUND_WAITING or _FOREGROUND_ACTIVE or _REVIEW_WAITING:
                        record_span("work_queue", time.monotonic() - queue_started, outcome="busy")
                        raise RenderBusy('Preview is queued while the service is busy. Your edits are still here.')
                    acquired = _WORK_SLOT.acquire(blocking=False)
        else:
            with _PRIORITY_LOCK:
                _FOREGROUND_WAITING += 1
            try:
                acquired = _WORK_SLOT.acquire(timeout=max(0, min(float(wait_seconds), 130)))
            finally:
                with _PRIORITY_LOCK:
                    _FOREGROUND_WAITING -= 1
                    if acquired:
                        # Transition waiting -> running atomically for Review
                        # and automatic-preview priority checks.
                        _FOREGROUND_ACTIVE += 1
        if not acquired:
            record_span("work_queue", time.monotonic() - queue_started, outcome="busy")
            raise RenderBusy('Another report is being prepared. Your saved work is unchanged; retry generation shortly.')
    # Admission is fail-closed only on explicitly opted-in high-resource hosts.
    # Check before allocating another DOCX/Pillow package, counting admissions
    # under one lock so two contenders cannot both spend the same headroom.
    # Previews use the measured A34 budget and fail closed even for the first
    # preview. Foreground work keeps the A19 rule: the first job always
    # retains the single-worker fallback, and later jobs need the A19 margin.
    global _ACTIVE_WORK
    reserved = False
    try:
        if _WORK_CAPACITY > 1:
            with _ADMISSION_LOCK:
                available = memory_headroom()
                if preview:
                    if available is None or available < required_free_bytes(_ACTIVE_WORK):
                        record_span("work_queue", time.monotonic() - queue_started, outcome="busy")
                        raise RenderBusy(
                            'Additional preview work is queued while memory is busy. '
                            'Your edits are still here. Retry shortly.')
                elif _ACTIVE_WORK:
                    required = (512 + 768 * (_ACTIVE_WORK + 1)) * 1024 * 1024
                    if available is None or available < required:
                        record_span("work_queue", time.monotonic() - queue_started, outcome="busy")
                        raise RenderBusy('Additional report work is queued while memory is busy. Your saved work is unchanged.')
                _ACTIVE_WORK += 1
                reserved = True
        _WORK_LOCAL.active = True
        _WORK_LOCAL.preview_guard = _PreviewMemoryGuard(headroom) if preview else None
        try:
            try:
                if preview:
                    _WORK_LOCAL.preview_guard()
            except RenderBusy:
                record_span("work_queue", time.monotonic() - queue_started, outcome="busy")
                raise
            record_span("work_queue", time.monotonic() - queue_started)
            yield
        finally:
            _WORK_LOCAL.preview_guard = None
            _WORK_LOCAL.active = False
    finally:
        if reserved:
            with _ADMISSION_LOCK:
                _ACTIVE_WORK -= 1
        if not preview:
            with _PRIORITY_LOCK:
                _FOREGROUND_ACTIVE -= 1
        _WORK_SLOT.release()
