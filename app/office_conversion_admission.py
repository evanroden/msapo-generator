"""Fail-closed, cross-process LibreOffice admission with private process lanes.

The default remains the legacy single-slot conversion lock. Opt-in allows
two distinct profiles/subprocesses only when finite cgroup CPU and RAM
quotas permit it. The mode flock prevents a serial deployment from racing a
parallel deployment during scale-down or a rolling restart.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sys
import time

MIB = 1024 * 1024
GIB = 1024 * MIB
MIN_PARALLEL_MEMORY = 3 * GIB
SECOND_LANE_HEADROOM = 1536 * MIB


class OfficeLaneBusy(RuntimeError):
    """A conversion lease was not available within its bounded wait."""


def _read_int(path):
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def _limits(root=Path('/sys/fs/cgroup')):
    """Effective finite quota and memory limit, not physical host totals."""
    try:
        cpu_raw = (root / 'cpu.max').read_text().split()
        if len(cpu_raw) != 2 or cpu_raw[0] == 'max':
            return None
        cpu = int(cpu_raw[0]) / int(cpu_raw[1])
    except FileNotFoundError:
        quota = _read_int(root / 'cpu/cpu.cfs_quota_us')
        period = _read_int(root / 'cpu/cpu.cfs_period_us')
        if not quota or quota <= 0 or not period or period <= 0:
            return None
        cpu = quota / period
    except (OSError, ValueError, ZeroDivisionError, OverflowError):
        return None
    limit = _read_int(root / 'memory.max')
    if limit is None:
        limit = _read_int(root / 'memory/memory.limit_in_bytes')
    if not limit or limit < 0 or limit >= (1 << 60):
        return None
    return cpu, limit


def parallel_enabled():
    """Requires an explicit flag AND measured container capacity."""
    if os.environ.get('MSAPO_OFFICE_PARALLEL') != '1' or sys.platform != 'linux':
        return False
    limits = _limits()
    if limits is None or limits[0] < 2 or limits[1] < MIN_PARALLEL_MEMORY:
        return False
    try:
        return len(os.sched_getaffinity(0)) >= 2
    except (AttributeError, OSError):
        return False


def _try_lock(handle, *, shared=False):
    if os.name == 'nt':
        import msvcrt
        handle.seek(0)
        if handle.read(1) == b'':
            handle.seek(0)
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(handle.fileno(), (fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
                    | fcntl.LOCK_NB)
        return True
    except (OSError, BlockingIOError):
        return False


def _unlock(handle):
    if os.name == 'nt':
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def conversion_lane(*, wait_seconds, serial_lock, folder, memory_headroom):
    """Yield (lane, parallel) while holding every cross-process lease.

    Lane 0 retains .conversion-lock and .active-office.json compatibility.
    A high-resource lane 1 must have at least 1.5 GiB currently free.
    A mode shared/exclusive flock prevents mixed-capacity deployments from
    occupying the same container budget. No spin lock is held while sleeping.
    """
    deadline = time.monotonic() + max(0, min(float(wait_seconds), 130))
    parallel = parallel_enabled()
    if not parallel and not serial_lock.acquire(timeout=max(0, deadline - time.monotonic())):
        raise OfficeLaneBusy('Another report is rendering. Please try again shortly.')
    try:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        # Windows never opts into parallel and retains the legacy lock only.
        mode_file = folder / '.conversion-mode.lock'
        with mode_file.open('a+b') as mode:
            while not _try_lock(mode, shared=parallel):
                if time.monotonic() >= deadline:
                    raise OfficeLaneBusy('Another report is rendering. Please try again shortly.')
                time.sleep(min(.05, max(0, deadline - time.monotonic())))
            try:
                while True:
                    for lane in range(2 if parallel else 1):
                        if lane == 1:
                            free = memory_headroom()
                            if free is None or free < SECOND_LANE_HEADROOM:
                                continue
                        name = '.conversion-lock' if lane == 0 else '.conversion-lock-1'
                        with (folder / name).open('a+b') as handle:
                            if not _try_lock(handle):
                                continue
                            try:
                                yield lane, parallel
                                return
                            finally:
                                _unlock(handle)
                    if time.monotonic() >= deadline:
                        raise OfficeLaneBusy('Another report is rendering. Please try again shortly.')
                    time.sleep(min(.05, max(0, deadline - time.monotonic())))
            finally:
                _unlock(mode)
    finally:
        if not parallel:
            serial_lock.release()
