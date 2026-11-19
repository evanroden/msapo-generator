"""A34: bounded high-tier admission and unchanged constrained fallback."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from app import monthly_report_render_jobs as jobs
from app.monthly_preview_memory_budget import MIB


@pytest.fixture
def high_tier(monkeypatch):
    monkeypatch.setattr(jobs, '_WORK_CAPACITY', 2)
    monkeypatch.setattr(jobs, '_WORK_SLOT', jobs._ParallelWorkSlots(2))
    monkeypatch.setattr(jobs, '_ACTIVE_WORK', 0)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 2 * 1024**3)
    return monkeypatch


def test_two_preview_leases_overlap_but_third_fails_fast(high_tier):
    gate, finish = Barrier(3), Event()

    def worker():
        with jobs.work_slot(preview=True):
            assert jobs.preview_memory_guard() is not None
            gate.wait(timeout=5)
            assert finish.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(worker), pool.submit(worker)
        try:
            gate.wait(timeout=5)
            assert jobs._ACTIVE_WORK == 2
            with pytest.raises(jobs.RenderBusy, match='Another report'):
                with jobs.work_slot(preview=True):
                    pass
        finally:
            finish.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert jobs._ACTIVE_WORK == 0 and not jobs._WORK_SLOT.locked()


def test_pressure_does_not_spend_same_headroom_twice(high_tier):
    high_tier.setattr(jobs, 'memory_headroom', lambda: 600 * MIB)
    with jobs.work_slot(preview=True):
        # A second preview in the SAME thread is a nested operation and takes
        # no second lease by design, so it can never be rejected. Run it in
        # another thread, where it must go through admission and fail.
        with ThreadPoolExecutor(max_workers=1) as pool:
            def second():
                with pytest.raises(jobs.RenderBusy, match='edits are still here'):
                    with jobs.work_slot(preview=True):
                        pass
            pool.submit(second).result(timeout=5)
        assert jobs._ACTIVE_WORK == 1
    assert jobs._ACTIVE_WORK == 0 and not jobs._WORK_SLOT.locked()


def test_unknown_live_counter_fails_closed_on_high_tier(high_tier):
    high_tier.setattr(jobs, 'memory_headroom', lambda: None)
    with pytest.raises(jobs.RenderBusy, match='Retry shortly'):
        with jobs.work_slot(preview=True):
            pass
    assert jobs._ACTIVE_WORK == 0 and not jobs._WORK_SLOT.locked()


def test_exception_releases_exact_owned_reservation(high_tier):
    with pytest.raises(RuntimeError, match='synthetic interruption'):
        with jobs.work_slot(preview=True):
            assert jobs._ACTIVE_WORK == 1
            raise RuntimeError('synthetic interruption')
    assert jobs._ACTIVE_WORK == 0 and not jobs._WORK_SLOT.locked()
    with jobs.work_slot(preview=True):
        assert jobs._ACTIVE_WORK == 1


def test_late_pressure_rejects_active_preview_without_erasing_lease(high_tier):
    remaining = [2 * 1024**3]
    high_tier.setattr(jobs, 'memory_headroom', lambda: remaining[0])
    with jobs.work_slot(preview=True):
        guard = jobs.preview_memory_guard()
        remaining[0] = 300 * MIB
        with pytest.raises(jobs.RenderBusy, match='Retry shortly'):
            guard()
        assert jobs.preview_memory_guard() is guard
    assert jobs.preview_memory_guard() is None and jobs._ACTIVE_WORK == 0


def test_constrained_control_retains_original_mutex(monkeypatch):
    monkeypatch.setattr(jobs, '_WORK_CAPACITY', 1)
    monkeypatch.setattr(jobs, '_WORK_SLOT', jobs.threading.Lock())
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 200 * MIB)
    with jobs.work_slot(preview=True):
        with pytest.raises(jobs.RenderBusy, match='Another report'):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: next(_contended_preview())).result(timeout=5)
    assert not jobs._WORK_SLOT.locked()


def _contended_preview():
    with jobs.work_slot(preview=True):
        yield


def test_foreground_export_keeps_priority_with_spare_parallel_slot(high_tier):
    with jobs.work_slot():
        assert jobs._FOREGROUND_ACTIVE == 1
        with ThreadPoolExecutor(max_workers=1) as pool:
            def background():
                with pytest.raises(jobs.RenderBusy, match='queued'):
                    with jobs.work_slot(preview=True):
                        pass
            pool.submit(background).result(timeout=5)
        assert jobs._ACTIVE_WORK == 1
    assert jobs._FOREGROUND_ACTIVE == 0 and jobs._ACTIVE_WORK == 0


def test_review_yields_to_active_foreground_even_with_two_slots(high_tier):
    with jobs.work_slot():
        with ThreadPoolExecutor(max_workers=1) as pool:
            def review():
                with pytest.raises(jobs.RenderBusy, match='Another report'):
                    with jobs.work_slot(preview=True, review=True, wait_seconds=0):
                        pass
            pool.submit(review).result(timeout=5)
    assert jobs._REVIEW_WAITING == 0 and jobs._FOREGROUND_ACTIVE == 0
