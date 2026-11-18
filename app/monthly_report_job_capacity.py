"""Optional, fail-closed compute sizing for in-process heavy report work.

No extra report slots are enabled by default. Both Render and Azure Container
Apps expose Linux cgroup quotas; a host CPU count alone is never sufficient to
opt into parallel assembly. This does not increase LibreOffice concurrency or
permit multiple replicas/writers to a shared report store.
"""
from __future__ import annotations

import os
from pathlib import Path

_GIB = 1024 ** 3
_MAX_JOBS = 8
_ROOT = Path('/sys/fs/cgroup')


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return None


def _positive_int(value: str | None) -> int | None:
    try:
        number = int(value) if value is not None else 0
    except ValueError:
        return None
    return number if number > 0 else None


def _cgroup_cpu(root: Path) -> float | None:
    """Read v2 quota or v1 quota/period; unlimited/invalid is unknown."""
    v2 = _read_text(root / 'cpu.max')
    if v2 is not None:
        parts = v2.split()
        if len(parts) != 2 or parts[0] == 'max':
            return None
        quota, period = (_positive_int(part) for part in parts)
    else:
        quota = _positive_int(_read_text(root / 'cpu' / 'cpu.cfs_quota_us'))
        period = _positive_int(_read_text(root / 'cpu' / 'cpu.cfs_period_us'))
    if quota is None or period is None:
        return None
    return quota / period


def _cgroup_memory(root: Path) -> int | None:
    """Unknown/unlimited memory cannot authorize greater concurrency."""
    raw = _read_text(root / 'memory.max')
    if raw is None:
        raw = _read_text(root / 'memory' / 'memory.limit_in_bytes')
    size = _positive_int(raw)
    return size if size is not None and size < (1 << 60) else None


def heavy_job_capacity(setting: str | None = None, *, root: Path = _ROOT,
                       affinity_cpus: int | None = None) -> int:
    """Number of same-process report assembly slots, not writer replicas.

    MSAPO_HEAVY_JOB_CONCURRENCY=1 (default) retains exclusive work admission.
    'auto' or 2..8 explicitly opts in, but never exceeds cgroup CPU/2 GiB per
    slot. Missing/unlimited/invalid quotas, fractional CPU and low RAM => 1.
    Read once at process start: changing environment does not mutate live jobs.
    """
    if setting is None:
        setting = os.environ.get('MSAPO_HEAVY_JOB_CONCURRENCY', '1')
    if setting == 'auto':
        requested = _MAX_JOBS
    else:
        requested = _positive_int(setting)
        if requested is None:
            return 1
    if requested <= 1:
        return 1
    try:
        if affinity_cpus is None:
            affinity_cpus = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count()
    except OSError:
        return 1
    cpu = _cgroup_cpu(root)
    memory = _cgroup_memory(root)
    if not affinity_cpus or cpu is None or memory is None:
        return 1
    # Floor the CPU quota so a 1.5 CPU container never runs two heavy jobs.
    return max(1, min(requested, _MAX_JOBS, affinity_cpus, int(cpu), memory // (2 * _GIB)))
