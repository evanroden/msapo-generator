"""A23 synthetic two-session LibreOffice admission and owned-output regressions.

No client files, shared report state or network services are used here.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Event
import time

from docx import Document
import pytest

from app import monthly_report_render_jobs as jobs
from app import office_conversion_admission as admission
from app import office_process
from app import pdf_converter as converter
from conftest import requires_libreoffice


def _runtime(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    folder = tmp_path / 'outputs'
    folder.mkdir()
    monkeypatch.setattr(converter, 'OUTPUT_DIR', folder)
    monkeypatch.setattr(converter, 'PDF_BACKEND', 'libreoffice')
    return folder


def _source(tmp_path, owner='site-A', name='report'):
    directory = tmp_path / owner
    directory.mkdir()
    path = directory / (name + '.docx')
    doc = Document()
    doc.add_paragraph('Synthetic source for ' + owner)
    doc.save(path)
    return path


@pytest.mark.parametrize('setting,quotas,expected', [
    (None, (4, 4 * admission.GIB), False),
    ('1', (.5, 512 * admission.MIB), False),
    ('1', (1, 2 * admission.GIB), False),
    ('1', (2, 2 * admission.GIB), False),
    ('1', (2, 4 * admission.GIB), True),
    ('0', (4, 8 * admission.GIB), False),
    ('broken', (4, 8 * admission.GIB), False),
    ('1', None, False),
])
def test_opt_in_requires_finite_cpu_and_memory(monkeypatch, setting, quotas, expected):
    if setting is None:
        monkeypatch.delenv('MSAPO_OFFICE_PARALLEL', raising=False)
    else:
        monkeypatch.setenv('MSAPO_OFFICE_PARALLEL', setting)
    monkeypatch.setattr(admission, '_limits', lambda: quotas)
    monkeypatch.setattr(admission.os, 'sched_getaffinity', lambda _: {0, 1, 2, 3})
    assert admission.parallel_enabled() is expected if sys.platform == 'linux' else not admission.parallel_enabled()


def test_512mb_half_cpu_stays_single_slot_even_when_flag_enabled(monkeypatch, tmp_path):
    _runtime(monkeypatch, tmp_path)
    monkeypatch.setenv('MSAPO_OFFICE_PARALLEL', '1')
    monkeypatch.setattr(admission, '_limits', lambda: (.5, 512 * admission.MIB))
    started, release = Event(), Event()
    def first():
        with jobs.conversion_slot(wait_seconds=2):
            started.set()
            assert release.wait(3)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first)
        assert started.wait(2)
        with pytest.raises(jobs.RenderBusy, match='Another report is rendering'):
            with jobs.conversion_slot(wait_seconds=0):
                pass
        release.set()
        future.result(timeout=4)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux shared file-flock lanes')
def test_two_independent_sessions_enter_and_release_private_lanes(monkeypatch, tmp_path):
    output = _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(admission, 'parallel_enabled', lambda: True)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 3 * admission.GIB)
    entered = Event()
    release = Event()
    leases = {}
    def run(name):
        with jobs.conversion_slot(wait_seconds=2):
            leases[name] = (office_process._marker().name,
                            getattr(office_process._OFFICE_MARKER_LOCAL, 'slot'))
            if len(leases) == 2:
                entered.set()
            assert release.wait(3)
        return name
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(run, 'site-A')
        b = pool.submit(run, 'site-B')
        try:
            assert entered.wait(2), 'second session was blocked by the former global mutex'
            assert {lane for _, lane in leases.values()} == {0, 1}
            assert len({marker for marker, _ in leases.values()}) == 2
        finally:
            release.set()
        assert {a.result(4), b.result(4)} == {'site-A', 'site-B'}
    with jobs.conversion_slot(wait_seconds=0):
        pass
    assert not list(output.glob('.office-*'))
    assert not list((tmp_path / 'runtime').rglob('.active-office*.json'))


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux shared file-flock lanes')
def test_second_lane_requires_live_headroom_and_queues_behind_slow(monkeypatch, tmp_path):
    _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(admission, 'parallel_enabled', lambda: True)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: admission.SECOND_LANE_HEADROOM - 1)
    entered, release = Event(), Event()
    def slow():
        with jobs.conversion_slot(wait_seconds=3):
            entered.set()
            assert release.wait(3)
    with ThreadPoolExecutor(max_workers=1) as pool:
        held = pool.submit(slow)
        assert entered.wait(2)
        with pytest.raises(jobs.RenderBusy):
            with jobs.conversion_slot(wait_seconds=.07):
                pytest.fail('second lane admitted with insufficient headroom')
        release.set()
        held.result(timeout=4)
    with jobs.conversion_slot(wait_seconds=0):
        pass


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux shared file-flock lanes')
def test_single_slot_fallback_waits_for_both_parallel_lanes(monkeypatch, tmp_path):
    _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 3 * admission.GIB)
    monkeypatch.setattr(admission, 'parallel_enabled', lambda: True)
    entered, release = Event(), Event()
    def parallel_worker():
        with jobs.conversion_slot(wait_seconds=2):
            entered.set()
            assert release.wait(4)
    with ThreadPoolExecutor(max_workers=1) as pool:
        held = pool.submit(parallel_worker)
        assert entered.wait(2)
        monkeypatch.setattr(admission, 'parallel_enabled', lambda: False)
        with pytest.raises(jobs.RenderBusy):
            with jobs.conversion_slot(wait_seconds=.05):
                pytest.fail('legacy worker bypassed parallel-mode barrier')
        release.set()
        held.result(timeout=4)
    with jobs.conversion_slot(wait_seconds=0):
        pass


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux shared file-flock lanes')
def test_failure_and_cancellation_leave_no_lane_or_marker(monkeypatch, tmp_path):
    _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(admission, 'parallel_enabled', lambda: True)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 3 * admission.GIB)
    for error in (ValueError('synthetic failure'), KeyboardInterrupt()):
        with pytest.raises(type(error)):
            with jobs.conversion_slot(wait_seconds=0):
                raise error
        with jobs.conversion_slot(wait_seconds=0):
            pass
    assert not list((tmp_path / 'runtime').rglob('.active-office*.json'))


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux process groups and marker recovery')
def test_serial_restart_quarantines_orphaned_second_lane_only(monkeypatch, tmp_path):
    _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(admission, 'parallel_enabled', lambda: False)
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)'],
                               start_new_session=True)
    marker = tmp_path / 'runtime' / 'monthly_reports' / 'render-jobs' / '.active-office-1.json'
    marker.parent.mkdir(parents=True, exist_ok=True)
    import json
    marker.write_text(json.dumps({'pid': process.pid, 'boot': office_process._boot_id()}))
    try:
        with pytest.raises(jobs.RenderBusy, match='still stopping'):
            with jobs.conversion_slot(wait_seconds=0):
                pytest.fail('orphan from lane 1 was ignored on serial restart')
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
    with jobs.conversion_slot(wait_seconds=0):
        assert not marker.exists()


@requires_libreoffice
def test_real_parallel_writer_keeps_owner_bytes_and_page_geometry(monkeypatch, tmp_path):
    import pymupdf
    output = _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(admission, 'parallel_enabled', lambda: True)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 3 * admission.GIB)
    left = _source(tmp_path, 'site-A')
    right = _source(tmp_path, 'site-B')
    originals = {p: sha256(p.read_bytes()).hexdigest() for p in (left, right)}
    def run(path):
        result = converter.convert_to_pdf(path)
        data = result.read_bytes()
        with pymupdf.open(stream=data, filetype='pdf') as doc:
            return result, data, [(round(p.rect.width), round(p.rect.height),
                                   p.get_text()) for p in doc]
    with ThreadPoolExecutor(max_workers=2) as pool:
        (l, lb, lp), (r, rb, rp) = list(pool.map(run, (left, right)))
    try:
        assert l != r and l.parent == r.parent == output
        assert lb.startswith(b'%PDF-') and rb.startswith(b'%PDF-')
        assert lp[0][:2] == rp[0][:2] == (612, 792)
        assert 'site-A' in lp[0][2] and 'site-B' not in lp[0][2]
        assert 'site-B' in rp[0][2] and 'site-A' not in rp[0][2]
        assert all(sha256(p.read_bytes()).hexdigest() == digest
                   for p, digest in originals.items())
        assert not list(output.glob('.office-*'))
        assert not list((tmp_path / 'runtime').rglob('.active-office*.json'))
    finally:
        l.unlink(missing_ok=True)
        r.unlink(missing_ok=True)


def test_restart_reaps_only_old_private_profiles(monkeypatch, tmp_path):
    output = _runtime(monkeypatch, tmp_path)
    ancient = output / '.office-old-orphan'
    recent = output / '.office-live-current'
    unrelated = output / 'user-source.docx'
    finished = output / 'completed.pdf'
    for directory in (ancient, recent):
        directory.mkdir()
        (directory / 'profile').mkdir()
        (directory / 'profile' / 'settings').write_text('synthetic')
    unrelated.write_bytes(b'untouched input')
    finished.write_bytes(b'%PDF-1.7 existing')
    old_time = time.time() - 900
    os.utime(ancient, (old_time, old_time))
    assert admission.prune_orphaned_profiles(output, old_seconds=600) == 1
    assert not ancient.exists()
    assert recent.exists()
    assert unrelated.read_bytes() == b'untouched input'
    assert finished.read_bytes() == b'%PDF-1.7 existing'


def test_restart_does_not_sweep_while_other_owned_office_is_running(monkeypatch, tmp_path):
    output = _runtime(monkeypatch, tmp_path)
    old = output / '.office-old-orphan'
    old.mkdir()
    old_time = time.time() - 900
    os.utime(old, (old_time, old_time))
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'],
                               start_new_session=(os.name == 'posix'))
    marker = office_process._marker()
    marker.parent.mkdir(parents=True, exist_ok=True)
    import json
    marker.write_text(json.dumps({'pid': process.pid, 'boot': office_process._boot_id()}))
    try:
        assert admission.prune_orphaned_profiles(output) == 0
        assert old.exists()
    finally:
        process.kill()
        process.wait(timeout=3)
    assert admission.prune_orphaned_profiles(output) == 1
    assert not old.exists()


@requires_libreoffice
def test_identical_input_parallel_matches_serial_rendered_page_bytes(monkeypatch, tmp_path):
    """Raw PDF metadata can vary; rendered pixels and document bytes cannot."""
    import pymupdf
    output = _runtime(monkeypatch, tmp_path)
    original = _source(tmp_path, owner='same-owner')
    original_hash = sha256(original.read_bytes()).hexdigest()
    monkeypatch.setattr(admission, 'parallel_enabled', lambda: False)
    baseline = converter.convert_to_pdf(original)
    monkeypatch.setattr(admission, 'parallel_enabled', lambda: True)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 3 * admission.GIB)
    saved_pids = []
    previous_record = office_process._record
    def capture(pid):
        saved_pids.append(pid)
        previous_record(pid)
    monkeypatch.setattr(office_process, '_record', capture)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(converter.convert_to_pdf, (original, original)))
    def page_bytes(path):
        with pymupdf.open(path) as pdf:
            return [(round(page.rect.width), round(page.rect.height),
                     sha256(page.get_pixmap(alpha=False).samples).hexdigest(),
                     page.get_text()) for page in pdf]
    try:
        assert len({baseline, first, second}) == 3
        assert page_bytes(baseline) == page_bytes(first) == page_bytes(second)
        assert sha256(original.read_bytes()).hexdigest() == original_hash
        assert saved_pids and all(not office_process._group_running(pid) for pid in saved_pids)
        assert not list(output.glob('.office-*'))
        assert not list((tmp_path / 'runtime').rglob('.active-office*.json'))
    finally:
        for path in (baseline, first, second):
            path.unlink(missing_ok=True)


def test_missing_and_malformed_inputs_never_publish_an_old_pdf(monkeypatch, tmp_path):
    output = _runtime(monkeypatch, tmp_path)
    old = output / 'missing.pdf'
    old.write_bytes(b'%PDF-1.7 old output')
    missing = tmp_path / 'missing.docx'
    with pytest.raises(converter.PDFConversionError):
        converter.convert_to_pdf(missing)
    malformed = tmp_path / 'malformed.docx'
    # A truncated OOXML (ZIP) package. Plain text renamed to .docx is not a
    # malformed package: Writer's text-import fallback renders it.
    malformed.write_bytes(b'PK\x03\x04 truncated OOXML package')
    with pytest.raises(converter.PDFConversionError):
        converter.convert_to_pdf(malformed)
    assert old.read_bytes() == b'%PDF-1.7 old output'
    assert not list(output.glob('.office-*'))
