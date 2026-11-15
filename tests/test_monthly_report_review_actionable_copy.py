"""Final Review shows actionable checks, not a misleading section-fill score."""

from test_monthly_report_ui import monthly


def test_review_has_no_section_coverage_score_but_retains_direct_issue_errors(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    review_copy = [
        item.value
        for kind in ("caption", "markdown", "info")
        for item in app.get(kind)
    ]
    old_coverage_copy = (
        "Monthly information is entered in",
        "Template artwork and PDF compression",
        "Every included section has some monthly input",
        "Only one section has information entered",
        "Sections to consider before sharing",
    )
    assert not any(phrase in value for value in review_copy
                   for phrase in old_coverage_copy)
    # Review renders the count as Markdown, not a caption or completion score.
    assert any(
        "item needs attention" in item.value or "items need attention" in item.value
        for item in app.get("markdown")
    )
    assert any("Enter who prepared this report" in item.value for item in app.error)
    # Required errors still control the existing generation button.
    assert next(w for w in app.button if w.label == "Create Word and PDF").disabled


def test_no_new_update_and_estimated_pages_are_optional_disclosures(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    # The saved activity is Library content, not a newly entered monthly update.
    # Its included section belongs in the conditional, collapsed-by-default
    # disclosure, rather than a mandatory section-coverage checklist.
    assert any(w.label == "Sections without new updates (optional)"
               for w in app.expander)
    captions = [item.value for item in app.get("caption")]
    assert any("Blank or unchanged sections are allowed" in value
               for value in captions)
    assert any("#report-section-activity" in item.value
               for item in app.get("markdown"))
    # Current Review shows planning ranges as read-only captions; it does not
    # require an additional page-count expander or acknowledgement.
    assert any("Before creation · Word estimate:" in value for value in captions)
    assert any("PDF estimate: about" in value for value in captions)
    assert not any("without new updates" in w.label.lower()
                   or "estimated pages" in w.label.lower()
                   for w in app.checkbox)
    assert not any("Sections to consider before sharing" in item.value
                   for item in app.get("markdown"))
    # Rerendering Review help must not change the saved source text.
    before = next(w for w in app.text_area if w.label == "Activity summary").value
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == before
