"""Synthetic cgroup controls; no client assets or live plan changes."""
import pytest

from app.monthly_report_job_capacity import heavy_job_capacity


@pytest.mark.parametrize('cpu, memory_gib, flag, expected', [
    ('50000 100000', 0.5, 'auto', 1),
    ('100000 100000', 2, 'auto', 1),
    ('200000 100000', 4, '1', 1),
    ('200000 100000', 4, 'auto', 2),
    ('400000 100000', 8, 'auto', 4),
    ('800000 100000', 16, 'auto', 8),
    ('400000 100000', 8, '2', 2),
    ('400000 100000', 8, '99', 4),
    ('150000 100000', 4, 'auto', 1),
    ('400000 100000', 3, 'auto', 1),
    ('400000 100000', 8, '0', 1),
    ('400000 100000', 8, 'malformed', 1),
    ('400000 100000', 8, '-5', 1),
])
def test_cgroup_v2_limits_are_conservative(tmp_path, cpu, memory_gib, flag, expected):
    (tmp_path / 'cpu.max').write_text(cpu)
    (tmp_path / 'memory.max').write_text(str(int(memory_gib * 1024**3)))
    assert heavy_job_capacity(flag, root=tmp_path, affinity_cpus=16) == expected


def test_cgroup_v1_compatible(tmp_path):
    (tmp_path / 'cpu').mkdir()
    (tmp_path / 'memory').mkdir()
    (tmp_path / 'cpu' / 'cpu.cfs_quota_us').write_text('400000')
    (tmp_path / 'cpu' / 'cpu.cfs_period_us').write_text('100000')
    (tmp_path / 'memory' / 'memory.limit_in_bytes').write_text(str(8 * 1024**3))
    assert heavy_job_capacity('auto', root=tmp_path, affinity_cpus=16) == 4
    assert heavy_job_capacity('auto', root=tmp_path, affinity_cpus=2) == 2


@pytest.mark.parametrize('cpu, mem', [
    (None, None), ('max 100000', str(8 * 1024**3)),
    ('broken', str(8 * 1024**3)), ('400000 100000', 'max'),
    ('400000 0', str(8 * 1024**3)), ('400000 100000', '-1'),
    ('400000 100000', 'not-number'),
])
def test_missing_unlimited_invalid_quota_falls_back_to_one(tmp_path, cpu, mem):
    if cpu is not None:
        (tmp_path / 'cpu.max').write_text(cpu)
    if mem is not None:
        (tmp_path / 'memory.max').write_text(mem)
    assert heavy_job_capacity('auto', root=tmp_path, affinity_cpus=16) == 1


def test_default_disabled_even_on_large_machine(tmp_path, monkeypatch):
    (tmp_path / 'cpu.max').write_text('800000 100000')
    (tmp_path / 'memory.max').write_text(str(16 * 1024**3))
    monkeypatch.delenv('MSAPO_HEAVY_JOB_CONCURRENCY', raising=False)
    assert heavy_job_capacity(root=tmp_path, affinity_cpus=16) == 1
    monkeypatch.setenv('MSAPO_HEAVY_JOB_CONCURRENCY', 'auto')
    assert heavy_job_capacity(root=tmp_path, affinity_cpus=16) == 8
