"""Report navigation and review use content, not misleading page-size guesses."""
from test_monthly_report_ui import monthly


def test_jump_links_keep_one_report_ordered_page_and_reach_final_review(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    markup = "\n".join(m.value for m in app.markdown)
    assert "Jump to:" in markup
    assert "(#report-section-activity)" in markup
    assert "(#report-section-training)" in markup
    assert "(#report-review)" in markup
    assert "Sections to consider before sharing" not in markup
    assert any(e.label == "Sections without new updates (optional)" for e in app.expander)
    assert not any("Actual DOCX and PDF sizes" in c.value for c in app.caption)
    assert not any("Estimated document size" in c.value for c in app.caption)
    assert not any(e.label == "Expected pages (layout information only)" for e in app.expander)


def test_section_jumps_survive_activity_edit_without_extra_workflow_pages(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "September inspections completed.").run()
    assert not app.exception
    markup = "\n".join(m.value for m in app.markdown)
    assert "(#report-section-activity)" in markup and "(#report-review)" in markup
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "September inspections completed.")
