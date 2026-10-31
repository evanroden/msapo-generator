"""Preview pressure yields its owned converter, never a user's original/state."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

import pytest

from app import monthly_report_render_jobs as jobs
from app import office_process as office
from conftest import requires_libreoffice

MIB = 1024 * 1024
HIGH = jobs.PREVIEW_HEADROOM_BYTES + 64 * MIB


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: HIGH)


def test_pressure_after_admission_refuses_before_launch(monkeypatch):
    with jobs.work_slot(preview=True), jobs.conversion_slot(wait_seconds=0):
        monkeypatch.setattr(jobs, 'memory_headroom', lambda: 0)
        monkeypatch.setattr(office.subprocess, 'Popen', lambda *a, **k: pytest.fail('pressure must refuse before Popen'))
        with pytest.raises(jobs.RenderBusy, match='queued'):
            office.run_office([sys.executable, '-c', 'pass'])
    assert not jobs._WORK_SLOT.locked() and not jobs._SLOT.locked()


@pytest.mark.parametrize('preview', [False, None])
def test_foreground_and_default_keep_original_wait_and_no_memory_reads(monkeypatch, preview):
    calls = []
    class Process:
        pid = 123456
        returncode = 0
        def wait(self, *, timeout): calls.append(timeout)
    monkeypatch.setattr(office.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(office, '_record', lambda _: None)
    monkeypatch.setattr(office, '_stop', lambda _: None)
    monkeypatch.setattr(office, '_clear', lambda _: None)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: pytest.fail('foreground must not consult preview pressure'))
    from contextlib import nullcontext
    with jobs.work_slot() if preview is False else nullcontext():
        result = office.run_office(['synthetic-default'], timeout=7.25)
    assert result.returncode == 0 and calls == [7.25]


def test_guard_is_exact_lease_nested_foreground_cannot_drop_it():
    with jobs.work_slot(preview=True):
        guard = jobs.preview_memory_guard()
        assert guard is not None
        with jobs.work_slot():
            assert jobs.preview_memory_guard() is guard
        guard()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(jobs.RenderBusy, match='lease'):
                pool.submit(guard).result()
            assert pool.submit(jobs.preview_memory_guard).result() is None
    assert jobs.preview_memory_guard() is None
    with jobs.work_slot(preview=True):
        assert jobs.preview_memory_guard() is not guard
        with pytest.raises(jobs.RenderBusy, match='lease'):
            guard()


@pytest.mark.parametrize('state', ['unavailable', 'unsupported'])
def test_finite_lease_cannot_silently_lose_counters(monkeypatch, state):
    with jobs.work_slot(preview=True):
        guard = jobs.preview_memory_guard()
        monkeypatch.setattr(jobs, 'memory_headroom', lambda: None)
        monkeypatch.setattr(jobs, '_memory_status', lambda: (state, None))
        with pytest.raises(jobs.RenderBusy, match='checked'):
            guard()


@pytest.mark.parametrize('state', ['unsupported', 'unlimited'])
def test_original_unknown_or_unlimited_platform_semantics(monkeypatch, state):
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: None)
    monkeypatch.setattr(jobs, '_memory_status', lambda: (state, None))
    with jobs.work_slot(preview=True):
        jobs.preview_memory_guard()()
        monkeypatch.setattr(jobs, 'memory_headroom', lambda: 0)
        with pytest.raises(jobs.RenderBusy, match='queued'):
            jobs.preview_memory_guard()()


def test_unlimited_is_not_a_read_failure_after_finite_admission(monkeypatch):
    with jobs.work_slot(preview=True):
        monkeypatch.setattr(jobs, 'memory_headroom', lambda: None)
        monkeypatch.setattr(jobs, '_memory_status', lambda: ('unlimited', None))
        jobs.preview_memory_guard()()
        monkeypatch.setattr(jobs, '_memory_status', lambda: ('unavailable', None))
        with pytest.raises(jobs.RenderBusy, match='checked'):
            jobs.preview_memory_guard()()


def test_initial_counter_error_is_not_unsupported_platform(monkeypatch):
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: None)
    monkeypatch.setattr(jobs, '_memory_status', lambda: ('unavailable', None))
    with pytest.raises(jobs.RenderBusy, match='checked'):
        with jobs.work_slot(preview=True):
            jobs.preview_memory_guard()()


@pytest.mark.parametrize('files,expected', [
    ({}, ('unsupported', None)),
    ({'memory.max': 'max'}, ('unlimited', None)),
    ({'memory.max': '536870912', 'memory.current': '104857600'}, ('finite', 432013312)),
    ({'memory.max': '536870912', 'memory.current': '999999999'}, ('finite', 0)),
    ({'memory.max': '536870912'}, ('unavailable', None)),
    ({'memory.max': 'bad'}, ('unavailable', None)),
    ({'memory.max': '536870912', 'memory.current': '-1'}, ('unavailable', None)),
    ({'memory.limit_in_bytes': str(1 << 62)}, ('unlimited', None)),
    ({'memory.limit_in_bytes': '200', 'memory.usage_in_bytes': '120'}, ('finite', 80)),
    ({'memory.max': PermissionError()}, ('unavailable', None)),
])
def test_counter_state_distinguishes_unlimited_missing_and_broken(monkeypatch, files, expected):
    def read(path, *a, **kw):
        value = files.get(path.name, FileNotFoundError())
        if isinstance(value, Exception): raise value
        return value
    monkeypatch.setattr(Path, 'read_text', read)
    assert jobs._memory_status() == expected


def test_guarded_wait_uses_one_deadline_and_exact_timeout(monkeypatch):
    clock = [10.0]
    waits = []
    class Process:
        pid = 123456
        returncode = None
        def wait(self, *, timeout):
            waits.append(timeout); clock[0] += timeout
            raise subprocess.TimeoutExpired('synthetic', timeout)
    monkeypatch.setattr(office.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(office.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(office, '_record', lambda _: None)
    stopped = []
    monkeypatch.setattr(office, '_stop', lambda p: stopped.append(p.pid))
    monkeypatch.setattr(office, '_clear', lambda _: None)
    with jobs.work_slot(preview=True), jobs.conversion_slot(wait_seconds=0):
        with pytest.raises(subprocess.TimeoutExpired) as error:
            office.run_office(['synthetic'], timeout=.12)
    assert error.value.timeout == .12
    assert len(waits) >= 2 and max(waits) <= .05
    assert sum(waits) == pytest.approx(.12) and stopped == [123456]


def test_pressure_cleanup_failure_keeps_quarantine_and_blocks_next_conversion(monkeypatch):
    class Process:
        pid = 123456
        returncode = None
        def wait(self, *, timeout):
            monkeypatch.setattr(jobs, 'memory_headroom', lambda: 0)
            raise subprocess.TimeoutExpired('synthetic', timeout)
    monkeypatch.setattr(office.subprocess, 'Popen', lambda *a, **k: Process())
    def fail_cleanup(_): raise office.OfficeCleanupPending('Synthetic owned group still running')
    monkeypatch.setattr(office, '_stop', fail_cleanup)
    with jobs.work_slot(preview=True), jobs.conversion_slot(wait_seconds=0):
        with pytest.raises(office.OfficeCleanupPending):
            office.run_office(['synthetic'])
    assert office._marker().exists()
    monkeypatch.setattr(office, '_group_running', lambda _: True)
    with pytest.raises(jobs.RenderBusy, match='still stopping'):
        with jobs.conversion_slot(wait_seconds=0):
            pytest.fail('quarantined process must prevent next launch')


def test_real_allocating_child_is_preempted_reaped_and_never_publishes(monkeypatch, tmp_path):
    ledger = tmp_path / 'pids'; completed = tmp_path / 'completed'
    script = tmp_path / 'allocator.py'
    script.write_text('''import os,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(10)'])
ledger=Path(sys.argv[1]); temporary=ledger.with_suffix('.pending')
temporary.write_text(str(os.getpid())+' '+str(child.pid)); temporary.replace(ledger)
buffer=bytearray(24*1024*1024)
for n in range(0,len(buffer),4096):buffer[n]=1
time.sleep(1.5)
Path(sys.argv[2]).write_text('finished-without-preemption')
''')
    sampled = []
    def headroom():
        if not ledger.exists(): return HIGH
        pid = int(ledger.read_text().split()[0])
        try:
            status = Path(f'/proc/{pid}/status').read_text()
            rss = int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmRSS:'))) * 1024
        except (FileNotFoundError, StopIteration): return HIGH
        sampled.append(rss)
        # Controlled budget derives from REAL child allocation, not a claimed
        # local cgroup. Baseline never consults it after launching the process.
        return jobs.PREVIEW_HEADROOM_BYTES + 24*MIB - rss
    monkeypatch.setattr(jobs, 'memory_headroom', headroom)
    cleanup = office._stop; order = []
    def stop(process):
        assert jobs._SLOT.locked() and jobs._WORK_SLOT.locked()
        cleanup(process)
        assert not office._group_running(process.pid)
        order.append('reaped-while-leased')
    monkeypatch.setattr(office, '_stop', stop)
    with jobs.work_slot(preview=True), jobs.conversion_slot(wait_seconds=0):
        with pytest.raises(jobs.RenderBusy, match='queued'):
            office.run_office([sys.executable, str(script), str(ledger), str(completed)], timeout=5)
    assert max(sampled) > 24*MIB and order == ['reaped-while-leased']
    assert not completed.exists() and not office._marker().exists()
    for pid in map(int, ledger.read_text().split()):
        try:
            state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
        except FileNotFoundError:
            state = 'gone'
        assert state in {'gone', 'Z', 'X'}
    with jobs.conversion_slot(wait_seconds=0):
        pass


@pytest.mark.parametrize('reason', ['pressure', 'counter-error'])
def test_completion_does_not_hide_failed_lifetime_guard(monkeypatch, reason):
    class Process:
        pid = 123456
        returncode = 0
        def wait(self, *, timeout):
            monkeypatch.setattr(jobs, 'memory_headroom', lambda: 0 if reason == 'pressure' else None)
            monkeypatch.setattr(jobs, '_memory_status', lambda: ('unavailable', None))
    monkeypatch.setattr(office.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(office, '_record', lambda _: None)
    events = []
    monkeypatch.setattr(office, '_stop', lambda _: events.append('stop'))
    monkeypatch.setattr(office, '_clear', lambda _: events.append('clear'))
    with jobs.work_slot(preview=True):
        with pytest.raises(jobs.RenderBusy):
            office.run_office(['synthetic'])
    assert events == ['stop', 'clear']


def test_original_wait_failure_is_not_masked_by_guard(monkeypatch):
    original = ValueError('Synthetic original process failure')
    class Process:
        pid = 123456
        returncode = None
        def wait(self, *, timeout): raise original
    monkeypatch.setattr(office.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(office, '_record', lambda _: None)
    events = []
    monkeypatch.setattr(office, '_stop', lambda _: events.append('stop'))
    monkeypatch.setattr(office, '_clear', lambda _: events.append('clear'))
    with jobs.work_slot(preview=True):
        with pytest.raises(ValueError) as error:
            office.run_office(['synthetic'])
    assert error.value is original and events == ['stop', 'clear']


@pytest.mark.parametrize('visible,current', [(True, True), (False, True), (True, False)])
def test_actual_busy_route_retains_last_good_and_requeues_only_current_visible_owner(monkeypatch, visible, current):
    from concurrent.futures import Future
    from threading import BoundedSemaphore
    from app import monthly_report_section_preview_ui as ui
    from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    fingerprint = draft.fingerprint
    assets = {'original': b'immutable-original'}
    class Process:
        pid = 123456
        returncode = None
        def wait(self, *, timeout):
            monkeypatch.setattr(jobs, 'memory_headroom', lambda: 0)
            raise subprocess.TimeoutExpired('synthetic', timeout)
    monkeypatch.setattr(office.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(office, '_record', lambda _: None)
    monkeypatch.setattr(office, '_stop', lambda _: None)
    monkeypatch.setattr(office, '_clear', lambda _: None)
    def preview(*a, **kw):
        with jobs.work_slot(preview=True), jobs.conversion_slot(wait_seconds=0):
            office.run_office(['synthetic'])
        pytest.fail('pressure must not return a publishable preview')
    monkeypatch.setattr(ui, 'preview_section', preview)
    slot = BoundedSemaphore(1); assert slot.acquire(False)
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', slot)
    result = ui._build_preview_entry(draft, 'cover', assets, 'Cover', 'current-owner')
    assert result == {'busy': True} and slot.acquire(False)
    slot.release()
    future = Future(); future.set_result(result)
    last_good = {'fingerprint': 'last-good', 'pages': 1}
    request = (fingerprint, draft, assets, 'Cover')
    state = {'owner': 'current-owner', 'wanted': {'cover': fingerprint if current else 'new-owner-fingerprint'},
             'visible': {'cover': visible}, 'queue': {}, 'cache': {'cover': last_good},
             'last_good': {'cover': last_good}, 'running': ('cover', fingerprint, future),
             'running_request': request}
    monkeypatch.setattr(ui, 'monotonic', lambda: 10)
    ui._advance_preview_queue(state)
    assert state['cache']['cover'] is last_good and state['last_good']['cover'] is last_good
    assert state['queue'] == ({'cover': request} if current and visible else {})
    assert state['owner'] == 'current-owner' and state['running'] is None
    assert draft.fingerprint == fingerprint and assets == {'original': b'immutable-original'}


@requires_libreoffice
def test_real_writer_can_finish_with_healthy_preview_lease(monkeypatch, tmp_path):
    from docx import Document
    import pymupdf
    from app import pdf_converter
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    monkeypatch.setattr(pdf_converter, 'PDF_BACKEND', 'libreoffice')
    source = tmp_path / 'healthy-preview.docx'
    document = Document(); document.add_paragraph('Synthetic healthy preview lease.'); document.save(source)
    original = source.read_bytes()
    with jobs.work_slot(preview=True):
        result = pdf_converter.convert_to_pdf(source)
    with pymupdf.open(result) as pdf:
        assert len(pdf) == 1 and 'Synthetic healthy preview lease.' in pdf[0].get_text()
    assert source.read_bytes() == original and not office._marker().exists()
    assert not jobs._SLOT.locked() and not jobs._WORK_SLOT.locked()
