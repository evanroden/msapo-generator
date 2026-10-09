"""Low-memory admission is distinct from the reentrant office conversion gate."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import pytest

from app import monthly_report_render_jobs as jobs


def test_busy_memory_defers_preview_before_any_build(monkeypatch):
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: jobs.PREVIEW_HEADROOM_BYTES-1)
    with pytest.raises(jobs.RenderBusy, match='queued'):
        with jobs.work_slot(preview=True):
            pytest.fail('A preview must not start under memory pressure')
    # A background preview cannot permanently consume the admission slot.
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: None)
    with jobs.work_slot(preview=True):
        pass


def test_one_assembly_at_a_time_and_foreground_waiter_takes_priority(monkeypatch):
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: None)
    started, release = Event(), Event()
    def hold_preview():
        with jobs.work_slot(preview=True):
            started.set()
            assert release.wait(5)
    def foreground():
        with jobs.work_slot(wait_seconds=3):
            return 'export'
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(hold_preview)
        assert started.wait(2)
        pending = pool.submit(foreground)
        deadline = time.monotonic()+2
        while not jobs._FOREGROUND_WAITING and time.monotonic() < deadline:
            time.sleep(.01)
        with pytest.raises(jobs.RenderBusy):
            with jobs.work_slot(preview=True):
                pass
        release.set()
        first.result(3)
        assert pending.result(3) == 'export'
    assert jobs._FOREGROUND_WAITING == 0


def test_assembly_can_call_converter_without_nesting_its_lock(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: None)
    with jobs.work_slot(preview=True):
        with jobs.conversion_slot(wait_seconds=0):
            # Nested wrappers around the SAME backend call share one lease.
            with jobs.conversion_slot(wait_seconds=0):
                pass
    with jobs.conversion_slot(wait_seconds=0):
        pass


def test_nested_failure_releases_both_independent_slots(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    with pytest.raises(ValueError, match='Synthetic'):
        with jobs.work_slot():
            with jobs.conversion_slot(wait_seconds=0):
                raise ValueError('Synthetic conversion error')
    with jobs.work_slot(preview=True), jobs.conversion_slot(wait_seconds=0):
        pass


def test_docx_remains_downloadable_when_pdf_runs_out_of_resources(monkeypatch):
    from app import monthly_report_docx as module
    from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026,9))
    monkeypatch.setattr(module, 'assemble_docx', lambda *a, **kw: b'completed-docx')
    def busy(*a, **kw):
        raise jobs.RenderBusy('Synthetic converter resource pressure')
    monkeypatch.setattr(jobs, 'convert_to_pdf', busy)
    package = module.generate_report(draft)
    assert package.docx == b'completed-docx' and package.pdf is None
    assert 'DOCX is ready' in package.pdf_error
