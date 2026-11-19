"""Bounded, optional PDF-page raster workers for large reviewed batches.

PyMuPDF objects never cross process boundaries. The normal PreviewStore visible
page API remains serial: starting a pool to paint only one or two pages is slower.
No process touches the durable report library or publishes prepared assets.
"""
from __future__ import annotations

from collections import deque
import hashlib
import math
import multiprocessing
import os
from pathlib import Path
from threading import BoundedSemaphore

# 24-page and visible two-page previews remain serial. A pool may only pay for
# itself on substantially larger batches and has an explicit per-process lane.
MIN_PARALLEL_PAGES = 64
MIN_PDF_BYTES = 256 * 1024
MIN_MEMORY_BYTES = 2 * 1024 ** 3
MIN_FREE_MEMORY_BYTES = 768 * 1024 ** 2
MAX_WORKERS = 2
WORKER_TIMEOUT_SECONDS = 90
RASTER_SLOT = BoundedSemaphore(1)


def _int_file(name):
    try:
        value = Path(name).read_text().strip()
        return int(value) if value.isdecimal() and int(value) > 0 else None
    except (OSError, ValueError):
        return None


def resource_limits():
    """Return available memory, total memory limit and effective CPU quota.

    Cgroup limits take precedence over physical host memory/CPU. A missing
    resource measurement is not permission to start extra processes.
    """
    try:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError):
        return 0, 0, 0
    cgroup_limit = _int_file("/sys/fs/cgroup/memory.max") or _int_file(
        "/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if cgroup_limit:
        total = min(total, cgroup_limit)
    used = _int_file("/sys/fs/cgroup/memory.current") or _int_file(
        "/sys/fs/cgroup/memory/memory.usage_in_bytes")
    available = max(0, total - used) if used is not None else 0
    try:
        cpu = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpu = os.cpu_count() or 1
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            cpu = min(cpu, int(quota) / int(period))
    except (OSError, ValueError, ZeroDivisionError):
        quota = _int_file("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        period = _int_file("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if quota and period:
            cpu = min(cpu, quota / period)
    return available, total, cpu


def eligible(page_count):
    if page_count < MIN_PARALLEL_PAGES or multiprocessing.current_process().daemon:
        return False
    available, total, cpu = resource_limits()
    return total >= MIN_MEMORY_BYTES and available >= MIN_FREE_MEMORY_BYTES and cpu >= 2


# Lazily opened, process-local state; never pass a fitz.Document or Pixmap
# through multiprocessing. Each worker validates its own immutable input.
_WORKER_PDF = None
_WORKER_KEY = None


def _raster_page(job):
    global _WORKER_PDF, _WORKER_KEY
    path, digest, number, dpi, pixels, maximum_bytes = job
    if _WORKER_KEY != (path, digest):
        if _WORKER_PDF is not None:
            _WORKER_PDF.close()
            _WORKER_PDF = None
        with open(path, "rb") as stream:
            raw = stream.read(maximum_bytes + 1)
        if len(raw) > maximum_bytes or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("A source file failed its integrity check.")
        import pymupdf as fitz
        _WORKER_PDF = fitz.open(stream=raw, filetype="pdf")
        _WORKER_KEY = (path, digest)
    page = _WORKER_PDF[number - 1]
    width, height = page.rect.width * dpi / 72, page.rect.height * dpi / 72
    if not all(math.isfinite(n) and n > 0 for n in (width, height)) or width * height > pixels:
        raise ValueError("This PDF page is too large to rasterize safely.")
    png = page.get_pixmap(dpi=dpi, alpha=False).tobytes("png")
    from app.monthly_report_docx import normalize_report_image
    return number, normalize_report_image(png, ".png", line_art=True, dpi=dpi)


def parallel_pages(path, digest, numbers, *, dpi, max_pixels, max_source_bytes):
    """Yield ordered (page, ReportImage) pairs with two bounded in-flight jobs.

    The caller must have verified the original with source_bytes() and must
    close this generator on cancellation. Even if a task fails, terminate and
    join workers before releasing the session's single raster lane.
    """
    pages = iter(numbers)
    # forkserver starts from a clean interpreter (no inherited PyMuPDF state)
    # and avoids repeatedly importing the entire application in every child.
    # Windows and installations without forkserver use safe spawn instead.
    method = "forkserver" if "forkserver" in multiprocessing.get_all_start_methods() else "spawn"
    context = multiprocessing.get_context(method)
    pool = context.Pool(processes=MAX_WORKERS)
    pending = deque()
    def submit(number):
        return pool.apply_async(_raster_page, ((str(path), digest, number, dpi,
                                               max_pixels, max_source_bytes),))
    completed = False
    try:
        for _ in range(MAX_WORKERS):
            try:
                pending.append(submit(next(pages)))
            except StopIteration:
                break
        while pending:
            result = pending.popleft().get(timeout=WORKER_TIMEOUT_SECONDS)
            yield result
            try:
                pending.append(submit(next(pages)))
            except StopIteration:
                pass
        completed = True
    finally:
        # Graceful close on success avoids killing live worker shutdown;
        # cancelled/failed/stale requests must stop remaining work now.
        if completed:
            pool.close()
        else:
            pool.terminate()
        pool.join()
