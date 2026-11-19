"""A01 deterministic read-only latency receipt and queue controls."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import pytest

from app import monthly_report_render_jobs as jobs
from app.monthly_latency_spans import capture_spans, measure_span, record_span


def test_capture_opt_in_cannot_emit_private_identifiers():
    record_span("work_queue", 1.)
    with capture_spans() as events:
        with measure_span("source_ingest"):
            pass
        with pytest.raises(RuntimeError, match="synthetic"):
            with measure_span("source_mapping"):
                raise RuntimeError("synthetic")
        with pytest.raises(ValueError, match="Unknown"):
            record_span("customer-filename", 1)
    assert [e["result"] for e in events] == ["ok", "error"]
    assert all(set(e) == {"phase", "elapsed_ms", "result"} for e in events)
    assert "synthetic" not in str(events)
    with capture_spans() as empty:
        assert not empty


def test_sessions_cannot_share_spans():
    def run(n):
        with capture_spans() as events:
            record_span("first_raster" if n == 1 else "source_mapping", n / 10)
            return list(events)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.map(run, (1, 2))
    assert [e["phase"] for e in a] == ["first_raster"]
    assert [e["phase"] for e in b] == ["source_mapping"]


def test_work_queue_records_busy_without_changing_gate(monkeypatch):
    monkeypatch.setattr(jobs, "memory_headroom", lambda: None)
    lock = Lock()
    monkeypatch.setattr(jobs, "_WORK_SLOT", lock)
    with capture_spans() as events:
        with jobs.work_slot(preview=True, wait_seconds=0):
            pass
        assert lock.acquire(False)
        try:
            with pytest.raises(jobs.RenderBusy):
                with jobs.work_slot(preview=True, wait_seconds=0):
                    pass
        finally:
            lock.release()
    assert [e["result"] for e in events if e["phase"] == "work_queue"] == ["ok", "busy"]
    with jobs.work_slot(preview=True, wait_seconds=0):
        pass


def test_office_queue_records_timeout_and_nested_once(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    lock = Lock()
    monkeypatch.setattr(jobs, "_SLOT", lock)
    with capture_spans() as events:
        assert lock.acquire(False)
        try:
            with pytest.raises(jobs.RenderBusy):
                with jobs.conversion_slot(wait_seconds=0):
                    pass
        finally:
            lock.release()
        with jobs.conversion_slot(wait_seconds=0):
            with jobs.conversion_slot(wait_seconds=0):
                pass
    assert [e["result"] for e in events if e["phase"] == "office_thread_queue"] == ["busy", "ok"]
    assert len([e for e in events if e["phase"] == "office_process_queue"]) == 1


def test_raster_summary_small_n_has_raw_values_not_false_p95():
    from scripts.benchmark_monthly_preview_cache import distribution
    r = distribution([3., 1., 2.])
    assert r["samples_ms"] == [3., 1., 2.]
    assert r["median_ms"] == 2.
    assert "p95_ms" not in r
    assert distribution(list(range(20)))["p95_ms"] == 18
