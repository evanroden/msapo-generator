"""Bounded, cross-process serialization of monthly report office conversions."""
import os
import threading
import time
from contextlib import contextmanager

from app import pdf_converter
from app.monthly_report_library import _root

_SLOT = threading.Lock()


class RenderBusy(pdf_converter.PDFConversionError):
    pass


@contextmanager
def conversion_slot(*, wait_seconds=10):
    """Preview callers fail promptly; foreground work has a bounded queue wait."""
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
                yield
            finally:
                if os.name == "nt":
                    lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        _SLOT.release()


def convert_to_pdf(path, *, wait_seconds=10):
    with conversion_slot(wait_seconds=wait_seconds):
        return pdf_converter.convert_to_pdf(path)
