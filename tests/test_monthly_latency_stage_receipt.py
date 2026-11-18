"""A22 synthetic attribution: ordering, no-op safety and byte preservation."""
from hashlib import sha256
import json

import pytest

from app.monthly_report_latency_trace import TimingTrace, mark, span, synthetic_timing
from app import monthly_report_sources as sources
from scripts.qa_monthly_preview_latency_e2e import _docx, _image, _pdf, _profile


def _ordered(receipt):
    stages = receipt["spans"]
    assert [item["start_ms"] for item in stages] == sorted(item["start_ms"] for item in stages)
    assert all(0 <= item["start_ms"] <= item["end_ms"] for item in stages)
    assert all(item["wall_ms"] >= 0 and item["cpu_ms"] >= 0 for item in stages)
    return stages


def test_disabled_and_exception_do_not_leak_collector():
    with span("parse"):
        mark("upload_received")
    trace = TimingTrace()
    with pytest.raises(RuntimeError, match="synthetic"):
        with synthetic_timing(trace):
            mark("upload_received")
            with span("parse"):
                raise RuntimeError("synthetic")
    events = _ordered(trace.receipt())
    assert [event["stage"] for event in events] == ["upload_received", "parse"]
    with span("conversion"):
        pass
    assert len(trace.receipt()["spans"]) == 2
    with pytest.raises(ValueError, match="Unsupported timing stage"):
        with synthetic_timing(TimingTrace()):
            mark("filename-or-sensitive-value")


@pytest.mark.parametrize("suffix,raw", [(".pdf", _pdf(2)), (".docx", _docx(1))])
def test_cold_warm_stage_order_and_immutable_original(tmp_path, monkeypatch, suffix, raw):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    assert sha256(raw).digest()  # Work only with synthetic, immutable bytes.
    source_hash = sha256(raw).hexdigest()
    profile = _profile("qa-a22-origin")
    captures = []
    images = []
    for _ in range(2):
        trace = TimingTrace()
        with synthetic_timing(trace):
            content, extras = sources.ingest(profile, "synthetic" + suffix, raw)
            picture = _image(profile, content)
        assert extras == ()
        assert content.source.sha256 == source_hash
        assert sources._path(profile, source_hash, suffix).read_bytes() == raw
        captures.append(_ordered(trace.receipt()))
        images.append(picture)
        # No literal filenames, bytes or site identifiers permitted in receipt.
        text = json.dumps(trace.receipt())
        assert "synthetic.pdf" not in text and "synthetic.docx" not in text
        assert profile.key not in text
    assert images[0] == images[1]
    assert [event["stage"] for event in captures[0] if event["point"]] == ["upload_received"]
    assert [event["stage"] for event in captures[1] if event["point"]] == ["upload_received"]
    for events in captures:
        names = [event["stage"] for event in events]
        assert "hash_cache_lookup" in names
        assert "optional_visual_read" in names
        assert names.index("hash_cache_lookup") < names.index("optional_visual_read")
    assert "parse" in [event["stage"] for event in captures[0]]
    assert "parse" not in [event["stage"] for event in captures[1]]
    assert source_hash == sha256(raw).hexdigest()


def test_bad_source_and_cross_profile_have_no_data_leak(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = _profile("qa-a22-one")
    other = _profile("qa-a22-other")
    original = _pdf(2)
    for name, raw, error in [("bad.exe", b"x", "Unsupported"),
                             ("empty.pdf", b"", "empty"),
                             ("bad.pdf", b"not a PDF", None)]:
        trace = TimingTrace()
        with synthetic_timing(trace):
            with pytest.raises(Exception) as caught:
                sources.ingest(profile, name, raw)
        if error:
            assert error.lower() in str(caught.value).lower()
        _ordered(trace.receipt())
    first, _ = sources.ingest(profile, "same.pdf", original)
    second, _ = sources.ingest(other, "same.pdf", original)
    assert first.source.sha256 == second.source.sha256 == sha256(original).hexdigest()
    assert _image(profile, first) == _image(other, second)

def test_cooperative_capacity_retry_records_wait_and_cancels_stale_job(monkeypatch):
    from app.monthly_report_read_wait import read_with_capacity_wait
    from app.monthly_report_render_jobs import RenderBusy

    attempts = []
    checkpoints = []
    waiting = []
    monkeypatch.setattr("app.monthly_report_read_wait.sleep", lambda _: None)

    def read():
        attempts.append(1)
        if len(attempts) == 1:
            raise RenderBusy("Synthetic queue contention")
        return "immutable result"

    trace = TimingTrace()
    with synthetic_timing(trace):
        value = read_with_capacity_wait(read, lambda: checkpoints.append(1),
                                        lambda: waiting.append(1), wait_seconds=1)
    assert value == "immutable result"
    assert len(attempts) == len(checkpoints) == 2
    assert len(waiting) == 1
    assert "job_queue" in [entry["stage"] for entry in _ordered(trace.receipt())]

    def canceled():
        raise RuntimeError("Stale request canceled")

    with pytest.raises(RuntimeError, match="Stale"):
        read_with_capacity_wait(lambda: pytest.fail("Canceled read must not run"),
                                canceled, lambda: None)
