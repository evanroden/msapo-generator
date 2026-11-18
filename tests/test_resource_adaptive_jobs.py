"""A19: parallel assembly is opt-in; memory pressure never starts a second job.

These tests use a synthetic report payload and no durable library mutations.
They exercise the real admission/release path, not LibreOffice throughput.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app import monthly_report_render_jobs as jobs


_GIB = 1024 ** 3


@pytest.fixture
def two_slots(monkeypatch):
    monkeypatch.setattr(jobs, '_WORK_SLOT', jobs._ParallelWorkSlots(2))
    monkeypatch.setattr(jobs, '_WORK_CAPACITY', 2)
    monkeypatch.setattr(jobs, '_ACTIVE_WORK', 0)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 4 * _GIB)
    yield
    assert jobs._ACTIVE_WORK == 0


def test_two_independent_synthetic_reports_can_overlap_when_enabled(two_slots):
    barrier = Barrier(3)
    release = Event()
    accepted = []
    def run(report_id):
        with jobs.work_slot(wait_seconds=2):
            with jobs.work_slot(wait_seconds=0):  # A nested operation takes no second lease.
                accepted.append(report_id)
                barrier.wait(timeout=3)
                assert release.wait(3)
        return report_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(run, marker) for marker in ('site-A', 'site-B')]
        try:
            barrier.wait(timeout=3)
            assert sorted(accepted) == ['site-A', 'site-B']
            assert jobs._ACTIVE_WORK == 2
            assert jobs._WORK_SLOT.locked()  # Preserve legacy introspection.
        finally:
            release.set()
        assert sorted(result.result(timeout=5) for result in results) == ['site-A', 'site-B']
    assert not jobs._WORK_SLOT.locked()


@pytest.mark.parametrize('headroom', [None, 512 * 1024**2, 2 * _GIB - 1])
def test_second_job_rejected_under_pressure_without_losing_first(two_slots, monkeypatch, headroom):
    original = {'report': 'synthetic unchanged', 'edited': 'human edit'}
    with jobs.work_slot():
        monkeypatch.setattr(jobs, 'memory_headroom', lambda: headroom)
        with ThreadPoolExecutor(max_workers=1) as pool:
            def second():
                with jobs.work_slot(wait_seconds=0):
                    original['report'] = 'incorrect overwrite'
            with pytest.raises(jobs.RenderBusy, match='queued'):
                pool.submit(second).result(timeout=3)
        assert jobs._ACTIVE_WORK == 1
        assert original == {'report': 'synthetic unchanged', 'edited': 'human edit'}
    # A scale-down or unreadable counter must not lock out the old single job.
    with jobs.work_slot(wait_seconds=0):
        assert jobs._ACTIVE_WORK == 1


def test_baseexception_releases_parallel_lease(two_slots):
    with pytest.raises(KeyboardInterrupt):
        with jobs.work_slot():
            raise KeyboardInterrupt()
    assert jobs._ACTIVE_WORK == 0
    assert not jobs._WORK_SLOT.locked()
    with jobs.work_slot(wait_seconds=0):
        pass


@pytest.mark.skipif(os.name == 'nt', reason='POSIX file-lock crash recovery')
def test_killed_conversion_owner_releases_persistent_lock(tmp_path, monkeypatch):
    """An OS-killed worker never leaves a durable conversion lease behind."""
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    code = (
        'import time\n'
        'from app.monthly_report_render_jobs import conversion_slot\n'
        'with conversion_slot(wait_seconds=3):\n'
        '    print("lease-acquired", flush=True)\n'
        '    time.sleep(30)\n'
    )
    env = dict(os.environ, EPC_DATA_DIR=str(tmp_path))
    child = subprocess.Popen([sys.executable, '-c', code], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'lease-acquired'
    finally:
        child.kill()
        child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()
    with jobs.conversion_slot(wait_seconds=3):
        assert (Path(tmp_path) / 'monthly_reports' / 'render-jobs' / '.conversion-lock').is_file()
