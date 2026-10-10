"""Generating a saved report must not strand the next unsaved edits behind a stale generation."""
from dataclasses import replace

from app import monthly_report_active_work as active
from app import monthly_report_guided as guided
from app.monthly_report_docx import ReportPackage
from app.monthly_report_model import ReportPeriod
from app.contracts import RRH_CONTRACT
from test_monthly_report_ui import monthly


def test_generate_discards_work_but_following_edits_get_a_new_active_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(active, "enabled", lambda _value: True)
    monkeypatch.setattr(guided, "generate_report", lambda draft, **kwargs: ReportPackage(
        b"synthetic-docx", b"%PDF-test", "synthetic.docx", "synthetic.pdf", draft.fingerprint))
    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Editor").run()
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Completed synthetic September inspection.").run()
    assert not app.exception
    button = next(b for b in app.button if b.label == "Generate DOCX and PDF")
    warnings = next((w for w in app.checkbox if w.label == "I checked these specific warnings"), None)
    if warnings:
        warnings.check().run()
    button = next(b for b in app.button if b.label == "Generate DOCX and PDF")
    assert not button.disabled
    button.click().run()
    assert not app.exception
    assert any(b.label == "Download DOCX" for b in app.get("download_button"))
    # Edit again without pressing Save. The previous journal was explicitly
    # discarded after Generate, so its replacement must use the new identity.
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Completed synthetic September inspection and reviewed the next pump.").run()
    assert not app.exception
    assert not any("Another tab or a new working copy" in error.value for error in app.error)
    result = active.load("", RRH_CONTRACT, "synthetic-guided", ReportPeriod(2026, 9))
    assert result is not None
    assert any("reviewed the next pump" in b.text for b in result.draft.blocks)
    assert result.generation
