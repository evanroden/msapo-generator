"""Bounded, cross-process serialization of monthly report office conversions."""
import os
import threading
import time
from contextlib import contextmanager

from app import pdf_converter
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
    deadline = time.monotonic() + max(0, min(float(wait_seconds), 130))
    if not _SLOT.acquire(timeout=max(0, deadline - time.monotonic())):
        raise RenderBusy("Another report is rendering. Please try again shortly.")
    try:
        folder = _root() / "render-jobs"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / ".conversion-lock").open("a+b") as lock:
            if os.name == "nt":
                import msvcrt
                lock.write(b"0"); lock.flush()
            else:
                import fcntl
            while True:
                try:
                    if os.name == "nt":
                        lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        raise RenderBusy("Another report is rendering. Please try again shortly.") from None
                    time.sleep(min(.05, max(0, deadline - time.monotonic())))
            try:
                _CONVERSION_LOCAL.active = True
                # python-docx package/relationship cycles can otherwise retain
                # decoded media while the office process starts allocating.
                import gc
                gc.collect()
                yield
            finally:
                _CONVERSION_LOCAL.active = False
                if os.name == "nt":
                    lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        _SLOT.release()


def convert_to_pdf(path, *, wait_seconds=10):
    with conversion_slot(wait_seconds=wait_seconds):
        return pdf_converter.convert_to_pdf(path)


# Assembly can hold decoded pictures and an entire OOXML package. Serialize that
# phase separately from the backend lock: a metafile helper may itself convert a
# document, so holding the conversion lock around assembly would deadlock it.
_WORK_SLOT = threading.Lock()
_WORK_LOCAL = threading.local()
_PRIORITY_LOCK = threading.Lock()
_FOREGROUND_WAITING = 0
PREVIEW_HEADROOM_BYTES = 160 * 1024 * 1024


def memory_headroom():
    """Use the container's actual limit, not host RAM or a guessed service plan."""
    from pathlib import Path
    for folder, limit_name, used_name in (
        (Path('/sys/fs/cgroup'), 'memory.max', 'memory.current'),
        (Path('/sys/fs/cgroup/memory'), 'memory.limit_in_bytes', 'memory.usage_in_bytes'),
    ):
        try:
            limit = int((folder / limit_name).read_text().strip())
            used = int((folder / used_name).read_text().strip())
        except (OSError, ValueError):
            continue
        if 0 < limit < 1 << 60 and used >= 0:
            return max(0, limit - used)
    return None


@contextmanager
def work_slot(*, preview=False, wait_seconds=130):
    """Admit one heavy monthly job; background work yields to foreground export."""
    global _FOREGROUND_WAITING
    if getattr(_WORK_LOCAL, 'active', False):
        yield
        return
    if preview:
        with _PRIORITY_LOCK:
            waiting = _FOREGROUND_WAITING
        headroom = memory_headroom()
        if waiting or (headroom is not None and headroom < PREVIEW_HEADROOM_BYTES):
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
    if not acquired:
        raise RenderBusy('Another report is being prepared. Your saved work is unchanged; retry generation shortly.')
    _WORK_LOCAL.active = True
    try:
        yield
    finally:
        _WORK_LOCAL.active = False
        _WORK_SLOT.release()
