"""Novice review: an empty skeleton needs a soft warning, not twelve mandatory checkboxes."""
from dataclasses import replace

from app import monthly_report_guided as guided
from app.monthly_report_docx import ReportPackage
from app.monthly_report_model import ReportPeriod, ResolvedBlock, default_sections, synthetic_draft, synthetic_profiles
from test_monthly_report_ui import monthly


def _prepared(app):
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Editor").run()
    assert not app.exception
    return app


def _generate(app):
    return next(w for w in app.button if w.label == "Create Word and PDF")


def test_advisory_count_ignores_logo_stock_text_and_empty_table_schemas():
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)),
                    sections=default_sections())
    activity = ResolvedBlock("activity_summary", "This month")
    standing = ResolvedBlock("org_chart", "Library", text="Organization already known")
    draft = replace(draft, blocks=(activity, standing))
    assert guided.monthly_entries_by_section(draft) == ()
    changed = replace(activity, text="Work completed this month.")
    draft = replace(draft, blocks=(changed, standing))
    assert guided.monthly_entries_by_section(draft) == ("activity",)


def test_empty_monthly_draft_asks_generate_anyway_before_creating_download(monkeypatch, tmp_path):
    counts = []
    def fake(draft, **kwargs):
        counts.append(draft.fingerprint)
        return ReportPackage(b"PK-SYNTHETIC", b"%PDF-SYNTHETIC", "synthetic.docx",
                             "synthetic.pdf", draft.fingerprint)
    monkeypatch.setattr(guided, "generate_report", fake)
    app = _prepared(monthly(monkeypatch, tmp_path))
    assert not _generate(app).disabled
    assert not any(w.label == "Create anyway" for w in app.button)
    assert not any("0 of" in c.value or "not a completeness score" in c.value for c in app.caption)
    _generate(app).click().run()
    assert not app.exception
    assert counts == []
    assert not app.get("download_button")
    assert [w.value for w in app.warning if "No new monthly updates" in w.value] == [
        "No new monthly updates were entered. This report may contain saved details "
        "and dividers only. Review it before sharing."
    ]
    assert any("Creating files also attempts to save a shared version." in c.value
               for c in app.caption)
    next(w for w in app.button if w.label == "Create anyway").click().run()
    assert not app.exception
    assert len(counts) == 1
    assert [w.label for w in app.get("download_button")] == ["Download DOCX", "Download PDF"]


def test_shared_save_guidance_keeps_browser_recovery_distinct(monkeypatch, tmp_path):
    app = _prepared(monthly(monkeypatch, tmp_path))
    captions = [item.value for item in app.caption]
    assert "Saving here adds a shared version; browser recovery is separate." in captions
    assert "Creating files also attempts to save a shared version." in captions
    assert not any("No new monthly updates were entered." in warning.value for warning in app.warning)



def test_one_substantive_monthly_section_remains_one_click_with_soft_advice(monkeypatch, tmp_path):
    calls = []
    def fake(draft, **kwargs):
        calls.append(draft.fingerprint)
        return ReportPackage(b"PK-SYNTHETIC", b"%PDF-SYNTHETIC",
                             "synthetic.docx", "synthetic.pdf", draft.fingerprint)
    monkeypatch.setattr(guided, "generate_report", fake)
    app = _prepared(monthly(monkeypatch, tmp_path))
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Synthetic repair completed during September.").run()
    assert not app.exception
    assert not _generate(app).disabled
    assert not any("Only one section" in m.value for m in app.info)
    assert any(e.label == "Sections without new updates (optional)" for e in app.expander)
    _generate(app).click().run()
    assert not app.exception
    assert len(calls) == 1
    assert not any(w.label == "Create anyway" for w in app.button)


def test_pending_empty_confirmation_expires_when_monthly_content_changes(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(guided, "generate_report", lambda draft, **kwargs: calls.append(draft.fingerprint))
    app = _prepared(monthly(monkeypatch, tmp_path))
    _generate(app).click().run()
    assert any(w.label == "Create anyway" for w in app.button)
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Synthetic newly added monthly work.").run()
    assert not app.exception
    assert not any(w.label == "Create anyway" for w in app.button)
    assert not calls


def test_required_preflight_blocker_still_prevents_empty_override(monkeypatch, tmp_path):
    app = _prepared(monthly(monkeypatch, tmp_path))
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Insert image here").run()
    assert not app.exception
    assert _generate(app).disabled
    assert not any(w.label == "Create anyway" for w in app.button)
