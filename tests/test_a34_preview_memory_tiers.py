"""A34: synthetic cgroup controls and measured peak-based preflight."""
import pytest
from app.monthly_preview_memory_budget import (MIB, MEASURED_NATIVE_PEAK_BYTES,
    PREVIEW_JOB_ESTIMATE_BYTES, required_free_bytes, preview_worker_budget)


@pytest.mark.parametrize('cpu,memory_gib,setting,expected', [
    ('50000 100000', 0.5, 'auto', 1),
    ('100000 100000', 2, 'auto', 1),
    ('200000 100000', 2, 'auto', 2),
    ('400000 100000', 4, 'auto', 3),
    ('400000 100000', 8, '2', 2),
    ('400000 100000', 8, '99', 3),
    ('150000 100000', 4, 'auto', 1),
    ('400000 100000', 8, '1', 1),
    ('400000 100000', 8, 'malformed', 1),
    ('400000 100000', 8, '-1', 1),
])
def test_finite_cgroup_v2(tmp_path, cpu, memory_gib, setting, expected):
    (tmp_path / 'cpu.max').write_text(cpu)
    (tmp_path / 'memory.max').write_text(str(int(memory_gib * 1024**3)))
    assert preview_worker_budget(setting, root=tmp_path, affinity_cpus=8) == expected


def test_v1_finite_limits_and_affinity(tmp_path):
    (tmp_path / 'cpu').mkdir()
    (tmp_path / 'memory').mkdir()
    (tmp_path / 'cpu/cpu.cfs_quota_us').write_text('200000')
    (tmp_path / 'cpu/cpu.cfs_period_us').write_text('100000')
    (tmp_path / 'memory/memory.limit_in_bytes').write_text(str(4 * 1024**3))
    assert preview_worker_budget('auto', root=tmp_path, affinity_cpus=1) == 1
    assert preview_worker_budget('auto', root=tmp_path, affinity_cpus=2) == 2


@pytest.mark.parametrize('cpu,memory', [
    ('max 100000', str(4 * 1024**3)),
    ('400000 100000', 'max'),
    ('garbled', str(4 * 1024**3)),
    ('400000 100000', 'garbled'),
    ('400000 0', str(4 * 1024**3)),
    ('400000 100000', str(1 << 62)),
])
def test_unknown_limits_fail_closed(tmp_path, cpu, memory):
    (tmp_path / 'cpu.max').write_text(cpu)
    (tmp_path / 'memory.max').write_text(memory)
    assert preview_worker_budget('auto', root=tmp_path, affinity_cpus=8) == 1


def test_missing_limits_fail_closed(tmp_path):
    assert preview_worker_budget('auto', root=tmp_path, affinity_cpus=8) == 1


def test_budget_matches_measured_peak_and_bounds_growth():
    assert MEASURED_NATIVE_PEAK_BYTES == 342_962_176
    assert PREVIEW_JOB_ESTIMATE_BYTES == 384 * MIB
    assert required_free_bytes(0) == 544 * MIB
    assert required_free_bytes(1) == 928 * MIB
    assert required_free_bytes(2) == 1312 * MIB
    assert required_free_bytes(-1) == required_free_bytes(0)
