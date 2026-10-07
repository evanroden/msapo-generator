from dataclasses import replace
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_editor as editor, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_docx import ReportPackage, assemble_docx
from app.monthly_report_model import ReportPeriod, default_sections, synthetic_profiles


ROOT = Path(__file__).resolve().parents[1]


def app_with_library(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(editor, "operator_today", lambda tz: date(2026, 10, 6))
    profile = replace(synthetic_profiles()[0], contract=RRH_CONTRACT, key="synthetic",
                      excluded_sections=tuple(s.key for s in default_sections() if s.key != "organization"))
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)

    def generate(draft, **kwargs):
        return ReportPackage(assemble_docx(draft, **kwargs), b"%PDF-synthetic", "demo.docx", "demo.pdf", draft.fingerprint)

    monkeypatch.setattr(editor, "generate_report", generate)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Monthly report").run()
    app.toggle("report_use_library").set_value(True).run()
    assert not app.exception
    return app, profile


def org_source(app):
    return next(box for box in app.selectbox if box.key.endswith("_org_chart_source"))


def generate_button(app):
    return next(button for button in app.button if button.label == "Generate DOCX and PDF")


def mock_chart_upload(monkeypatch):
    stream = BytesIO()
    Image.new("RGB", (50, 40), "blue").save(stream, "PNG")
    stream.name = "synthetic-chart.png"
    original = editor.st.file_uploader
    monkeypatch.setattr(editor.st, "file_uploader", lambda label, *args, **kwargs:
                        stream if label == "Replace org chart" else original(label, *args, **kwargs))


def test_profile_load_shows_real_structure_and_missing_org_chart(monkeypatch, tmp_path):
    app, profile = app_with_library(monkeypatch, tmp_path)
    assert generate_button(app).disabled
    assert any("org_chart" in item.value for item in app.error)
    assert any(profile.facilities[0].title in item.value for item in app.markdown)


def test_one_off_org_chart_generates_snapshot_without_changing_library(monkeypatch, tmp_path):
    app, profile = app_with_library(monkeypatch, tmp_path)
    mock_chart_upload(monkeypatch)
    org_source(app).set_value("Replace once").run()
    assert not app.exception
    assert not generate_button(app).disabled
    generate_button(app).click().run()
    assert not app.exception
    assert len(app.get("download_button")) == 2
    assert library.load_profile(profile.contract, profile.key).block("org_chart") is None
    saved = library.load_snapshot(profile.contract, profile.key, ReportPeriod(2026, 9))
    assert saved is not None
    assert next(b for b in saved.draft.blocks if b.key == "org_chart").asset_hashes
    app.segmented_control[0].set_value("Purchase order").run()
    app.segmented_control[0].set_value("Monthly report").run()
    assert org_source(app).value == "Replace once"
    assert not generate_button(app).disabled


def test_shared_org_chart_needs_confirmation_and_next_template_uses_it(monkeypatch, tmp_path):
    app, profile = app_with_library(monkeypatch, tmp_path)
    mock_chart_upload(monkeypatch)
    org_source(app).set_value("Replace and save to library").run()
    assert not app.exception
    assert generate_button(app).disabled
    actor = next(widget for widget in app.text_input if widget.label == "Editor name")
    actor.set_value("Synthetic Editor").run()
    confirm = next(widget for widget in app.checkbox if widget.label == "Save this replacement as a new shared library version")
    confirm.check().run()
    next(b for b in app.button if b.label == "Confirm library replacement").click().run()
    assert not app.exception
    state = library.load_profile(profile.contract, profile.key)
    assert state.block("org_chart").asset_hashes
    assert not generate_button(app).disabled
    app.date_input("report_month").set_value(date(2026, 10, 1)).run()
    assert not app.exception
    assert org_source(app).value == "Library"
    assert not generate_button(app).disabled


def test_caption_cannot_resolve_missing_required_image(monkeypatch, tmp_path):
    app, _ = app_with_library(monkeypatch, tmp_path)
    org_source(app).set_value("Replace once").run()
    next(widget for widget in app.text_input if widget.label == "Caption").set_value("Synthetic org chart caption").run()
    assert generate_button(app).disabled


def test_last_month_keeps_section_and_block_order_and_one_off_assets(monkeypatch, tmp_path):
    app, profile = app_with_library(monkeypatch, tmp_path)
    mock_chart_upload(monkeypatch)
    org_source(app).set_value("Replace once").run()
    next(b for b in app.button if b.key.endswith("_organization_down")).click().run()
    next(b for b in app.button if b.key.endswith("_org_chart_down")).click().run()
    generate_button(app).click().run()
    saved = library.load_snapshot(profile.contract, profile.key, ReportPeriod(2026, 9))
    assert saved.draft.sections[0].key == "activity"
    assert saved.draft.sections[1].blocks[0].key == "business_hours_workflow"
    app.date_input("report_month").set_value(date(2026, 10, 1)).run()
    assert org_source(app).value == "Last month"
    assert not generate_button(app).disabled
    generate_button(app).click().run()
    next_saved = library.load_snapshot(profile.contract, profile.key, ReportPeriod(2026, 10))
    assert [s.key for s in next_saved.draft.sections] == [s.key for s in saved.draft.sections]
    assert next_saved.draft.sections[1].blocks == saved.draft.sections[1].blocks
    start = next(r for r in app.radio if r.label == "Start from")
    start.set_value("The profile's library template").run()
    assert org_source(app).value == "Library"
    assert generate_button(app).disabled  # One-off assets never become template defaults.


def test_typed_table_round_trip_preserves_zero_false_and_dates():
    from app.monthly_report_model import BlockSpec, ColumnSpec
    spec = BlockSpec("synthetic_table", "table", columns=(
        ColumnSpec("cost", "Cost", "currency"), ColumnSpec("when", "Date", "date"),
        ColumnSpec("done", "Complete", "boolean"),
    ))
    seed, config = editor._typed_table(spec, (("0", "2026-09-01", "No"),))
    assert seed == [{"Cost": 0.0, "Date": date(2026, 9, 1), "Complete": False}]
    assert [editor._cell_text(v) for v in seed[0].values()] == ["0.0", "2026-09-01", "No"]
    assert len(config) == 3


def test_empty_typed_editors_render_and_survive_workflow_cleanup(monkeypatch, tmp_path):
    app, _ = app_with_library(monkeypatch, tmp_path)
    for key in ("service_calls", "subcontractor_matrix", "capital_renewal"):
        next(box for box in app.selectbox if box.key.endswith("_" + key + "_source")).set_value("This month").run()
        assert not app.exception
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.segmented_control[0].set_value("Monthly report").run()
    assert not app.exception
    for key in ("service_calls", "subcontractor_matrix", "capital_renewal"):
        assert next(box for box in app.selectbox if box.key.endswith("_" + key + "_source")).value == "This month"
