"""Bounded, cross-process serialization of monthly report office conversions."""
import os
import threading
import time
from contextlib import contextmanager

from app import pdf_converter
from app.monthly_latency_spans import measure_span, record_span
from app.monthly_report_library import _root

_SLOT = threading.Lock()
_CONVERSION_LOCAL = threading.local()


class RenderBusy(pdf_converter.PDFConversionError):
    pass


@contextmanager
def conversion_slot(*, wait_seconds=10):
    """Preview callers fail promptly; foreground work has a bounded queue wait."""
    if getattr(_CONVERSION_LOCAL, 'active', False):
        yield
        return
    started = time.monotonic()
    deadline = started + max(0, min(float(wait_seconds), 130))
    if not _SLOT.acquire(timeout=max(0, deadline - time.monotonic())):
        record_span("office_thread_queue", time.monotonic() - started, outcome="busy")
        raise RenderBusy("Another report is rendering. Please try again shortly.")
    record_span("office_thread_queue", time.monotonic() - started)
    try:
        folder = _root() / "render-jobs"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / ".conversion-lock").open("a+b") as lock:
            if os.name == "nt":
                import msvcrt
                lock.write(b"0"); lock.flush()
            else:
                import fcntl
            process_started = time.monotonic()
            while True:
                try:
                    if os.name == "nt":
                        lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        record_span("office_process_queue", time.monotonic() - process_started, outcome="busy")
                        raise RenderBusy("Another report is rendering. Please try again shortly.") from None
                    time.sleep(min(.05, max(0, deadline - time.monotonic())))
            record_span("office_process_queue", time.monotonic() - process_started)
            try:
                from app.office_process import OfficeCleanupPending, require_idle
                try:
                    require_idle()
                except OfficeCleanupPending as exc:
                    raise RenderBusy(str(exc)) from exc
                _CONVERSION_LOCAL.active = True
                # python-docx package/relationship cycles can otherwise retain
                # decoded media while the office process starts allocating.
                import gc
                gc.collect()
                # The prior native DOCX / Pillow allocations are no longer
                # reachable at this point, but glibc may retain their freed
                # arenas. Return those pages before launching LibreOffice in
                # a memory-capped *preview* lease. This never changes the
                # source assets, assembled DOCX, render guard or host limit.
                if preview_memory_guard() is not None:
                    _reclaim_preview_heap()
                yield
            finally:
                _CONVERSION_LOCAL.active = False
                if os.name == "nt":
                    lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        _SLOT.release()


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


def convert_to_pdf(path, *, wait_seconds=10, lossless_images=False):
    with conversion_slot(wait_seconds=wait_seconds):
        # The nested converter shares this lease. Subprocess + validation
        # + publication are measured separately from lock admission.
        with measure_span("office_execution"):
            if lossless_images is not False:
                return pdf_converter.convert_to_pdf(path, lossless_images=lossless_images)
            return pdf_converter.convert_to_pdf(path)


# Assembly can hold decoded pictures and an entire OOXML package. Serialize that
# phase separately from the backend lock: a metafile helper may itself convert a
# document, so holding the conversion lock around assembly would deadlock it.
from app.monthly_report_job_capacity import heavy_job_capacity


class _ParallelWorkSlots:
    """A bounded semaphore retaining the old lock's diagnostic .locked() API."""
    def __init__(self, capacity):
        self._slots = threading.BoundedSemaphore(capacity)
        self._guard = threading.Lock()
        self._held = 0

    def acquire(self, blocking=True, timeout=None):
        result = self._slots.acquire(blocking=blocking, timeout=timeout)
        if result:
            with self._guard:
                self._held += 1
        return result

    def release(self):
        with self._guard:
            self._slots.release()
            self._held -= 1

    def locked(self):
        with self._guard:
            return self._held > 0


# Only explicit opt-in and finite CPU/RAM quotas enable parallel assembly.
# The default remains the exact threading.Lock contract. LibreOffice and shared
# filesystem conversion locks remain exclusive on every configuration.
_WORK_CAPACITY = heavy_job_capacity()
_WORK_SLOT = (threading.Lock() if _WORK_CAPACITY == 1
              else _ParallelWorkSlots(_WORK_CAPACITY))
_ADMISSION_LOCK = threading.Lock()
_ACTIVE_WORK = 0
_WORK_LOCAL = threading.local()
_PRIORITY_LOCK = threading.Lock()
_FOREGROUND_WAITING = 0
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
            if headroom < PREVIEW_HEADROOM_BYTES:
                raise RenderBusy('Preview is queued while the service is busy. Your edits are still here.')


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
                if not _FOREGROUND_WAITING and _WORK_SLOT.acquire(blocking=False):
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
    global _FOREGROUND_WAITING
    if getattr(_WORK_LOCAL, 'active', False):
        yield
        return
    queue_started = time.monotonic()
    if preview:
        headroom = memory_headroom()
        if headroom is not None and headroom < PREVIEW_HEADROOM_BYTES:
            record_span("work_queue", time.monotonic() - queue_started, outcome="busy")
            raise RenderBusy('Preview is queued while the service is busy. Your edits are still here.')
        if review:
            acquired = _wait_for_review_slot(wait_seconds)
        else:
            with _PRIORITY_LOCK:
                if _FOREGROUND_WAITING or _REVIEW_WAITING:
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
    record_span("work_queue", time.monotonic() - queue_started,
                outcome="ok" if acquired else "busy")
    if not acquired:
        raise RenderBusy('Another report is being prepared. Your saved work is unchanged; retry generation shortly.')

    # Conservative, process-local reservation. A new parallel job needs
    # headroom for itself AND every currently admitted heavy job. The first
    # job always retains the former single-worker fallback, including when
    # cgroup usage briefly becomes unreadable or the host is scaled down.
    global _ACTIVE_WORK
    try:
        with _ADMISSION_LOCK:
            if _WORK_CAPACITY > 1 and _ACTIVE_WORK:
                headroom_now = memory_headroom()
                required = (512 + 768 * (_ACTIVE_WORK + 1)) * 1024 * 1024
                if headroom_now is None or headroom_now < required:
                    raise RenderBusy('Additional report work is queued while memory is busy. Your saved work is unchanged.')
            _ACTIVE_WORK += 1
    except BaseException:
        _WORK_SLOT.release()
        raise
    _WORK_LOCAL.active = True
    _WORK_LOCAL.preview_guard = _PreviewMemoryGuard(headroom) if preview else None
    try:
        if preview:
            _WORK_LOCAL.preview_guard()
        yield
    finally:
        _WORK_LOCAL.preview_guard = None
        _WORK_LOCAL.active = False
        with _ADMISSION_LOCK:
            _ACTIVE_WORK -= 1
        _WORK_SLOT.release()
