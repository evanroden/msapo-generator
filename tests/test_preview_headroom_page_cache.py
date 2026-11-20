"""Preview headroom counts the container's real use, not reclaimable file cache.

Synthetic cgroup files only; no real cgroup is read or changed.
"""
from app import monthly_report_render_jobs as jobs

MIB = 1024 * 1024


def _v2(tmp_path, *, limit, current, stat):
    folder = tmp_path / "v2"
    folder.mkdir()
    (folder / "memory.max").write_text(str(limit))
    (folder / "memory.current").write_text(str(current))
    if stat is not None:
        (folder / "memory.stat").write_text(stat)
    return folder


def _only(monkeypatch, *roots):
    monkeypatch.setattr(jobs, "_CGROUP_MEMORY", roots)


def test_inactive_file_cache_is_not_counted_as_used(monkeypatch, tmp_path):
    # 512 MiB container: 400 MiB charged, 120 MiB of it inactive file cache
    # (for example LibreOffice libraries after a conversion).
    folder = _v2(tmp_path, limit=512 * MIB, current=400 * MIB,
                 stat=f"anon {250 * MIB}\nfile {150 * MIB}\nactive_file {30 * MIB}\n"
                      f"inactive_file {120 * MIB}\n")
    _only(monkeypatch, (str(folder), "memory.max", "memory.current", "inactive_file"))
    assert jobs._memory_status() == ("finite", 232 * MIB)
    assert jobs.memory_headroom() >= jobs.PREVIEW_HEADROOM_BYTES


def test_active_cache_and_anonymous_memory_still_count(monkeypatch, tmp_path):
    folder = _v2(tmp_path, limit=512 * MIB, current=400 * MIB,
                 stat=f"anon {370 * MIB}\nactive_file {30 * MIB}\ninactive_file 0\n")
    _only(monkeypatch, (str(folder), "memory.max", "memory.current", "inactive_file"))
    assert jobs.memory_headroom() == 112 * MIB
    assert jobs.memory_headroom() < jobs.PREVIEW_HEADROOM_BYTES


def test_missing_or_broken_stat_keeps_the_stricter_measure(monkeypatch, tmp_path):
    folder = _v2(tmp_path, limit=512 * MIB, current=400 * MIB, stat=None)
    _only(monkeypatch, (str(folder), "memory.max", "memory.current", "inactive_file"))
    assert jobs.memory_headroom() == 112 * MIB
    (folder / "memory.stat").write_text("inactive_file not-a-number\n")
    assert jobs.memory_headroom() == 112 * MIB


def test_cache_larger_than_usage_never_reports_more_than_the_limit(monkeypatch, tmp_path):
    folder = _v2(tmp_path, limit=512 * MIB, current=10 * MIB,
                 stat=f"inactive_file {50 * MIB}\n")
    _only(monkeypatch, (str(folder), "memory.max", "memory.current", "inactive_file"))
    assert jobs.memory_headroom() == 512 * MIB


def test_cgroup_v1_uses_total_inactive_file(monkeypatch, tmp_path):
    folder = tmp_path / "v1"
    folder.mkdir()
    (folder / "memory.limit_in_bytes").write_text(str(512 * MIB))
    (folder / "memory.usage_in_bytes").write_text(str(450 * MIB))
    (folder / "memory.stat").write_text(f"cache {200 * MIB}\ninactive_file {5 * MIB}\n"
                                        f"total_inactive_file {100 * MIB}\n")
    _only(monkeypatch, (str(tmp_path / "absent"), "memory.max", "memory.current", "inactive_file"),
          (str(folder), "memory.limit_in_bytes", "memory.usage_in_bytes", "total_inactive_file"))
    assert jobs._memory_status() == ("finite", 162 * MIB)


def test_unlimited_and_absent_cgroups_are_unchanged(monkeypatch, tmp_path):
    folder = tmp_path / "v2"
    folder.mkdir()
    (folder / "memory.max").write_text("max")
    _only(monkeypatch, (str(folder), "memory.max", "memory.current", "inactive_file"))
    assert jobs._memory_status() == ("unlimited", None)
    _only(monkeypatch, (str(tmp_path / "absent"), "memory.max", "memory.current", "inactive_file"))
    assert jobs._memory_status() == ("unsupported", None)
