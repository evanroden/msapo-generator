"""Opt-in, bounded cross-process render leases for hosts with measured resources.

The default 512 MiB Render path deliberately keeps its original single locks.
This is an admission controller, not a thread pool: callers own their native
objects and LibreOffice is still launched as an isolated subprocess.
"""
from __future__ import annotations

from contextlib import contextmanager
import itertools
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

MIB = 1024 * 1024
# Two large office/native jobs plus 512 MiB for app, parser and UI work.
PARALLEL_MIN_MEMORY = 2048 * MIB
RESERVE_BYTES = 160 * MIB
ESTIMATED_PEAK = {
    "heavy": 512 * MIB,       # native assembly / standalone conversion
    "conversion": 320 * MIB,  # inside an already admitted heavy lease
    "parse": 128 * MIB,
    "raster": 128 * MIB,
    "io": 32 * MIB,
}
CAPACITIES = {"heavy": 2, "conversion": 2, "parse": 2, "raster": 2, "io": 4}
PRIORITIES = {"export": 0, "review": 1, "visible": 2, "parse": 3, "optional": 4}
_CV = threading.Condition()
_WAITING = []
_RUNNING = {kind: 0 for kind in CAPACITIES}
_SERIAL = itertools.count()


class AdmissionUnavailable(RuntimeError):
    pass


def _read_int(path):
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def _memory_limit():
    for path in ("/sys/fs/cgroup/memory.max",
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        result = _read_int(path)
        if result is not None and 0 < result < 1 << 60:
            return result
    return None


def _cpu_capacity():
    """Use cgroup quota rather than host os.cpu_count on limited containers."""
    quota_cpu = None
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            quota_cpu = int(quota) / int(period)
    except (OSError, ValueError, ZeroDivisionError):
        pass
    if quota_cpu is None:
        quota = _read_int("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        period = _read_int("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if quota is not None and quota > 0 and period and period > 0:
            quota_cpu = quota / period
    if quota_cpu is None:
        return None  # Host affinity alone does not establish a finite CPU quota.
    try:
        return min(quota_cpu, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return quota_cpu


def parallel_enabled():
    """A flag alone cannot turn a 512 MiB/0.5 CPU instance into a two-job host."""
    return (os.getenv("MSAPO_RENDER_PARALLEL") == "1" and
            os.name == "posix" and sys.platform == "linux" and
            (_memory_limit() or 0) >= PARALLEL_MIN_MEMORY and
            (_cpu_capacity() or 0) >= 2)


def snapshot():
    """Aggregate of this process's admissions, not a global cross-host count."""
    with _CV:
        return {"queued": {k: sum(t[2] == k for t in _WAITING) for k in CAPACITIES},
                "running": dict(_RUNNING), "parallel": parallel_enabled()}


def _lock_folder():
    """Container-wide directory for resource-admission locks.

    Report storage stays namespaced: isolated QA points _root() at its own
    directory, so a live heavy lease and an isolated QA heavy lease used to
    get independent slot/budget locks against the same cgroup and could
    double-book the same headroom. Lock files hold no report data, only
    flocks, so one shared directory is safe. MSAPO_RESOURCE_LOCK_DIR
    overrides it for tests and operators.
    """
    override = (os.environ.get("MSAPO_RESOURCE_LOCK_DIR") or "").strip()
    folder = Path(override) if override else Path(tempfile.gettempdir()) / "msapo-render-jobs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _slot_path(kind, index):
    folder = _lock_folder()
    # A01's Office admission exclusively owns .conversion-lock[-1].
    # Reserve memory with a distinct lock to avoid self-deadlock when the
    # same thread subsequently obtains A01's authoritative conversion lane.
    name = f".resource-{kind}-{index}.lock"
    return folder / name


def _try_slot(kind):
    import fcntl
    for index in range(CAPACITIES[kind]):
        handle = _slot_path(kind, index).open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return index, handle
        except (BlockingIOError, OSError):
            handle.close()
    return None



def _locked_count(kind):
    """Count in-flight leases across all processes sharing the data directory.

    Every probe opens its own file description: flock collisions are visible
    even for another thread in this same process.
    """
    import fcntl
    total = 0
    for index in range(CAPACITIES[kind]):
        with _slot_path(kind, index).open("a+b") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                total += 1
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return total


def _try_admit_budgeted(kind, headroom):
    """Atomically check cross-process reservations and claim a lane.

    Checking only process-local counters permits two workers to spend the same
    remaining cgroup bytes. The shared budget flock serializes the check with
    slot acquisition; the lane locks retain reservations until release.
    """
    import fcntl
    folder = _lock_folder()
    with (folder / ".resource-budget.lock").open("a+b") as budget:
        try:
            fcntl.flock(budget.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            return None
        try:
            # Account for *every* class, including conversions nested in a
            # heavy worker and native allocations not yet reflected by RSS.
            counts = {name: _locked_count(name) for name in CAPACITIES}
            reserved = sum(counts[name] * ESTIMATED_PEAK[name] for name in CAPACITIES)
            free = headroom() if headroom is not None else None
            if kind == "conversion" and counts["heavy"] > counts["conversion"]:
                # A conversion runs inside an already admitted heavy lease,
                # whose peak covers the conversion's peak: transfer that
                # reservation instead of charging a second full peak, or two
                # admitted heavies could both wait for a conversion neither
                # can get. A conversion without a heavy lease still charges
                # its own peak.
                needed = reserved + RESERVE_BYTES
            else:
                needed = reserved + ESTIMATED_PEAK[kind] + RESERVE_BYTES
            if free is None or free < needed:
                return None
            return _try_slot(kind)
        finally:
            fcntl.flock(budget.fileno(), fcntl.LOCK_UN)


@contextmanager
def lease(kind, *, priority="visible", wait_seconds=0, headroom=None,
          is_current=None):
    """FIFO within priority; timeout/cancel safely removes only its own ticket.

    File locks bound each class across app processes. The cgroup limit, live
    free memory and already reserved heavy slots must all permit admission.
    A cancelled queued request cannot run; started work is never cancelled.
    """
    if kind not in CAPACITIES or priority not in PRIORITIES:
        raise ValueError("Unknown resource class or priority")
    if not parallel_enabled():
        raise AdmissionUnavailable("Parallel admission requires a measured high-resource host.")
    deadline = time.monotonic() + max(0, min(float(wait_seconds), 130))
    ticket = (PRIORITIES[priority], next(_SERIAL), kind)
    acquired = None
    with _CV:
        _WAITING.append(ticket)
        try:
            while acquired is None:
                if is_current is not None and not is_current():
                    raise AdmissionUnavailable("The queued preview was superseded; edits are unchanged.")
                if (ticket == min((t for t in _WAITING if t[2] == kind),
                                  default=ticket)):
                    acquired = _try_admit_budgeted(kind, headroom)
                if acquired is not None:
                    _RUNNING[kind] += 1
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AdmissionUnavailable("The render queue is full or memory is constrained; retry shortly.")
                _CV.wait(timeout=min(.05, remaining))
        finally:
            _WAITING.remove(ticket)
    try:
        yield acquired[0]
    finally:
        import fcntl
        index, handle = acquired
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            with _CV:
                _RUNNING[kind] -= 1
                _CV.notify_all()
