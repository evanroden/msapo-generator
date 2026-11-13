"""Preview heap reclamation retains the existing guarded conversion policy."""
import ctypes
import os
from types import SimpleNamespace

import pytest

from app import monthly_report_render_jobs as jobs


@pytest.mark.skipif(os.name != "posix", reason="POSIX conversion lease")
def test_reclaim_only_runs_inside_a_preview_conversion_lease(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(jobs, "_root", lambda: tmp_path)
    monkeypatch.setattr("app.office_process.require_idle", lambda: None)
    monkeypatch.setattr(jobs, "_reclaim_preview_heap", lambda: calls.append("preview"))
    try:
        jobs._WORK_LOCAL.active = True
        jobs._WORK_LOCAL.preview_guard = lambda: None
        with jobs.conversion_slot(wait_seconds=0):
            pass
        assert calls == ["preview"]

        jobs._WORK_LOCAL.active = False
        jobs._WORK_LOCAL.preview_guard = None
        with jobs.conversion_slot(wait_seconds=0):
            pass
        assert calls == ["preview"], "Foreground conversion must not gain a trim requirement."
    finally:
        jobs._WORK_LOCAL.active = False
        jobs._WORK_LOCAL.preview_guard = None


@pytest.mark.skipif(os.name != "posix", reason="glibc-specific allocator hint")
def test_reclaim_uses_allocator_hint_without_changing_guard(monkeypatch):
    calls = []

    class FakeTrim:
        def __call__(self, padding):
            calls.append(padding)
            return 1

    monkeypatch.setattr(ctypes, "CDLL", lambda name: SimpleNamespace(malloc_trim=FakeTrim()))
    jobs._reclaim_preview_heap()
    assert calls == [0]

    monkeypatch.setattr(ctypes, "CDLL", lambda name: SimpleNamespace())
    jobs._reclaim_preview_heap()  # Non-glibc POSIX platforms remain supported.

    # The memory guard is unmodified: insufficient reported headroom is refused.
    monkeypatch.setattr(jobs, "memory_headroom", lambda: jobs.PREVIEW_HEADROOM_BYTES - 1)
    jobs._WORK_LOCAL.active = True
    guard = jobs._PreviewMemoryGuard(jobs.PREVIEW_HEADROOM_BYTES)
    jobs._WORK_LOCAL.preview_guard = guard
    try:
        with pytest.raises(jobs.RenderBusy, match="Preview is queued"):
            guard()
    finally:
        jobs._WORK_LOCAL.active = False
        jobs._WORK_LOCAL.preview_guard = None
