"""The fresh Water browser task starts through ordinary first-report actions."""
import pytest
from app import monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_model import ReportDraft, ResolvedBlock
from test_monthly_report_ui import monthly


def test_ordinary_earlier_unsaved_month_has_empty_omitted_water_without_hydrated_report(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    assert library.list_profiles(RRH_CONTRACT) == ()
    assert not any(isinstance(v, ReportDraft) for v in app.session_state.filtered_state.values())
    next(w for w in app.checkbox if w.label == "United Memorial Medical Center").check().run()
    app.selectbox("report_month_number").set_value(10).run()
    next(b for b in app.button if b.label == "Use ENFRA template").click().run()
    next(w for w in app.text_input if w.label == "Your name").set_value("Synthetic Fresh Water Reviewer").run()
    next(b for b in app.button if b.label == "Start this report").click().run()
    assert not app.exception
    draft = next(v for k, v in app.session_state.filtered_state.items()
                 if k.startswith("report_guided_") and k.endswith("_draft")
                 and isinstance(v, ReportDraft))
    assert draft.profile.facilities[0].title == "United Memorial Medical Center"
    # First-design setup normally resumes its empty bootstrap; that is a
    # different prerequisite from _initial_draft's optional Omit placeholder.
    assert next(b for b in draft.blocks if b.key == "water_reports") == ResolvedBlock("water_reports", "This month")
    assert draft.period.key == "2026-10"
    app.selectbox("report_month_number").set_value(9).run()
    assert not app.exception
    draft = next(v for k, v in app.session_state.filtered_state.items()
                 if k.startswith("report_guided_") and k.endswith("_draft")
                 and isinstance(v, ReportDraft) and v.period.key == "2026-09")
    assert next(b for b in draft.blocks if b.key == "water_reports") == ResolvedBlock("water_reports", "Omit")
    # AppTest has no device cookie; a new month does not inherit attribution
    # from a shared bootstrap. Enter it through the ordinary field.
    assert draft.prepared_by == ""
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Fresh Water Reviewer").run()
    draft = next(v for k, v in app.session_state.filtered_state.items()
                 if k.startswith("report_guided_") and k.endswith("_draft")
                 and isinstance(v, ReportDraft) and v.period.key == "2026-09")
    assert draft.prepared_by == "Synthetic Fresh Water Reviewer"
    assert not draft.sources
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None
    assert library.load_imported_draft(draft.profile.contract, draft.profile.key).period.key == "2026-10"
    state = library.load_profile(draft.profile.contract, draft.profile.key)
    assert state.revision == 1 and state.versions == ()
    from io import BytesIO
    from app import monthly_report_upload_ui as ui
    from scripts.qa_water_fresh_page_journey import NAME, source_pdf
    stream = BytesIO(source_pdf()); stream.name = NAME
    original_uploader = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *a, **kw:
                        [stream] if label == "Water-treatment files" else original_uploader(label, *a, **kw))
    app.run()
    include = next(b for b in app.button if b.label == "Include page")
    assert not include.disabled
    include.click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label == "Page to review").value == 2
    current = next(v for k, v in app.session_state.filtered_state.items()
                   if k.startswith("report_guided_") and k.endswith("_draft")
                   and isinstance(v, ReportDraft) and v.period.key == "2026-09")
    assert next(b for b in current.blocks if b.key == "water_reports") == ResolvedBlock("water_reports", "Omit")
    next(b for b in app.button if b.label == "Exclude page").click().run()
    assert not app.exception
    current = next(v for k, v in app.session_state.filtered_state.items()
                   if k.startswith("report_guided_") and k.endswith("_draft")
                   and isinstance(v, ReportDraft) and v.period.key == "2026-09")
    water = next(b for b in current.blocks if b.key == "water_reports")
    assert water.source != "Omit" and len(water.asset_hashes) == 1
    assert current.sources[0].selected_pages == (1,)
    assert 2 in dict(current.sources[0].client_page_exclusions)
    assert [b for b in current.blocks if b.key != "water_reports"] == [
        b for b in draft.blocks if b.key != "water_reports"]


def test_disposable_entry_does_not_seed_or_fall_back_when_marker_is_absent(monkeypatch, tmp_path):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "1")
    monkeypatch.setenv("EPC_MONTHLY_FRESH_TASK", "1")
    app = AppTest.from_file(Path(__file__).parent / "fixtures/workspaces/monthly_fresh_app.py").run()
    assert len(app.exception) == 1
    assert "marked disposable synthetic root" in app.exception[0].message
    assert not list(tmp_path.iterdir())


def test_marked_disposable_entry_runs_actual_ordinary_monthly_without_prefill(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    marker = tmp_path / "monthly-dom-synthetic-only.marker"
    marker.write_text("synthetic-monthly-dom-v1", encoding="ascii")
    fixture = Path(__file__).parent / "fixtures/workspaces/monthly_fresh_app.py"
    # Keep the process-wide no-network audit hook confined to this child.
    script = '''
from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest
app = AppTest.from_file(sys.argv[1], default_timeout=20)
app.query_params["workflow"] = "monthly"
app.run()
assert not app.exception, app.exception
assert any("ISOLATED SYNTHETIC TESTING" in w.value for w in app.warning)
assert any(b.label == "Rochester Regional Health" for b in app.button)
assert not any(b.label == "Load known-value report" for b in app.button)
assert not list(Path(sys.argv[2]).glob("monthly_reports/library/**/manifest.json"))
print("PASS real ordinary entry, no seeded profile")
'''
    run = subprocess.run([sys.executable, "-c", script, str(fixture), str(tmp_path)],
                         env={**os.environ, "EPC_DATA_DIR": str(tmp_path),
                              "EPC_MONTHLY_DOM_FIXTURE": "1", "EPC_MONTHLY_FRESH_TASK": "1"},
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS real ordinary entry, no seeded profile" in run.stdout


@pytest.mark.parametrize("query", [{}, {"workflow": "purchase"}, {"workflow": "monthly", "monthly_qa": "isolated"}])
def test_disposable_entry_rejects_other_routes_before_render_or_writes(monkeypatch, tmp_path, query):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    marker = tmp_path / "monthly-dom-synthetic-only.marker"
    marker.write_text("synthetic-monthly-dom-v1", encoding="ascii")
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "1")
    monkeypatch.setenv("EPC_MONTHLY_FRESH_TASK", "1")
    app = AppTest.from_file(Path(__file__).parent / "fixtures/workspaces/monthly_fresh_app.py")
    app.query_params.update(query)
    app.run()
    assert len(app.exception) == 1
    assert "only the ordinary Monthly route" in app.exception[0].message
    assert list(tmp_path.iterdir()) == [marker]


def test_fresh_source_is_two_readable_invented_pages_with_the_native_target():
    import pymupdf
    from scripts.qa_water_fresh_page_journey import FIRST, source_pdf
    raw = source_pdf()
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        assert len(pdf) == 2
        for number, page in enumerate(pdf, 1):
            text = page.get_text()
            assert "TEST ONLY - ALL RECORDS INVENTED" in text
            assert "Facility: " + FIRST in text
            assert "2026-09-17" in text
            assert f"Synthetic page {number}: conductivity inspected." in text


def test_durable_observer_reads_only_the_exact_target_month_and_verifies_original_bytes(monkeypatch, tmp_path):
    from dataclasses import replace
    from app import monthly_report_active_work as active
    from app.monthly_report_model import Facility, ReportDraft, ReportProfile, ReportPeriod, default_sections
    from app.monthly_report_sources import ingest
    from scripts.qa_water_fresh_page_journey import ACTOR, FIRST, durable_receipt, source_pdf
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = ReportProfile(RRH_CONTRACT, "fresh-synthetic", FIRST, (Facility("ummc", FIRST),))
    october = ReportDraft(profile, ReportPeriod(2026, 10), ACTOR, default_sections(),
                          (ResolvedBlock("water_reports", "This month"),))
    active.save("a" * 32, october, expected_revision=0, base_snapshot_revision=0)
    assert durable_receipt(tmp_path) is None
    source, _ = ingest(profile, "TEST ONLY water.pdf", source_pdf())
    source = replace(source, source=replace(source.source, classification="Water treatment"))
    september = replace(october, period=ReportPeriod(2026, 9),
                        blocks=(ResolvedBlock("water_reports", "Omit"),), sources=(source.source,))
    active.save("a" * 32, september, expected_revision=0, base_snapshot_revision=0)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    receipt = durable_receipt(tmp_path)
    assert receipt["water_source"] == "Omit" and receipt["state"]["pages"] == []
    assert receipt["originals"][0]["sha256"] == source.source.sha256
    assert receipt["period"] == "2026-09" and receipt["base_snapshot_revision"] == 0
    assert {p: p.read_bytes() for p in before} == before
    original = next(tmp_path.glob("monthly_reports/library/**/sources/*.pdf"))
    # The real source is immutable. Fault only this observer read; preserve
    # the retained original and its shared content-addressed object bytes.
    from pathlib import Path
    read_bytes = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path:
                        b"corrupted observer read" if path == original else read_bytes(path))
    with pytest.raises(AssertionError, match="original failed its digest"):
        durable_receipt(tmp_path)


def test_server_shutdown_timeout_is_bounded_and_keeps_the_first_business_failure():
    import subprocess
    from scripts.qa_water_fresh_page_journey import stop_server

    class SlowServer:
        def __init__(self):
            self.calls = []

        def poll(self):
            return None

        def terminate(self):
            self.calls.append("terminate")

        def kill(self):
            self.calls.append("kill")

        def wait(self, timeout):
            self.calls.append(("wait", timeout))
            if timeout == 15:
                raise subprocess.TimeoutExpired("synthetic server", timeout)
            return -9

    process = SlowServer()
    first = {"result": "fail", "phase": "first-page review", "error": "original include failure"}
    cleanup = stop_server(process, first)
    assert process.calls == ["terminate", ("wait", 15), "kill", ("wait", 5)]
    assert cleanup == first["cleanup_errors"]
    assert first["phase"] == "first-page review" and first["error"] == "original include failure"
