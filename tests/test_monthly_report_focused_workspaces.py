"""First-use and returning reports keep one editing home per section."""

from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_guided import STEPS, review_destination
from app.monthly_report_model import ReportFollowUp, ReportPeriod, ReportSource
from app.monthly_report_sources import SourceContent
from test_monthly_report_ui import monthly, step


def choose_section(app, key):
    next(value for value in app.selectbox if value.label == "Section to update").set_value(key).run()
    assert not app.exception


def working_state(app):
    key = next(key for key in app.session_state.filtered_state if key.startswith("report_guided_") and key.endswith("_draft"))
    return key, app.session_state[key]


def include(app, *titles):
    step(app, 1)
    for title in titles:
        next(value for value in app.checkbox if value.label == "Include " + title).check().run()


def test_first_template_has_one_active_section_and_every_section_remains_reachable(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    next(value for value in app.text_input if value.label == "Site name").set_value("Synthetic First Site").run()
    next(value for value in app.button if value.label == "Use ENFRA template").click().run()
    next(value for value in app.text_input if value.label == "Your name").set_value("Synthetic Editor").run()
    next(value for value in app.checkbox if value.label == "Save this design for these sites so we can use it next month").check().run()
    next(value for value in app.button if value.label == "Start this report").click().run()
    step(app, 2)
    assert [value.label for value in app.text_area] == ["Activity summary"]
    assert not any("logo" in value.label.lower() for value in app.get("file_uploader"))
    for key in ("scorecards", "mbcx", "maintenance", "water", "issues", "capital", "proposals", "training", "activity"):
        choose_section(app, key)
        assert not any(value.label in ("Prompt to copy manually if needed", "Paste Copilot's response") for value in app.text_area)
    step(app, 3)
    chooser = next(value for value in app.selectbox if value.label == "Site information to update")
    assert len(chooser.options) == 2
    for key in ("subcontractors", "organization"):
        next(value for value in app.selectbox if value.label == "Site information to update").set_value(key).run()
        assert not app.exception
    step(app, 1)
    assert any(value.value == "Cover and report details" for value in app.subheader)


def test_unsaved_text_and_source_state_survive_section_switches_and_direct_save(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    include(app, "Training Summary", "Monthly Scorecards")
    next(value for value in app.text_input if value.label == "Prepared by").set_value("Synthetic Editor").run()
    step(app, 2)
    assert not any(value.label == "Save this draft for others on this report to continue" for value in app.checkbox)
    assert not any(value.label in ("Prompt to copy manually if needed", "Paste Copilot's response") for value in app.text_area)
    next(value for value in app.text_area if value.label == "Activity summary").set_value("Unsaved pump repair.").run()
    draft_key, _ = working_state(app)
    source = ReportSource("a" * 64, "synthetic.txt", "a" * 64, ".txt", page_texts=("Checked the pump.",))
    app.session_state[draft_key.removesuffix("_draft") + "_evidence"] = (SourceContent(source),)
    choose_section(app, "training")
    assert not any(value.label in ("Activity summary", "Utility analysis") for value in app.text_area)
    next(value for value in app.text_area if value.label == "Training summary").set_value("Completed a controls workshop.").run()
    choose_section(app, "scorecards")
    assert any(value.label == "Utility analysis" for value in app.text_area)
    assert not any(value.label == "Training summary" for value in app.text_area)
    choose_section(app, "activity")
    assert next(value for value in app.text_area if value.label == "Activity summary").value == "Unsaved pump repair."
    assert working_state(app)[1].sources == (source,)
    next(value for value in app.button if value.label == "Save progress").click().run()
    saved = library.load_snapshot(RRH_CONTRACT, "synthetic-guided", ReportPeriod(2026, 9))
    blocks = {block.key: block for block in saved.draft.blocks}
    assert blocks["activity_summary"].text == "Unsaved pump repair."
    assert blocks["training_summary"].text == "Completed a controls workshop."
    assert saved.draft.sources == (source,)


def test_omitted_active_section_resets_selection_without_losing_its_content(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    include(app, "Training Summary")
    step(app, 2)
    choose_section(app, "training")
    next(value for value in app.text_area if value.label == "Training summary").set_value("Completed safety training.").run()
    step(app, 1)
    next(value for value in app.checkbox if value.label == "Include Training Summary").uncheck().run()
    step(app, 2)
    assert next(value for value in app.selectbox if value.label == "Section to update").value == "activity"
    assert next(block for block in working_state(app)[1].blocks if block.key == "training_summary").text == "Completed safety training."
    include(app, "Training Summary")
    step(app, 2)
    choose_section(app, "training")
    assert next(value for value in app.text_area if value.label == "Training summary").value == "Completed safety training."


def test_capacity_lives_with_utility_results_but_still_invalidates_standing_review(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    include(app, "Monthly Scorecards")
    step(app, 3)
    next(value for value in app.checkbox if value.label == "I checked the standing information for these sites").check().run()
    draft_key, draft = working_state(app)
    review_key = draft_key.removesuffix("_draft") + "_standing_reviewed_content"
    approved = app.session_state[review_key]
    step(app, 2)
    choose_section(app, "scorecards")
    assert any(value.label == "Utility analysis" for value in app.text_area)
    capacity_key = next(key for key in app.session_state.filtered_state
                        if "_edit_thermal_capacity_table_" in key and not key.endswith(("_data", "_seed")))
    app.session_state[capacity_key] = {"edited_rows": {}, "added_rows": [{"Facility": "Synthetic North", "Service": "Heating", "Capacity": 200.0, "Units": "kW"}], "deleted_rows": []}
    app.run()
    assert not app.exception
    updated = working_state(app)[1]
    capacity = next(block for block in updated.blocks if block.key == "thermal_capacity")
    assert capacity.rows and "200" in capacity.rows[0][2]
    from app.monthly_report_guided import _standing_signature
    included = {block.key for section in updated.sections if section.included for block in section.blocks}
    assert _standing_signature(updated.blocks, included) != approved
    step(app, 3)
    assert not next(value for value in app.checkbox if value.label == "I checked the standing information for these sites").value
    assert not any("_edit_thermal_capacity_table_" in (value.key or "") for value in app.dataframe)


def test_hidden_followups_still_block_download_and_review_button_opens_their_section(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    include(app, "Equipment Performance Issues", "Pending & Declined Proposals")
    next(value for value in app.text_input if value.label == "Prepared by").set_value("Synthetic Editor").run()
    draft_key, draft = working_state(app)
    issue = ReportFollowUp("follow-synthetic-pump", "issue", "Pump vibration.", "2026-08")
    proposal = ReportFollowUp("follow-synthetic-controls", "proposal", "Controls renewal.", "2026-08", status="pending")
    app.session_state[draft_key] = replace(draft, follow_ups=(issue, proposal))
    step(app, 2)
    assert not any(value.label in ("Still open", "Update proposal") for value in app.button)
    step(app, 4)
    assert next(value for value in app.button if value.label == "Generate DOCX and PDF").disabled
    assert review_destination(working_state(app)[1], issue.key) == (STEPS[1], "issues")
    next(value for value in app.button if value.label == "Open Equipment Performance Issues").click().run()
    assert next(value for value in app.selectbox if value.label == "Section to update").value == "issues"
    assert any(value.label == "Still open" for value in app.button)
    assert not any(value.label == "Update proposal" for value in app.button)
    next(value for value in app.button if value.label == "Still open").click().run()
    assert working_state(app)[1].follow_ups[1] == proposal


def test_save_keeps_name_and_revision_gates_without_extra_confirmation(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert next(value for value in app.button if value.label == "Save progress").disabled
    next(value for value in app.text_input if value.label == "Prepared by").set_value("Synthetic Editor").run()
    assert not next(value for value in app.button if value.label == "Save progress").disabled
    _, draft = working_state(app)
    library.save_snapshot(draft, expected_revision=0, entered_editor="Another synthetic editor")
    app.run()
    assert next(value for value in app.button if value.label == "Save progress").disabled
    assert any("Another version was saved" in value.value for value in app.warning)


@pytest.mark.parametrize("allowed", ({"activity_summary"}, {"utility_analysis"}))
def test_completed_source_read_survives_when_writing_help_is_hidden(monkeypatch, allowed):
    from app import monthly_report_ai_ui as ai_ui

    def finish_read(draft, prefix):
        import streamlit as st
        source = replace(draft.sources[0], page_texts=("Newly read pump inspection.",), needs_vision=())
        st.session_state[prefix + "_evidence"] = (SourceContent(source),)

    monkeypatch.setattr(ai_ui, "_finish_job", finish_read)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_ai_ui import render_drafting
from app.monthly_report_model import ReportDraft, ReportPeriod, ReportSource, synthetic_profiles
from app.monthly_report_ui import _field
source = ReportSource("a" * 64, "synthetic.pdf", "a" * 64, ".pdf", page_texts=("",), needs_vision=(1,))
draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), "Synthetic Editor", (), (), sources=(source,))
st.session_state["result"], _ = render_drafting(draft, {}, "synthetic", _field, allowed_keys=ALLOWED)
'''.replace("ALLOWED", repr(allowed))).run()
    assert not app.exception
    assert app.session_state["result"].sources[0].page_texts == ("Newly read pump inspection.",)
