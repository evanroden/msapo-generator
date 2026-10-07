from dataclasses import replace
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_docx import ReportPackage, assemble_docx
from app.monthly_report_model import ReportPeriod, synthetic_profiles, ResolvedBlock, default_sections

ROOT = Path(__file__).resolve().parents[1]


def monthly(monkeypatch, tmp_path, *, saved=True):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(guided, "operator_today", lambda tz: date(2026, 10, 7))
    if saved:
        profile = replace(synthetic_profiles()[0], contract=RRH_CONTRACT, key="synthetic-guided",
                          excluded_sections=tuple(s.key for s in default_sections() if s.key != "activity"))
        library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
        library.replace_block(profile.contract, profile.key, "activity_summary", ResolvedBlock("activity_summary", "Library", text="Synthetic initial activity."),
                              expected_revision=1, actor="Synthetic Editor", confirmed=True, label="Synthetic activity")
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Monthly report").run()
    assert not app.exception
    return app


def step(app, number):
    next(r for r in app.radio if r.label == "Report steps").set_value(guided.STEPS[number-1]).run()
    assert not app.exception


def test_empty_contract_uploads_first_without_demo_or_day_selector(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    assert not app.date_input
    assert not any(t.key == "report_use_library" for t in app.toggle)
    assert app.selectbox("report_month_number").value == 9
    assert app.selectbox("report_year").value == 2026
    assert any(w.label == "Older or partially completed report" for w in app.get("file_uploader"))
    assert next(b for b in app.button if b.label == "Analyze report").disabled


def test_guided_text_survives_steps_and_workflow_switches(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    step(app, 2)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Synthetic reviewed repair.").run()
    step(app, 3)
    step(app, 2)
    assert next(w for w in app.text_area if w.label == "Activity summary").value == "Synthetic reviewed repair."
    for workflow in ("Expense reimbursement", "Purchase order"):
        app.segmented_control[0].set_value(workflow).run()
        app.segmented_control[0].set_value("Monthly report").run()
        assert not app.exception
        assert next(w for w in app.text_area if w.label == "Activity summary").value == "Synthetic reviewed repair."


def test_guided_progress_is_persistent_and_resumes_same_month(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Editor").run()
    step(app, 2)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Synthetic colleague's partial work.").run()
    next(w for w in app.checkbox if w.label == "Save this draft for others on this report to continue").check().run()
    next(b for b in app.button if b.label == "Save progress").click().run()
    assert not app.exception
    saved = library.load_snapshot(RRH_CONTRACT, "synthetic-guided", ReportPeriod(2026, 9))
    assert saved.entered_editor == "Synthetic Editor"
    assert next(b for b in saved.draft.blocks if b.key == "activity_summary").text == "Synthetic colleague's partial work."
    new = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    new.segmented_control[0].set_value("Monthly report").run()
    step(new, 2)
    assert next(w for w in new.text_area if w.label == "Activity summary").value == "Synthetic colleague's partial work."


def test_confirmed_import_resumes_even_with_an_older_saved_snapshot(monkeypatch, tmp_path):
    from test_monthly_report_setup import make_docx
    from app.monthly_report_import import inspect_docx
    monthly(monkeypatch, tmp_path)
    profile = library.list_profiles(RRH_CONTRACT)[0]
    state = library.load_profile(RRH_CONTRACT, profile.key)
    period = ReportPeriod(2026, 9)
    initial = guided._initial_draft(state, period, "Synthetic Editor")
    library.save_snapshot(initial, expected_revision=0, entered_editor="Synthetic Editor")
    incoming = replace(initial, blocks=tuple(replace(b, text="Synthetic imported partial work.") if b.key == "activity_summary" else b for b in initial.blocks))
    source = make_docx(tmp_path)
    library.save_report_setup(profile, incoming, source, {"sha256": inspect_docx(source).sha256}, assets=(),
                              expected_revision=state.revision, actor="Synthetic Editor", confirmed=True, snapshot_revision=1)
    new = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    new.segmented_control[0].set_value("Monthly report").run()
    step(new, 2)
    assert next(w for w in new.text_area if w.label == "Activity summary").value == "Synthetic imported partial work."


def test_guided_placeholder_warning_download_and_review_gates(monkeypatch, tmp_path):
    monkeypatch.setattr(guided, "generate_report", lambda draft, **kwargs: ReportPackage(
        assemble_docx(draft, **kwargs), b"%PDF-synthetic", "synthetic.docx", "synthetic.pdf", draft.fingerprint))
    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Editor").run()
    step(app, 2)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Insert image here").run()
    step(app, 3)
    next(w for w in app.checkbox if w.label == "I checked the standing information for these sites").check().run()
    step(app, 4)
    assert next(b for b in app.button if b.label == "Generate DOCX and PDF").disabled
    assert any("template instructions" in e.value for e in app.error)
    step(app, 2)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("August 2026 activity.").run()
    step(app, 4)
    assert next(b for b in app.button if b.label == "Generate DOCX and PDF").disabled
    next(w for w in app.checkbox if w.label == "I checked these specific warnings").check().run()
    next(b for b in app.button if b.label == "Generate DOCX and PDF").click().run()
    assert not app.exception
    assert [b.label for b in app.get("download_button")] == ["Download DOCX", "Download PDF"]
    step(app, 2)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("July 2026 activity.").run()
    step(app, 4)
    assert not app.get("download_button")
    assert not next(w for w in app.checkbox if w.label == "I checked these specific warnings").value


def test_upload_first_setup_requires_per_item_review_and_explicit_regional_membership(monkeypatch, tmp_path):
    from io import BytesIO
    from test_monthly_report_setup import make_docx
    from app import monthly_report_setup_ui as setup_ui
    from app.monthly_report_import import inspect_docx
    path = make_docx(tmp_path)
    original_bytes = path.read_bytes()
    upload = BytesIO(original_bytes)
    upload.size, upload.name = len(original_bytes), "synthetic-mixed.docx"
    real_upload = setup_ui.st.file_uploader
    monkeypatch.setattr(setup_ui.st, "file_uploader", lambda label, *a, **kw:
                        upload if label == "Older or partially completed report" else real_upload(label, *a, **kw))
    real_grid = setup_ui._grid
    monkeypatch.setattr(setup_ui, "_grid", lambda key, *a, **kw:
                        [{"Facility": "Synthetic North", "Alternate names": "Synthetic Legacy North"},
                         {"Facility": "Synthetic South", "Alternate names": ""}] if key.endswith("_facilities") else real_grid(key, *a, **kw))
    app = monthly(monkeypatch, tmp_path / "data", saved=False)
    next(b for b in app.button if b.label == "Analyze report").click().run()
    assert not app.exception
    assert not library.list_profiles(RRH_CONTRACT)
    next(w for w in app.selectbox if w.label == "What are you working on?").set_value("Finish a partially completed report").run()
    next(w for w in app.text_input if w.label == "Report name").set_value("Synthetic Region").run()
    next(w for w in app.selectbox if w.label == "Report scope").set_value("regional").run()
    next(w for w in app.text_input if w.label == "Your name").set_value("Synthetic Editor").run()
    assert next(b for b in app.button if b.label == "Save design and continue this report").disabled
    # A stale July cover must not discard September content or unread images.
    for _ in range(len(inspect_docx(path).items) + 1):
        selectors = [w for w in app.selectbox if w.label == "Use this item"]
        if not selectors:
            break
        destination = next(w for w in app.selectbox if w.label == "Where it belongs")
        choice = "Keep in report" if destination.value else "Save for reference"
        selectors[0].set_value(choice).run()
        next(b for b in app.button if b.label == "Confirm item and continue").click().run()
        assert not app.exception
    next(w for w in app.checkbox if w.label == "I checked the content decisions and confirm these sites, aliases and shared save").check().run()
    assert not next(b for b in app.button if b.label == "Save design and continue this report").disabled
    next(b for b in app.button if b.label == "Save design and continue this report").click().run()
    assert not app.exception
    profile = library.list_profiles(RRH_CONTRACT)[0]
    assert profile.scope_type == "regional" and len(profile.facilities) == 2
    assert profile.facilities[0].aliases == ("Synthetic Legacy North",)
    assert library.imported_original(RRH_CONTRACT, profile.key).read_bytes() == original_bytes
    draft = library.load_imported_draft(RRH_CONTRACT, profile.key)
    assert draft.period == ReportPeriod(2026, 9)
    assert "September 2026 repair" in next(b.text for b in draft.blocks if b.key == "activity_summary")
    assert next(b for b in draft.blocks if b.key == "vendor_reports").asset_hashes
    assert next(r for r in app.radio if r.label == "Report steps").value == guided.STEPS[0]
