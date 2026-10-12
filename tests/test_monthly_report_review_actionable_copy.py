"""Final review shows actionable checks, not a misleading section-fill score."""

from test_monthly_report_ui import monthly


def test_review_has_no_section_coverage_score_but_retains_direct_issue_errors(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    captions = [item.value for item in app.get("caption")]
    assert not any("Monthly information is entered in" in value for value in captions)
    assert not any("Template artwork and PDF compression" in value for value in captions)
    assert not any("Every included section has some monthly input" in value
                   for value in captions)
    assert any("item" in value and "need attention below" in value for value in captions)
    assert any("Enter who prepared this report" in item.value for item in app.error)
    # Required errors still control the existing generation button.
    assert next(w for w in app.button if w.label == "Generate DOCX and PDF").disabled


def test_no_new_update_and_estimated_pages_are_optional_disclosures(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    labels = [item.label for item in app.expander]
    assert "No new update (optional)" in labels
    assert "Page layout details (advanced)" in labels
    assert "Expected pages (layout information only)" not in labels
    assert not any("Sections to consider before sharing" in item.value
                   for item in app.get("markdown"))
    assert not any("Only one section has information entered" in item.value
                   for item in app.info)
    assert any("#report-section-" in item.value for item in app.get("markdown"))
    # The saved source content remains the same after an ordinary help rerun.
    before = next(w for w in app.text_area if w.label == "Activity summary").value
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == before
