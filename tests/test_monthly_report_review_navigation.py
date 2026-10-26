"""Report navigation and review use content, not misleading page-size guesses."""
from test_monthly_report_ui import monthly


def test_section_selector_replaces_jump_run_and_keeps_one_ordered_page(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    markup = "\n".join(m.value for m in app.markdown)
    assert markup.count('class="epc-section-selector"') == 1
    assert 'aria-label="Jump to section"' in markup
    assert markup.count('class="epc-review-shortcut"') == 1
    assert '<button type="button" class="epc-review-shortcut" disabled>Review</button>' in markup
    assert '<label for="monthly-section-choice">Section</label>' in markup
    assert '**Jump to:**' not in markup
    assert 'data-epc-pair="monthly_activity"' in markup
    assert 'data-epc-pair="monthly_training"' in markup
    assert any(item.proto.anchor == 'report-review' for item in app.subheader)
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
    assert markup.count('class="epc-section-selector"') == 1
    assert 'data-epc-pair="monthly_activity"' in markup
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "September inspections completed.")
