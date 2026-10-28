"""Carryover describes accepted choices, not a successful parser run."""
from copy import deepcopy
from dataclasses import replace

from app.monthly_report_import import inspect_docx
from app.monthly_report_sections import ImportSection, section_reviews
from app.monthly_report_start_import import analyze_starting_report, automatic_section_plans
from app.monthly_report_model import synthetic_profiles
from test_monthly_report_start_import import PERIOD, report_file, start_app
from test_monthly_source_table_roles import source


def open_summary(app):
    stage = next(k for k in app.session_state.filtered_state if k.startswith("report_setup_") and k.endswith("_stage"))
    prefix = app.session_state[stage.removesuffix("_stage") + "_active_section_review"][1]
    app.session_state[prefix + "_check_import"] = True
    app.run()
    assert not app.exception
    return prefix


def summary(app, prefix="Monthly Activity"):
    return next(c.value for c in app.caption if c.value.startswith(prefix) and " · " in c.value)


def test_actual_review_and_omission_update_summary_with_the_continue_gate(tmp_path, monkeypatch):
    path, _, _, _, _ = source(tmp_path, "Example: Synthetic source task")
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    open_summary(app)
    before = summary(app)
    assert "needs review" in before and "1 editable text selection" in before
    assert next(b for b in app.button if b.label == "Continue to this month’s updates").disabled
    next(r for r in app.radio if r.label == "Use source table 1").set_value("exclude").run()
    open_summary(app)
    after = summary(app)
    assert " · ready · " in after and "1 source item deliberately excluded" in after
    assert "needs review" not in after
    assert not next(b for b in app.button if b.label == "Continue to this month’s updates").disabled
    # The same source review card remains reachable after the explicit choice.
    next(r for r in app.radio if r.label == "What would you like to do?").set_value("Leave this section out").run()
    open_summary(app)
    assert "source contribution deliberately excluded" in summary(app)
    assert "editable" not in summary(app)
    assert path.read_bytes() == original


def test_actual_accepted_text_table_and_picture_have_separate_counts(tmp_path, monkeypatch):
    path = report_file(tmp_path, activity=("September 2026 verified work.",), table=True, photo=True, contact=False)
    app = start_app(monkeypatch, tmp_path, path)
    open_summary(app)
    value = summary(app)
    assert "1 editable text selection" in value and "1 editable table" in value
    assert "1 source picture selected" in value and " · ready · " in value


def test_unsupported_source_does_not_look_retained_or_ready(tmp_path):
    from docx import Document
    from docx.oxml import parse_xml
    from app.monthly_report_carryover_summary import carryover_summary
    path = report_file(tmp_path, activity=("September 2026 verified work.",), contact=False)
    doc = Document(path)
    doc.add_paragraph()._p.append(parse_xml('<w:txbxContent xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Synthetic layout label</w:t></w:r></w:p></w:txbxContent>'))
    doc.save(path)
    inspection = inspect_docx(path)
    plans = automatic_section_plans(inspection, analyze_starting_report(inspection, synthetic_profiles()[0], PERIOD))
    section = next(s for s in section_reviews(inspection) if s.key == "activity")
    original = deepcopy(plans)
    value = carryover_summary(section, plans["activity"])
    assert value.startswith("needs review") and "1 unsupported item unresolved" in value
    assert "1 editable text selection" in value and "retained as" not in value
    assert plans == original


def test_whole_page_and_cover_omission_are_distinct_from_editable_content(tmp_path):
    from app.monthly_report_carryover_summary import carryover_summary
    path = report_file(tmp_path, activity=("Synthetic paragraph.",), photo=True, contact=False)
    section = next(s for s in section_reviews(inspect_docx(path)) if s.key == "activity")
    plan = {"approved": True, "page_layout": True, "preserved_assets": [("org_chart", object())],
            "word_page_records": [{"sections": [1]}], "selected": [i.id for i in section.items],
            "unsupported_reviewed": True}
    value = carryover_summary(section, plan)
    assert "1 complete page retained as an image" in value and "editable" not in value
    picture = next(i for i in section.items if i.kind == "image")
    cover = ImportSection("cover", "Cover", (replace(picture, section="cover", suggested_slot="cover_photo"),))
    value = carryover_summary(cover, {"approved": True, "cover_photo_omitted": True,
        "cover_photo_source_ids": [picture.id], "new_assets": [("cover_photo", object())]})
    assert "cover photograph deliberately omitted" in value and "replacement picture" not in value
    assert "source item deliberately excluded" in value


def test_replacement_does_not_double_count_the_superseded_source_picture(tmp_path):
    from app.monthly_report_carryover_summary import carryover_summary
    path = report_file(tmp_path, photo=True, contact=False)
    section = next(s for s in section_reviews(inspect_docx(path)) if s.key == "activity")
    picture = next(i for i in section.items if i.kind == "image")
    value = carryover_summary(section, {"approved": True, "selected": [picture.id],
        "destinations": {picture.id: "org_chart"}, "new_assets": [("org_chart", object())]})
    assert "1 replacement picture selected" in value and "source picture selected" not in value
    assert "not found" in carryover_summary(ImportSection("activity", "Activity", ()), {"approved": True})
