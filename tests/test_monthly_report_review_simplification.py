"""Review actions reflect actual preflight issues, never a completion percentage."""

import re

from app import monthly_report_guided as guided
from app.monthly_report_checks import ReportCheck
from test_monthly_report_ui import monthly


def test_populated_report_keeps_source_data_with_optional_no_update_navigation(
        monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    draft = next(value for key, value in app.session_state.filtered_state.items()
                 if key.endswith("_draft") and hasattr(value, "blocks"))
    before = draft.fingerprint

    captions = [node.value for node in app.get("caption")]
    assert not any("Monthly information is entered in" in value for value in captions)
    assert not any("Template artwork and PDF compression" in value for value in captions)
    assert not any("Only one section has information" in value
                   for value in [*captions, *(x.value for x in app.info)])
    assert not any(e.label == "Expected pages (layout information only)"
                   for e in app.expander)
    assert any(e.label == "Sections without new updates (optional)"
               for e in app.expander)

    # A read-only rerun must not erase the authoritative monthly data.
    app.run()
    assert not app.exception
    after = next(value for key, value in app.session_state.filtered_state.items()
                 if key.endswith("_draft") and hasattr(value, "blocks"))
    assert after.fingerprint == before
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "Synthetic initial activity.")


def test_review_header_counts_only_actionable_preflight_checks(monkeypatch, tmp_path):
    expected = (
        ReportCheck("prepared_by", "Enter attribution.", True),
        ReportCheck("source_date_unknown", "Review one source date.", False),
    )
    monkeypatch.setattr(guided, "preflight", lambda *_args: expected)
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    assert any("2 items need attention" in v.value for v in app.markdown)
    assert any("Enter attribution." in e.value for e in app.error
               if "attribution" in e.value.lower()) or any(
                   "2 items need attention" in v.value for v in app.markdown)
    assert not any(re.search(r"\b\d+ of \d+ sections\b", c.value)
                   for c in app.get("caption"))


def test_review_header_singular_when_one_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(
        guided, "preflight",
        lambda *_args: (ReportCheck("source_date_unknown", "One date needs review.", False),)
    )
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    assert any("1 item needs attention" in v.value for v in app.markdown)
    assert not any("1 item need attention" in v.value for v in app.markdown)
