"""An admitted background preview may use its own headroom while it runs.

Admission needs PREVIEW_HEADROOM_BYTES free. The conversion it admits then
uses part of that room, so the running child is judged against the lower
PREVIEW_RUNNING_FLOOR_BYTES. With one threshold for both, a preview admitted
with just over 160 MiB free stopped itself as soon as LibreOffice started,
requeued, and stopped again for as long as memory stayed there (the capped
512 MiB native-browser check waited 120 s on "Updating preview…").
"""
from pathlib import Path
import sys

import pytest

from app import monthly_report_render_jobs as jobs
from app import office_process as office

MIB = 1024 * 1024
HIGH = jobs.PREVIEW_HEADROOM_BYTES + 64 * MIB

ALLOCATOR = '''import os,sys,time
from pathlib import Path
ledger=Path(sys.argv[1]); temporary=ledger.with_suffix('.pending')
temporary.write_text(str(os.getpid())); temporary.replace(ledger)
buffer=bytearray(24*1024*1024)
for n in range(0,len(buffer),4096):buffer[n]=1
time.sleep(1.0)
Path(sys.argv[2]).write_text('finished')
'''


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: HIGH)


def _rss(ledger):
    if not ledger.exists():
        return None
    try:
        status = Path(f'/proc/{int(ledger.read_text())}/status').read_text()
        return int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmRSS:'))) * 1024
    except (FileNotFoundError, StopIteration, ValueError):
        return None


def _run_allocator(monkeypatch, tmp_path, margin):
    """Admit with the full headroom, then let the child's REAL RSS spend it."""
    ledger, completed = tmp_path / 'pid', tmp_path / 'completed'
    script = tmp_path / 'allocator.py'
    script.write_text(ALLOCATOR)
    sampled = []

    def headroom():
        rss = _rss(ledger)
        if rss is None:
            return jobs.PREVIEW_HEADROOM_BYTES + margin
        sampled.append(rss)
        return jobs.PREVIEW_HEADROOM_BYTES + margin - rss

    monkeypatch.setattr(jobs, 'memory_headroom', headroom)
    with jobs.work_slot(preview=True), jobs.conversion_slot(wait_seconds=0):
        result = office.run_office([sys.executable, str(script), str(ledger), str(completed)], timeout=10)
    return result, completed, sampled


@pytest.mark.skipif(sys.platform != 'linux', reason='reads the real child RSS from /proc')
def test_admitted_preview_finishes_while_its_own_child_uses_the_admission_headroom(monkeypatch, tmp_path):
    # Admitted with 8 MiB to spare; the child's ~24 MiB (plus interpreter)
    # takes free memory below PREVIEW_HEADROOM_BYTES but far above the floor.
    result, completed, sampled = _run_allocator(monkeypatch, tmp_path, 8 * MIB)
    assert result.returncode == 0 and completed.read_text() == 'finished'
    lowest = jobs.PREVIEW_HEADROOM_BYTES + 8 * MIB - max(sampled)
    assert jobs.PREVIEW_RUNNING_FLOOR_BYTES < lowest < jobs.PREVIEW_HEADROOM_BYTES
    assert not office._marker().exists()
    assert not jobs._SLOT.locked() and not jobs._WORK_SLOT.locked()


def test_launch_still_needs_the_full_admission_headroom(monkeypatch):
    # Between the floor and the admission headroom: nothing is launched.
    with jobs.work_slot(preview=True), jobs.conversion_slot(wait_seconds=0):
        monkeypatch.setattr(jobs, 'memory_headroom', lambda: jobs.PREVIEW_RUNNING_FLOOR_BYTES + 32 * MIB)
        monkeypatch.setattr(office.subprocess, 'Popen', lambda *a, **k: pytest.fail('must refuse before Popen'))
        with pytest.raises(jobs.RenderBusy, match='queued'):
            office.run_office([sys.executable, '-c', 'pass'])
    assert not jobs._WORK_SLOT.locked() and not jobs._SLOT.locked()


@pytest.mark.parametrize('headroom, running, refused', [
    (jobs.PREVIEW_HEADROOM_BYTES - 1, False, True),
    (jobs.PREVIEW_HEADROOM_BYTES - 1, True, False),
    (jobs.PREVIEW_RUNNING_FLOOR_BYTES, True, False),
    (jobs.PREVIEW_RUNNING_FLOOR_BYTES - 1, True, True),
])
def test_single_worker_thresholds(monkeypatch, headroom, running, refused):
    monkeypatch.setattr(jobs, '_WORK_CAPACITY', 1)
    jobs._WORK_LOCAL.active = True
    guard = jobs._PreviewMemoryGuard(jobs.PREVIEW_HEADROOM_BYTES)
    jobs._WORK_LOCAL.preview_guard = guard
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: headroom)
    try:
        if refused:
            with pytest.raises(jobs.RenderBusy, match='Preview is queued'):
                guard(running=running)
        else:
            guard(running=running)
    finally:
        jobs._WORK_LOCAL.active = False
        jobs._WORK_LOCAL.preview_guard = None


@pytest.mark.parametrize('active, headroom, refused', [
    # Alone: only the floor, not its own 384 MiB estimate plus the reserve.
    (1, jobs.PREVIEW_RUNNING_FLOOR_BYTES, False),
    (1, jobs.PREVIEW_RUNNING_FLOOR_BYTES - 1, True),
    # With one other running job: the floor plus that job's estimate.
    (2, jobs.PREVIEW_RUNNING_FLOOR_BYTES + jobs.PREVIEW_JOB_ESTIMATE_BYTES, False),
    (2, jobs.PREVIEW_RUNNING_FLOOR_BYTES + jobs.PREVIEW_JOB_ESTIMATE_BYTES - 1, True),
])
def test_parallel_workers_running_floor_excludes_the_jobs_own_estimate(monkeypatch, active, headroom, refused):
    monkeypatch.setattr(jobs, '_WORK_CAPACITY', 2)
    monkeypatch.setattr(jobs, '_ACTIVE_WORK', active)
    jobs._WORK_LOCAL.active = True
    guard = jobs._PreviewMemoryGuard(jobs.PREVIEW_HEADROOM_BYTES)
    jobs._WORK_LOCAL.preview_guard = guard
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: headroom)
    try:
        if refused:
            with pytest.raises(jobs.RenderBusy, match='Preview is queued'):
                guard(running=True)
        else:
            guard(running=True)
        # Before launch the existing admission requirement is unchanged.
        monkeypatch.setattr(jobs, 'memory_headroom', lambda: jobs.required_free_bytes(active - 1) - 1)
        with pytest.raises(jobs.RenderBusy, match='Preview is queued'):
            guard()
    finally:
        jobs._WORK_LOCAL.active = False
        jobs._WORK_LOCAL.preview_guard = None
