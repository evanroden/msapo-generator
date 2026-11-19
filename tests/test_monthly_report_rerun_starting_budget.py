"""A05: an active Monthly editor must not re-import its starting report on every key.

Synthetic site/month only.  Streamlit AppTest measures native widget state and
actual reader calls, not browser first paint or real-source acceptance.
Refs #270, #491, #303.
"""
from pathlib import Path
from time import perf_counter, process_time
import json

from streamlit.testing.v1 import AppTest

from app import monthly_report_start as start
from app.contracts import RRH_CONTRACT
from app.monthly_report_model import synthetic_profiles
from test_monthly_report_ui import ROOT, choose_report, monthly


def test_ten_preparer_edits_do_not_repeat_cold_starting_evidence_read(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    original = start.read_starting_state
    reads = []

    def counted(contract, key, period):
        reads.append((contract, key, period.key))
        return original(contract, key, period)

    monkeypatch.setattr(start, "read_starting_state", counted)
    initial = next(w for w in app.text_input if w.label == "Prepared by")
    native_key = initial.key
    metrics = []
    try:
        for index in range(10):
            updated = f"Synthetic A05 editor {index}"
            t0, c0 = perf_counter(), process_time()
            next(w for w in app.text_input if w.label == "Prepared by").set_value(updated).run()
            metrics.append({"wall_s": round(perf_counter() - t0, 6),
                            "cpu_s": round(process_time() - c0, 6)})
            assert not app.exception and not app.error
            current = next(w for w in app.text_input if w.label == "Prepared by")
            assert current.value == updated
            assert current.key == native_key, "Unchanged report must not remount the native input"
            assert app.session_state["report_draft_mirror"].get(native_key) == updated
        assert not reads, "A warm editing rerun must not re-verify the starting selection"
    finally:
        # Both a failing-before run and a passing-after run retain an explicit
        # machine-readable synthetic observation without using client files.
        path = Path("test-artifacts/independent-synthetic/a05_monthly_warm_rerun.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"synthetic": True, "method": "Streamlit AppTest",
            "edits": len(metrics), "starting_reader_calls": reads,
            "measurements": metrics, "scope": "warm preparer input; no browser/queue timings"},
            indent=2), encoding="utf-8")


def test_second_streamlit_session_still_rechecks_starting_evidence(monkeypatch, tmp_path):
    from app import monthly_report_section_preview_ui
    monkeypatch.setattr(monthly_report_section_preview_ui, "render_section_preview",
                        lambda *a, **kw: None)
    app = monthly(monkeypatch, tmp_path)
    first = next(w for w in app.text_input if w.label == "Prepared by")
    first.set_value("Synthetic first-session editor").run()
    original = start.read_starting_state
    calls = []

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(start, "read_starting_state", counted)
    second = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    second.segmented_control[0].set_value("Monthly report").run()
    choose_report(second, synthetic_profiles()[0].facilities[0].title)
    assert not second.exception
    assert calls, "A new session must still independently validate saved starting evidence"
    assert all(call[:2] == (RRH_CONTRACT, "synthetic-guided") for call in calls)
    assert next(w for w in second.text_input if w.label == "Prepared by").value == ""


def test_shared_save_rechecks_starting_sources_and_persists_latest_native_edits(monkeypatch, tmp_path):
    from app import monthly_report_library as library
    from app.monthly_report_model import ReportPeriod

    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == "Prepared by").set_value(
        "Synthetic saved editor").run()
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Synthetic ten-character stable report input.").run()
    original = start.read_starting_state
    checked = []

    def fresh(*args):
        checked.append(args)
        return original(*args)

    monkeypatch.setattr(start, "read_starting_state", fresh)
    next(b for b in app.button if b.label == "Save shared version").click().run()
    assert not app.exception and not app.error
    assert len(checked) == 1, "Publish verifies its original once, rather than on each edit"
    saved = library.load_snapshot(RRH_CONTRACT, "synthetic-guided", ReportPeriod(2026, 9))
    assert saved.draft.prepared_by == "Synthetic saved editor"
    assert next(b for b in saved.draft.blocks if b.key == "activity_summary").text == "Synthetic ten-character stable report input."
    assert next(w for w in app.text_input if w.label == "Prepared by").value == "Synthetic saved editor"
    # Same native mounted session, now with a durable published revision.
    app.run()
    assert not app.exception
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", ReportPeriod(2026, 9)) == saved


def test_publication_refuses_newly_invalid_source_proof_without_losing_work(monkeypatch, tmp_path):
    from app import monthly_report_library as library
    from app.monthly_report_model import ReportPeriod

    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == "Prepared by").set_value(
        "Synthetic editor uncommitted").run()
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Synthetic work must not be dropped.").run()
    calls = []

    def damaged(*args):
        calls.append(args)
        raise ValueError("Synthetic source fingerprint changed during selection")

    monkeypatch.setattr(start, "read_starting_state", damaged)
    next(b for b in app.button if b.label == "Save shared version").click().run()
    assert not app.exception
    assert len(calls) == 1
    assert any("Shared version could not be saved" in x.value for x in app.error)
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", ReportPeriod(2026, 9)) is None
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "Synthetic work must not be dropped.")
    assert next(w for w in app.text_input if w.label == "Prepared by").value == (
        "Synthetic editor uncommitted")
