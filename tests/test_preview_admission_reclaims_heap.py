"""A preview refused for low headroom first returns freed heap to the OS.

Freed Python/glibc memory stays charged to the container until it is trimmed,
and the trim otherwise runs only inside an admitted conversion, so memory
freed by earlier sessions could keep every later preview refused. Synthetic
headroom values only; no real cgroup is read.
"""
import pytest

from app import monthly_report_render_jobs as jobs

MIB = 1024 * 1024


@pytest.fixture
def constrained(monkeypatch):
    # The single-worker host the capped 512 MiB container runs on.
    monkeypatch.setattr(jobs, '_WORK_CAPACITY', 1)
    monkeypatch.setattr(jobs, '_ACTIVE_WORK', 0)
    calls = []
    monkeypatch.setattr(jobs, '_reclaim_preview_heap', lambda: calls.append('trim'))
    return monkeypatch, calls


def test_low_headroom_is_reclaimed_then_preview_admitted(constrained):
    monkeypatch, calls = constrained
    # Freed heap comes back only once it has been trimmed.
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 300 * MIB if calls else 100 * MIB)
    with jobs.work_slot(preview=True):
        assert jobs.preview_memory_guard() is not None
    assert calls == ['trim']
    assert not jobs._WORK_SLOT.locked()


def test_preview_still_refused_when_reclaim_frees_too_little(constrained):
    monkeypatch, calls = constrained
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 100 * MIB)
    with pytest.raises(jobs.RenderBusy, match='queued while the service is busy'):
        with jobs.work_slot(preview=True):
            pytest.fail('a preview must not run below its memory budget')
    assert calls == ['trim']
    assert not jobs._WORK_SLOT.locked()


def test_enough_headroom_never_pays_for_a_reclaim(constrained):
    monkeypatch, calls = constrained
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 300 * MIB)
    with jobs.work_slot(preview=True):
        pass
    assert calls == []


def test_unknown_headroom_skips_the_reclaim(constrained):
    monkeypatch, calls = constrained
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: None)
    with jobs.work_slot(preview=True):
        pass
    assert calls == []
