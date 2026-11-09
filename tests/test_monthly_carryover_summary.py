"""The optional intake summary describes the choices the operator can make."""

from copy import deepcopy
from dataclasses import replace
from io import BytesIO

from PIL import Image

from app.monthly_report_docx import ReportImage
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_sections import ImportSection, build_section_import, section_reviews
from app.monthly_report_start_import import analyze_starting_report, automatic_section_plans
from test_monthly_report_start_import import PERIOD, report_file, start_app


def open_summary(app):
    stage = next(key for key in app.session_state.filtered_state
                 if key.startswith("report_setup_") and key.endswith("_stage"))
    prefix = app.session_state[stage.removesuffix("_stage") + "_active_section_review"][1]
    app.session_state[prefix + "_check_import"] = True
    app.run()
    assert not app.exception
    return prefix


def summary(app, title="Monthly Activity Summary"):
    values = [caption.value for caption in app.caption
              if caption.value.startswith(title + " · ")]
    assert len(values) == 1, values
    return values[0]


def continue_button(app):
    return next(button for button in app.button
                if button.label == "Continue to this month’s updates")


def test_actual_pending_review_is_present_in_optional_summary(tmp_path, monkeypatch):
    path = report_file(tmp_path, month="July 2026",
                       activity=("Inspected the synthetic pump.",), contact=False)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    prefix = open_summary(app)
    plans = deepcopy(app.session_state[prefix + "_section_plans"])
    value = summary(app)
    assert "needs review" in value and "1 editable text selection" in value
    assert "synthetic pump" not in value
    assert continue_button(app).disabled
    open_summary(app)
    assert app.session_state[prefix + "_section_plans"] == plans
    assert path.read_bytes() == original


def test_actual_confirmation_and_omission_remain_visible_and_match_gate(tmp_path, monkeypatch):
    path = report_file(tmp_path, month="July 2026",
                       activity=("Inspected the synthetic pump.",), contact=False)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    next(choice for choice in app.checkbox
         if choice.label == "This work belongs in September 2026").check().run()
    open_summary(app)
    value = summary(app)
    assert " · ready · " in value and "1 editable text selection" in value
    assert not continue_button(app).disabled
    next(choice for choice in app.radio
         if choice.label == "What would you like to do?").set_value("Leave this section out").run()
    open_summary(app)
    value = summary(app)
    assert "source contribution deliberately excluded" in value
    assert "editable" not in value and "original retained" in value
    assert not continue_button(app).disabled
    assert path.read_bytes() == original


def test_actual_accepted_text_table_and_picture_have_separate_counts(tmp_path, monkeypatch):
    path = report_file(tmp_path, activity=("September 2026 verified work.",),
                       table=True, photo=True, contact=False)
    app = start_app(monkeypatch, tmp_path, path)
    open_summary(app)
    value = summary(app)
    assert "1 editable text selection" in value
    assert "1 editable table" in value
    assert "1 source picture selected" in value and " · ready · " in value
    assert "verified work" not in value and "PM count" not in value
    assert not continue_button(app).disabled


def test_other_picture_review_and_summary_allow_pending_destination(tmp_path, monkeypatch):
    from docx import Document
    from streamlit.testing.v1 import AppTest

    path = report_file(tmp_path, photo=True, contact=False)
    document = Document(path)
    next(paragraph for paragraph in document.paragraphs
         if paragraph.text == "2 Monthly Activity Summary").text = "14 EXTRA SOURCE MATERIAL"
    document.save(path)
    original = path.read_bytes()
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    # Exercise the real section controls with a pending destination. This is
    # a section-card harness, separate from the full starting-flow cases above.
    app = AppTest.from_string(f'''
from pathlib import Path
import streamlit as st
from app.monthly_report_carryover_summary import render_carryover_summary
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import ReportPeriod
from app.monthly_report_section_ui import _section_card
from app.monthly_report_sections import section_reviews
from app.monthly_report_ui import _field
path = Path({str(path)!r})
inspection = inspect_docx(path)
section = next(section for section in section_reviews(inspection) if section.key == "other")
plans = st.session_state.setdefault("plans", {{"other": {{"key": "other", "target": "", "approved": False}}}})
_section_card(section, path, inspection, ReportPeriod(2026, 9), "pending", _field, plans, True)
render_carryover_summary((section,), plans)
''', default_timeout=30).run()
    assert not app.exception
    next(choice for choice in app.radio
         if choice.label == "Use this picture").set_value("keep").run()
    assert not app.exception
    value = summary(app, "Other content to check")
    assert "needs review" in value and "1 source picture selected" in value
    assert not app.session_state["plans"]["other"]["approved"]
    next(choice for choice in app.selectbox
         if choice.label == "Where should this content appear?").set_value("activity").run()
    assert not app.exception
    value = summary(app, "Other content to check")
    assert " · ready · " in value and "1 source picture selected" in value
    assert app.session_state["plans"]["other"]["approved"]
    assert path.read_bytes() == original


def test_unsupported_drawing_stays_unresolved_without_mutating_plan(tmp_path):
    from docx import Document
    from docx.oxml import parse_xml
    from app.monthly_report_carryover_summary import carryover_summary

    path = report_file(tmp_path, activity=("September 2026 verified work.",), contact=False)
    document = Document(path)
    document.add_paragraph()._p.append(parse_xml(
        '<w:txbxContent xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:p><w:r><w:t>Synthetic layout label</w:t></w:r></w:p></w:txbxContent>'))
    document.save(path)
    inspection = inspect_docx(path)
    plans = automatic_section_plans(
        inspection, analyze_starting_report(inspection, synthetic_profiles()[0], PERIOD))
    section = next(section for section in section_reviews(inspection) if section.key == "activity")
    original = deepcopy(plans)
    value = carryover_summary(section, plans["activity"])
    assert value.startswith("needs review") and "1 unsupported item unresolved" in value
    assert "1 editable text selection" in value and "page selected" not in value
    assert plans == original


def test_page_selection_does_not_claim_editable_content_or_guess_unselected_items(tmp_path):
    from app.monthly_report_carryover_summary import carryover_summary

    path = report_file(tmp_path, activity=("Synthetic paragraph.",), photo=True, contact=False)
    section = next(section for section in section_reviews(inspect_docx(path)) if section.key == "activity")
    plan = {"approved": True, "page_layout": True,
            "preserved_assets": [("org_chart", object())],
            "word_page_records": [{"sections": [1]}],
            "selected": [item.id for item in section.items], "unsupported_reviewed": True}
    value = carryover_summary(section, plan)
    assert "1 complete page selected as an image" in value
    assert "editable" not in value and "source picture selected" not in value
    assert "not selected" not in value


def test_no_cover_photo_wins_over_staged_replacement(tmp_path):
    from app.monthly_report_carryover_summary import carryover_summary

    path = report_file(tmp_path, photo=True, contact=False)
    picture = next(item for item in inspect_docx(path).items if item.kind == "image")
    cover = ImportSection("cover", "Cover", (
        replace(picture, section="cover", suggested_slot="cover_photo"),))
    plan = {"approved": True, "cover_photo_omitted": True,
            "cover_photo_source_ids": [picture.id],
            "new_assets": [("cover_photo", object())]}
    value = carryover_summary(cover, plan)
    assert "cover photograph deliberately omitted" in value
    assert "replacement picture" not in value and "source picture selected" not in value


def test_replacement_summary_matches_builder_superseding_only_the_picture(tmp_path):
    from app.monthly_report_carryover_summary import carryover_summary

    path = report_file(tmp_path, activity=("September 2026 verified work.",), photo=True, contact=False)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    section = next(section for section in section_reviews(inspection) if section.key == "activity")
    picture = next(item for item in section.items if item.kind == "image")
    text = next(item for item in section.items if item.kind == "text")
    data = BytesIO()
    Image.new("RGB", (400, 300), "green").save(data, "PNG")
    replacement = ReportImage(data.getvalue(), "png", 400, 300)
    plan = {"key": "activity", "target": "activity", "approved": True,
            "selected": [text.id, picture.id],
            "destinations": {picture.id: "org_chart"},
            "new_assets": [("org_chart", replacement)]}
    before = deepcopy(plan)
    value = carryover_summary(section, plan)
    mapped, _ = build_section_import(path, inspection, [plan])
    chart = next(block for block in mapped.blocks if block.key == "org_chart")
    assert len(chart.asset_hashes) == 1 and dict(mapped.assets)[chart.asset_hashes[0]] == replacement.data
    assert any("verified work" in block.text for block in mapped.blocks)
    assert "1 replacement picture selected" in value
    assert "source picture selected" not in value and "1 editable text selection" in value
    assert plan == before and path.read_bytes() == original


def test_page_replacement_summary_matches_builder_and_keeps_only_last_named_replacement(tmp_path):
    from app.monthly_report_carryover_summary import carryover_summary
    from test_monthly_report_word_pages import drawing_report, plan_for

    path = drawing_report(tmp_path)
    inspection = inspect_docx(path)
    section = next(section for section in section_reviews(inspection) if section.key == "organization")
    pictures = []
    for color in ("navy", "green", "red"):
        data = BytesIO()
        Image.new("RGB", (400, 600), color).save(data, "PNG")
        pictures.append(ReportImage(data.getvalue(), "png", 400, 600))
    plan = plan_for(pictures[0])
    plan.update(unsupported_reviewed=True,
                new_assets=[("org_chart", pictures[1]), ("org_chart", pictures[2])])
    value = carryover_summary(section, plan)
    mapped, _ = build_section_import(path, inspection, [plan])
    chart = next(block for block in mapped.blocks if block.key == "org_chart")
    assert len(chart.asset_hashes) == 1 and dict(mapped.assets)[chart.asset_hashes[0]] == pictures[2].data
    assert "1 replacement picture selected" in value
    assert "complete page" not in value and "unsupported item unresolved" not in value


def test_stale_page_assets_are_not_reported_after_complete_page_mode_is_off(tmp_path):
    from app.monthly_report_carryover_summary import carryover_summary
    from test_monthly_report_word_pages import drawing_report, plan_for

    path = drawing_report(tmp_path)
    inspection = inspect_docx(path)
    section = next(section for section in section_reviews(inspection) if section.key == "organization")
    data = BytesIO()
    Image.new("RGB", (400, 600), "navy").save(data, "PNG")
    picture = ReportImage(data.getvalue(), "png", 400, 600)
    plan = plan_for(picture)
    # Turning off complete-page mode retains the review records for recovery,
    # while a separately named contact replacement remains selected.
    plan.update(page_layout=False, unsupported_reviewed=True,
                new_assets=[("contact_matrix", picture)])
    before = deepcopy(plan)
    value = carryover_summary(section, plan)
    mapped, _ = build_section_import(path, inspection, [plan])
    assert [block.key for block in mapped.blocks] == ["contact_matrix"]
    assert "complete page" not in value and "1 replacement picture selected" in value
    assert plan == before and plan["preserved_assets"]


def test_multiple_added_photos_do_not_hide_kept_source_picture(tmp_path):
    from app.monthly_report_carryover_summary import carryover_summary

    path = report_file(tmp_path, photo=True, contact=False)
    inspection = inspect_docx(path)
    section = next(section for section in section_reviews(inspection) if section.key == "activity")
    source = next(item for item in section.items if item.kind == "image")
    additions = []
    for color in ("green", "red"):
        data = BytesIO()
        Image.new("RGB", (400, 300), color).save(data, "PNG")
        additions.append(("improvements", ReportImage(data.getvalue(), "png", 400, 300)))
    plan = {"key": "activity", "target": "activity", "approved": True,
            "selected": [source.id], "destinations": {source.id: "improvements"},
            "new_assets": additions}
    value = carryover_summary(section, plan)
    mapped, _ = build_section_import(path, inspection, [plan])
    photos = next(block for block in mapped.blocks if block.key == "improvements")
    assert len(photos.asset_hashes) == 3
    assert "1 source picture selected" in value and "2 replacement pictures selected" in value


def test_omitted_section_overrides_retained_selections_and_approval_is_not_inferred(tmp_path):
    from app.monthly_report_carryover_summary import carryover_summary

    path = report_file(tmp_path, photo=True, contact=False)
    section = next(section for section in section_reviews(inspect_docx(path)) if section.key == "activity")
    value = carryover_summary(section, {"omit": True, "approved": False,
        "selected": [item.id for item in section.items], "new_assets": [("improvements", object())]})
    assert value == "needs review · source contribution deliberately excluded · original retained"
    # A retained review card/question is not another approval gate.
    value = carryover_summary(section, {"approved": True, "questions": ["Correction remains reachable"]})
    assert value.startswith("ready") and "needs review" not in value
    assert "no source content selected" in value
    empty = carryover_summary(ImportSection("activity", "Activity", ()), {"approved": True})
    assert "source content not found" in empty


def test_native_art_selection_is_not_described_as_a_mapped_picture():
    from app.monthly_report_carryover_summary import carryover_summary

    value = carryover_summary(ImportSection("cover", "Cover", ()),
        {"approved": True, "native_art_review": {"verified_source": "synthetic"}})
    assert value == "ready · native artwork preservation selected"
