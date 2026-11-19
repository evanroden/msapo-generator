"""Bounded, cross-process serialization of monthly report office conversions."""
import os
import threading
import time
from contextlib import contextmanager

from app import pdf_converter
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


def convert_to_pdf(path, *, wait_seconds=10, lossless_images=False):
    with conversion_slot(wait_seconds=wait_seconds):
        with span("conversion"):
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


AUTO_PREVIEW_WAIT_SECONDS = 2.0


def queue_state():
    """Report waiting counts; a pending preview is not a finished ticket."""
    from app.monthly_report_visible_queue import QUEUE
    return QUEUE.snapshot()


def cancel_queued_preview(owner):
    """Cancel only queued preview requests belonging to a hidden/revised pane."""
    from app.monthly_report_visible_queue import QUEUE
    QUEUE.cancel_owner(owner)


@contextmanager
def work_slot(*, preview=False, review=False, wait_seconds=130,
              owner=None, revision=None, is_current=None):
    """Bounded visible-first admission while preserving current memory limits."""
    if review and not preview:
        raise ValueError("Review priority requires the preview memory guard.")
    if not preview and (owner is not None or revision is not None or is_current is not None):
        raise ValueError("Revision cancellation applies only to previews.")
    if getattr(_WORK_LOCAL, 'active', False):
        yield
        return

    from app.monthly_report_visible_queue import QUEUE, QueueBusy
    global _FOREGROUND_WAITING, _FOREGROUND_ACTIVE, _REVIEW_WAITING
    headroom = None
    acquired = False
    with span("job_queue"):
        if preview:
            headroom = memory_headroom()
            if headroom is not None and headroom < PREVIEW_HEADROOM_BYTES:
                raise RenderBusy('Preview is queued while the service is busy. Your edits are still here.')
            timeout = max(0, min(float(wait_seconds),
                                 10 if review else AUTO_PREVIEW_WAIT_SECONDS if owner is not None else 0))
            if not review and owner is None:
                # Retain main's fail-fast rule for unowned automatic previews
                # while foreground exports or deliberate Review are active.
                with _PRIORITY_LOCK:
                    if _FOREGROUND_WAITING or _FOREGROUND_ACTIVE or _REVIEW_WAITING:
                        raise RenderBusy('Preview is queued while the service is busy. Your edits are still here.')
        else:
            timeout = max(0, min(float(wait_seconds), 130))
        with _PRIORITY_LOCK:
            if review:
                _REVIEW_WAITING += 1
            elif not preview:
                _FOREGROUND_WAITING += 1
        def compatible_preview_turn():
            # Main's A34 review priority must not overlap an active export,
            # even when an opted-in host has an available parallel slot.
            with _PRIORITY_LOCK:
                if review:
                    return _FOREGROUND_ACTIVE == 0
                return not (_FOREGROUND_WAITING or _FOREGROUND_ACTIVE or _REVIEW_WAITING)

        try:
            try:
                QUEUE.acquire(_WORK_SLOT, preview=preview, review=review, wait_seconds=timeout,
                              owner=owner, revision=revision,
                              is_current=is_current if preview else None,
                              can_admit=compatible_preview_turn if preview and (review or owner is None) else None)
                acquired = True
            except QueueBusy as exc:
                raise RenderBusy(str(exc)) from exc
        finally:
            with _PRIORITY_LOCK:
                if review:
                    _REVIEW_WAITING -= 1
                elif not preview:
                    _FOREGROUND_WAITING -= 1
                    if acquired:
                        _FOREGROUND_ACTIVE += 1

    # Preserve main's A34 finite-cgroup parallel admission budget exactly.
    # The queue only changes who waits; it cannot bypass memory reservations.
    global _ACTIVE_WORK
    reserved = False
    try:
        if _WORK_CAPACITY > 1:
            with _ADMISSION_LOCK:
                available = memory_headroom()
                if preview:
                    if available is None or available < required_free_bytes(_ACTIVE_WORK):
                        raise RenderBusy(
                            'Additional preview work is queued while memory is busy. '
                            'Your edits are still here. Retry shortly.')
                elif _ACTIVE_WORK:
                    required = (512 + 768 * (_ACTIVE_WORK + 1)) * 1024 * 1024
                    if available is None or available < required:
                        raise RenderBusy('Additional report work is queued while memory is busy. Your saved work is unchanged.')
                _ACTIVE_WORK += 1
                reserved = True
        _WORK_LOCAL.active = True
        _WORK_LOCAL.preview_guard = _PreviewMemoryGuard(headroom) if preview else None
        try:
            if preview:
                _WORK_LOCAL.preview_guard()
                if is_current is not None:
                    try:
                        current = bool(is_current())
                    except Exception:
                        current = False
                    if not current:
                        raise RenderBusy('The preview request is obsolete. Your edits are still here.')
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
        QUEUE.release(_WORK_SLOT)
