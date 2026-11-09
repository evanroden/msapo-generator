"""Unknown Starting Report sections keep a usable, explicitly chosen destination."""

from copy import deepcopy

from docx import Document
import pytest

from app import monthly_report_library as library
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import synthetic_profiles
from test_monthly_report_start_import import report_file, save_start, start_app


def other_report(tmp_path, *, title=None):
    path = report_file(tmp_path, title=title, contact=False, photo=True,
                       activity=("Synthetic extra work completed.",))
    document = Document(path)
    next(paragraph for paragraph in document.paragraphs
         if paragraph.text == "2 Monthly Activity Summary").text = "14 EXTRA SOURCE MATERIAL"
    document.save(path)
    return path


def context(app):
    stage_key = next(key for key in app.session_state.filtered_state
                     if key.startswith("report_setup_") and key.endswith("_stage"))
    prefix = app.session_state[stage_key.removesuffix("_stage") + "_active_section_review"][1]
    return prefix, app.session_state[prefix + "_section_plans"], app.session_state[stage_key]


def destination(app):
    return next(choice for choice in app.selectbox if choice.label == "Where should this content appear?")


def action(app):
    return next(choice for choice in app.radio if choice.label == "What would you like to do?")


def continue_button(app):
    return next(button for button in app.button if button.label == "Continue to this month’s updates")


def test_unknown_destination_stays_unapproved_and_reachable_across_reruns(tmp_path, monkeypatch):
    path = other_report(tmp_path)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    for _ in range(3):
        _, plans, staged = context(app)
        assert destination(app).value == ""
        assert not plans["other"]["approved"] and continue_button(app).disabled
        assert "Other content to check" in {box.label for box in app.expander}
        assert staged[1].read_bytes() == original and path.read_bytes() == original
        app.run()
        assert not app.exception
    assert not library.list_profiles(synthetic_profiles()[0].contract)


def test_first_destination_then_picture_choice_saves_to_the_chosen_section(tmp_path, monkeypatch):
    path = other_report(tmp_path)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    picture = next(item for item in inspection.items if item.kind == "image")
    app = start_app(monkeypatch, tmp_path, path)
    destination(app).set_value("activity").run()
    _, plans, _ = context(app)
    assert plans["other"]["target"] == "activity"
    assert destination(app).value == "activity"
    next(choice for choice in app.radio if choice.label == "Use this picture").set_value("keep").run()
    assert not app.exception
    _, plans, _ = context(app)
    assert picture.id in plans["other"]["selected"]
    assert not continue_button(app).disabled
    app.run()
    assert destination(app).value == "activity"
    draft = save_start(app)
    block = next(block for block in draft.blocks if "Synthetic extra work" in block.text)
    assert block.key == "activity_summary" and len(block.asset_hashes) == 1
    assert f"docx:{inspection.sha256}:{picture.id}" in block.references
    assert library.read_asset(draft.profile.contract, draft.profile.key, block.asset_hashes[0])
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == original
    assert path.read_bytes() == original
    assert library.load_profile(draft.profile.contract, draft.profile.key).profile == draft.profile


def test_first_omission_choice_is_applied_and_saves_only_the_original(tmp_path, monkeypatch):
    path = other_report(tmp_path)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    action(app).set_value("Leave this section out").run()
    _, plans, _ = context(app)
    assert plans["other"]["omit"] and plans["other"]["approved"]
    assert not continue_button(app).disabled
    app.run()
    assert action(app).value == "Leave this section out"
    draft = save_start(app)
    assert not any("Synthetic extra work" in block.text or block.asset_hashes for block in draft.blocks)
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == original


def test_omission_can_be_reversed_and_destination_corrected_before_save(tmp_path, monkeypatch):
    path = other_report(tmp_path)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    action(app).set_value("Leave this section out").run()
    action(app).set_value("Keep and review").run()
    assert continue_button(app).disabled and destination(app).value == ""
    destination(app).set_value("activity").run()
    destination(app).set_value("issues").run()
    assert destination(app).value == "issues" and not app.exception
    draft = save_start(app)
    block = next(block for block in draft.blocks if "Synthetic extra work" in block.text)
    assert block.key == "equipment_issues"
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == original


@pytest.mark.parametrize(("retained_target", "widget_target"), (
    ("other", "other"), ("retired-section", "retired-section"), (None, None),
    ("activity", "other"), ("activity", ""), ("activity", None),
))
def test_retained_invalid_plan_cannot_approve_a_closed_card_and_reopens_for_recovery(
        tmp_path, monkeypatch, retained_target, widget_target):
    path = other_report(tmp_path)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    if retained_target == "activity":
        destination(app).set_value("activity").run()
    prefix, plans, _ = context(app)
    # Restore the old app's invalid approved state, including its native widget
    # value and a closed expander. Keep all reviewed content for recovery.
    plans["other"]["target"] = retained_target
    plans["other"]["approved"] = True
    before_selected = deepcopy(plans["other"]["selected"])
    app.session_state[prefix + "_section_other_target"] = widget_target
    app.session_state[prefix + "_section_other_open"] = False
    app.run()
    assert not app.exception
    _, plans, staged = context(app)
    assert not plans["other"]["approved"] and continue_button(app).disabled
    assert plans["other"]["selected"] == before_selected
    assert staged[1].read_bytes() == original
    app.session_state[prefix + "_section_other_open"] = True
    app.run()
    assert not app.exception and destination(app).value == ""
    destination(app).set_value("activity").run()
    assert not continue_button(app).disabled
    assert "Synthetic extra work" in str(context(app)[1]["other"]["texts"])
    assert path.read_bytes() == original


def test_clearing_an_accepted_destination_blocks_continue_until_rechosen(tmp_path, monkeypatch):
    path = other_report(tmp_path)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    destination(app).set_value("activity").run()
    assert not continue_button(app).disabled
    destination(app).set_value("").run()
    assert not app.exception and continue_button(app).disabled
    assert destination(app).value == "" and not context(app)[1]["other"]["approved"]
    destination(app).set_value("issues").run()
    assert not continue_button(app).disabled
    assert context(app)[1]["other"]["target"] == "issues"
    assert path.read_bytes() == original


def test_foreign_site_other_content_remains_automatically_excluded(tmp_path, monkeypatch):
    north, south = synthetic_profiles()[1].facilities
    path = other_report(tmp_path, title=south.title)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path, known_sites=(north, south))
    for _ in range(2):
        _, plans, _ = context(app)
        assert plans["other"]["source_site_relation"] == "other"
        assert plans["other"]["approved"] and not plans["other"]["selected"]
        assert "Other content to check" not in {box.label for box in app.expander}
        assert not any(choice.label == "Where should this content appear?" for choice in app.selectbox)
        assert not continue_button(app).disabled
        app.run()
        assert not app.exception
    draft = save_start(app)
    assert draft.profile.facilities == (north,)
    assert not any("Synthetic extra work" in block.text or block.asset_hashes for block in draft.blocks)
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == original


def test_recognized_activity_keeps_automatic_import_without_destination_question(tmp_path, monkeypatch):
    path = report_file(tmp_path, activity=("September 2026 recognized work.",), photo=True, contact=False)
    original = path.read_bytes()
    app = start_app(monkeypatch, tmp_path, path)
    assert not any(choice.label == "Where should this content appear?" for choice in app.selectbox)
    assert not continue_button(app).disabled
    draft = save_start(app)
    assert any("recognized work" in block.text for block in draft.blocks)
    assert next(block for block in draft.blocks if block.key == "improvements").asset_hashes
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == original
