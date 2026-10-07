from dataclasses import replace
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import monthly_report_ui as ui
from app.monthly_report_docx import ReportPackage, assemble_docx


ROOT = Path(__file__).resolve().parents[1]


def monthly(monkeypatch):
    monkeypatch.setattr(ui, "operator_today", lambda timezone: date(2026, 10, 6))
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value(ui.MONTHLY_REPORT_WORKFLOW).run()
    assert not app.exception
    return app


def test_default_previous_month_and_three_equal_scopes(monkeypatch):
    app = monthly(monkeypatch)
    assert app.date_input("report_month").value == date(2026, 9, 1)
    assert len(app.selectbox("report_profile").options) == 3
    assert not app.button("report_generate").disabled


def test_draft_survives_profile_and_both_workflow_switches(monkeypatch):
    app = monthly(monkeypatch)
    app.text_area("report_individual_activity_text").set_value("Synthetic operator's reviewed activity.").run()
    app.text_input("report_individual_prepared_by").set_value("Synthetic Operator").run()
    app.button("report_individual_activity_up").click().run()
    app.toggle("report_individual_water_include").set_value(False).run()
    app.selectbox("report_profile").set_value("regional").run()
    app.selectbox("report_profile").set_value("individual").run()
    for workflow in ("Expense reimbursement", "Purchase order"):
        app.segmented_control[0].set_value(workflow).run()
        app.segmented_control[0].set_value(ui.MONTHLY_REPORT_WORKFLOW).run()
        assert not app.exception
        assert app.text_area("report_individual_activity_text").value == "Synthetic operator's reviewed activity."
        assert app.text_input("report_individual_prepared_by").value == "Synthetic Operator"
        assert not app.toggle("report_individual_water_include").value
        assert app.expander[0].label == "Monthly Activity Summary"


def test_required_highlight_placeholder_and_warning_gates(monkeypatch):
    app = monthly(monkeypatch)
    app.text_input("report_individual_prepared_by").set_value("").run()
    assert app.button("report_generate").disabled
    assert any(".st-key-report_individual_prepared_by" in m.value for m in app.markdown)
    app.text_input("report_individual_prepared_by").set_value("Synthetic Operator").run()
    app.text_area("report_individual_activity_text").set_value("Insert image from O&M progress report").run()
    assert app.button("report_generate").disabled
    app.text_area("report_individual_activity_text").set_value("August 2026 activity").run()
    assert app.button("report_generate").disabled
    app.checkbox[0].check().run()
    assert not app.button("report_generate").disabled
    app.text_area("report_individual_activity_text").set_value("July 2026 activity").run()
    assert app.button("report_generate").disabled
    assert not app.checkbox[0].value


def test_generate_downloads_only_and_edit_invalidates_artifacts(monkeypatch):
    captured = []

    def generate(draft, **kwargs):
        captured.append(draft)
        return ReportPackage(assemble_docx(draft, **kwargs), b"%PDF-synthetic", "demo.docx", "demo.pdf", draft.fingerprint)

    monkeypatch.setattr(ui, "generate_report", generate)
    app = monthly(monkeypatch)
    app.button("report_generate").click().run()
    assert not app.exception
    assert [b.label for b in app.get("download_button")] == ["Download DOCX", "Download PDF"]
    app.text_area("report_individual_activity_text").set_value("Changed.").run()
    assert not app.get("download_button")
    app.button("report_generate").click().run()
    assert len(captured) == 2


def test_ai_review_gate_is_enforced_even_in_synthetic_ui(monkeypatch):
    original = ui.synthetic_draft

    def with_unreviewed_ai(*args):
        draft = original(*args)
        return replace(draft, blocks=(replace(draft.blocks[0], ai_written=True), *draft.blocks[1:]))

    monkeypatch.setattr(ui, "synthetic_draft", with_unreviewed_ai)
    app = monthly(monkeypatch)
    assert app.button("report_generate").disabled
    assert any("Review the AI draft" in error.value for error in app.error)
