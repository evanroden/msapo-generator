"""A13 synthetic regression: one optional section-visibility task, no data loss."""

from app.monthly_report_model import ReportPeriod
from app import monthly_report_library as library
from test_cover_import_task_ui import current
from test_monthly_report_ui import monthly


def test_section_choices_are_a_single_closed_optional_task(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    panels = [item for item in app.expander if item.label == "Report sections (optional)"]
    assert not app.exception
    assert len(panels) == 1 and panels[0].proto.expanded is False
    sections = current(app).sections
    controls = [item for item in app.checkbox if item.label.startswith("Include ")
                and item.label.endswith(" in this report")]
    assert len(controls) == len(sections)
    assert {item.label for item in controls} == {
        f"Include {section.title} in this report" for section in sections
    }
    assert sum(item.label in ("Manage source files", "Done with source files")
               for item in app.button) == 1
    assert len([item for item in app.text_area if item.label == "Activity summary"]) == 1


def test_delivered_edit_survives_section_toggle_and_shared_reload(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    before = current(app)
    prior = next(block for block in before.blocks if block.key == "activity_summary")
    editor = next(item for item in app.text_area if item.label == "Activity summary")
    checkbox = next(item for item in app.checkbox
                    if item.label == "Include Monthly Activity Summary in this report")
    editor.set_value("Synthetic reviewed work on pump P-42.")
    checkbox.uncheck().run()
    assert not app.exception
    omitted = current(app)
    assert "activity" in omitted.omitted_sections
    assert next(block for block in omitted.blocks
                if block.key == "activity_summary").text == "Synthetic reviewed work on pump P-42."
    assert library.load_profile(before.profile.contract, before.profile.key).block(
        "activity_summary") == prior
    app.run()
    next(item for item in app.checkbox
         if item.label == "Include Monthly Activity Summary in this report").check().run()
    assert not app.exception
    assert "activity" not in current(app).omitted_sections
    assert next(item for item in app.text_area
                if item.label == "Activity summary").value == "Synthetic reviewed work on pump P-42."
    next(item for item in app.text_input if item.label == "Prepared by").set_value(
        "Synthetic Editor").run()
    next(item for item in app.button if item.label == "Save shared version").click().run()
    assert not app.exception
    saved = library.load_snapshot(before.profile.contract, before.profile.key, ReportPeriod(2026, 9))
    assert next(block for block in saved.draft.blocks
                if block.key == "activity_summary").text == "Synthetic reviewed work on pump P-42."


def test_attention_receipt_comes_from_current_preflight(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    import re
    markers = re.findall(r'class="epc-review-attention-source" data-count="([0-9]+)"', markup)
    assert len(markers) == 1
    assert int(markers[0]) >= 0
    assert markup.count('class="epc-section-progress"') == 1
    assert markup.count('class="epc-navigation-attention"') == 1
    assert markup.index('class="epc-navigation-attention"') < markup.index('class="epc-section-progress"')
    assert markup.count('class="epc-section-back"') == 1
    assert markup.count('class="epc-section-next"') == 1
