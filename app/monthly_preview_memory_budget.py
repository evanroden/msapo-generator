"""Opt-in Monthly heavy-job budget calibrated against synthetic native preview RSS.

The November 11, 2026 512 MiB/0.5 CPU resource job (GitHub Actions
43071520534, monthly-report-resources) measured 342,962,176 bytes peak
container use with eight large image frames and ten native tables. Round that
up to 384 MiB per additional job; allow 160 MiB free for recovery. This is a
conservative preflight estimate, not an allocation guarantee. The live cgroup
counter and the per-preview guard remain authoritative throughout a job.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

MIB = 1024 * 1024
MEASURED_NATIVE_PEAK_BYTES = 342_962_176
PREVIEW_JOB_ESTIMATE_BYTES = ((MEASURED_NATIVE_PEAK_BYTES + 64 * MIB - 1) // (64 * MIB)) * 64 * MIB
FREE_MEMORY_RESERVE_BYTES = 160 * MIB
NON_PREVIEW_BUDGET_BYTES = 512 * MIB
MAX_PREVIEW_WORKERS = 3
CGROUP_ROOT = Path('/sys/fs/cgroup')


def _read(root: Path, filename: str) -> str | None:
    try:
        return (root / filename).read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return None


def _positive_int(raw: str | None) -> int | None:
    try:
        number = int(raw) if raw is not None else 0
    except ValueError:
        return None
    return number if number > 0 else None


def _limits(root: Path) -> tuple[float | None, int | None]:
    """Only finite, valid CPU and memory cgroups authorize extra jobs."""
    quota = _read(root, 'cpu.max')
    if quota is not None:
        parts = quota.split()
        if len(parts) != 2:
            return None, None
        numerator = _positive_int(parts[0])
        denominator = _positive_int(parts[1])
    else:
        numerator = _positive_int(_read(root, 'cpu/cpu.cfs_quota_us'))
        denominator = _positive_int(_read(root, 'cpu/cpu.cfs_period_us'))
    cpu = numerator / denominator if numerator and denominator else None

    raw = _read(root, 'memory.max')
    if raw is None:
        raw = _read(root, 'memory/memory.limit_in_bytes')
    memory = _positive_int(raw)
    if memory is not None and memory >= (1 << 60):
        memory = None
    return cpu, memory


def preview_worker_budget(setting: str | None = None, *, root: Path = CGROUP_ROOT,
                          affinity_cpus: int | None = None) -> int:
    """Default one job; opt-in `auto` or 2/3 requires real CPU+RAM headroom.

    Never infer container quotas from os.cpu_count() or unlimited cgroups.
    Settings are sampled once when the render-jobs module is imported, not
    changed underneath ongoing leases. Higher counts are capped at three.
    """
    if setting is None:
        setting = os.getenv('MSAPO_PREVIEW_MEMORY_TIER', '1')
    if setting == 'auto':
        requested = MAX_PREVIEW_WORKERS
    else:
        requested = _positive_int(setting)
    if requested is None or requested <= 1 or os.name != 'posix' or sys.platform != 'linux':
        return 1
    try:
        if affinity_cpus is None:
            affinity_cpus = (len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity')
                             else os.cpu_count())
    except OSError:
        return 1
    cpu, memory = _limits(root)
    if cpu is None or memory is None or not affinity_cpus or memory < 2 * 1024 ** 3:
        return 1
    # Do not spend all memory on measured peak allocations. Backpressure still
    # checks *live* free cgroup memory before launching any additional job.
    slots_from_ram = max(1, (memory - NON_PREVIEW_BUDGET_BYTES) // PREVIEW_JOB_ESTIMATE_BYTES)
    return max(1, min(requested, MAX_PREVIEW_WORKERS, int(cpu), affinity_cpus, slots_from_ram))


def required_free_bytes(active_jobs: int) -> int:
    """Worst-case preflight for another lease; active >= 0 and already counted."""
    return FREE_MEMORY_RESERVE_BYTES + PREVIEW_JOB_ESTIMATE_BYTES * (max(0, active_jobs) + 1)
