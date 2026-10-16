"""Opening a native request slot is distinct from adding report content."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportTable, ResolvedBlock


SCRIPT = '''
from dataclasses import replace
from types import SimpleNamespace
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import ReportPeriod, ResolvedBlock, default_sections, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field
original = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)),
    sections=default_sections(), blocks=(
        ResolvedBlock("rfi_matrix", "This month"),
        ResolvedBlock("activity_summary", "This month", text="Keep this unrelated finding.")))
draft = st.session_state.setdefault("draft", original)
st.session_state.setdefault("original", original)
spec = next(spec for section in draft.sections for spec in section.blocks if spec.key == "rfi_matrix")
block = next(block for block in draft.blocks if block.key == "rfi_matrix")
changed = _edit_content(spec, block, SimpleNamespace(profile=draft.profile),
    "rfi_test", {}, _field, draft)
st.session_state["draft"] = replace(draft, blocks=tuple(
    changed if item.key == changed.key else item for item in draft.blocks))
'''


def workspace():
    return AppTest.from_string(SCRIPT).run()


def block(app):
    return next(item for item in app.session_state["draft"].blocks if item.key == "rfi_matrix")


def install(app, incoming):
    draft = app.session_state["draft"]
    app.session_state["draft"] = replace(draft, blocks=tuple(
        incoming if item.key == incoming.key else item for item in draft.blocks))
    return app.run()


def add_request(app):
    return next(button for button in app.button if button.label == "Add request").click().run()


def grid_keys(app):
    return sorted(key for key, value in app.session_state.filtered_state.items()
                  if key.startswith("rfi_test_edit_rfi_matrix_") and isinstance(value, dict)
                  and "edited_rows" in value)


def edit_grid(app, key, *, edited=None, added=None, removed=None):
    app.session_state[key] = {"edited_rows": edited or {}, "added_rows": added or [],
                              "deleted_rows": removed or []}
    return app.run()


def test_empty_report_opens_only_an_empty_native_editor_without_changing_the_draft():
    app = workspace()
    before = app.session_state["draft"]
    assert not app.exception and not app.dataframe
    assert any(item.value == "No information requests added." for item in app.caption)
    add_request(app)
    assert not app.exception and len(app.dataframe) == 1
    assert app.session_state["draft"] == before
    key = grid_keys(app)[0]
    assert app.session_state[key + "_data"] == [{"Facility": None, "Requested item": None, "Status": None}]
    app.run()
    assert grid_keys(app) == [key] and app.session_state["draft"] == before


def test_entered_request_and_native_row_removal_keep_unknown_status_and_other_work():
    app = workspace()
    original = app.session_state["draft"]
    add_request(app)
    key = grid_keys(app)[0]
    edit_grid(app, key, edited={0: {"Facility": "Demo North", "Requested item": "Confirm control sequence."}})
    assert not app.exception
    assert block(app).rows == (("Demo North", "Confirm control sequence.", ""),)
    assert not any(item.value == "No information requests added." for item in app.caption)
    assert grid_keys(app) == [key]
    assert app.session_state["draft"].blocks[1] == original.blocks[1]
    edit_grid(app, key, removed=[0])
    assert not app.exception and not block(app).rows
    assert app.session_state["draft"].blocks[1] == original.blocks[1]
    assert any(item.value == "No information requests added." for item in app.caption)


def test_imported_continuation_schemas_rows_and_references_remain_native_and_editable():
    columns = ("Request #", "System / facility", "Requested details", "Recorded status", "Reference link")
    first = ReportTable(columns, (("0", "North / heating", "First line\nSecond line", "NR", "https://example.com/first"),), "native-frame-one")
    second = ReportTable(columns, (("2", "South / cooling", "Confirm drawing revision", "✓", "https://example.com/second"),), "native-frame-two")
    incoming = ResolvedBlock("rfi_matrix", "Last month", extra_tables=(first, second),
                             references=("synthetic-native-rfi",))
    app = install(workspace(), incoming)
    assert not app.exception and len(app.dataframe) == 2
    assert block(app) == incoming
    keys = grid_keys(app)
    for key in keys:
        assert tuple(app.session_state[key + "_data"][0]) == columns
    edit_grid(app, keys[0], edited={0: {"Requested details": "Clarify the current sequence."}})
    changed = block(app)
    assert changed.extra_tables[0].columns == columns
    assert changed.extra_tables[0].reference == first.reference
    assert changed.extra_tables[0].rows == (("0", "North / heating", "Clarify the current sequence.", "NR", "https://example.com/first"),)
    assert changed.extra_tables[1] == second and changed.references == incoming.references
    assert changed.source == "This month"
    assert not changed.rows
    assert grid_keys(app) == keys


def test_blank_imported_frame_is_retained_when_a_request_slot_is_opened():
    frame = ReportTable(("Site", "Question", "Recorded answer"), (("", "", ""),), "empty-native-frame")
    incoming = ResolvedBlock("rfi_matrix", "Last month", extra_tables=(frame,), references=("kept-source",))
    app = install(workspace(), incoming)
    assert not app.exception and not app.dataframe and block(app) == incoming
    add_request(app)
    assert not app.exception and len(app.dataframe) == 1
    assert block(app) == incoming


def test_imported_request_notes_do_not_receive_a_false_empty_claim():
    incoming = ResolvedBlock("rfi_matrix", "Last month", text="Requested floor plans remain pending.",
                             references=("retained-source",))
    app = install(workspace(), incoming)
    assert not app.exception and not app.dataframe
    assert not any(item.value == "No information requests added." for item in app.caption)
    assert next(item for item in app.text_area if item.label == "Notes included in this section").value == incoming.text
    add_request(app)
    assert not app.exception and len(app.dataframe) == 1 and block(app) == incoming


def test_explicit_request_entry_in_an_omitted_imported_frame_includes_only_the_entered_content():
    frame = ReportTable(("Facility", "Question", "Status"), (), "retained-empty-frame")
    incoming = ResolvedBlock("rfi_matrix", "Omit", extra_tables=(frame,), references=("retained-source",))
    app = install(workspace(), incoming)
    add_request(app)
    assert block(app) == incoming
    edit_grid(app, grid_keys(app)[0], edited={0: {"Question": "Confirm the equipment list."}})
    assert not app.exception and block(app).source == "This month"
    assert block(app).extra_tables[0].rows == (("", "Confirm the equipment list.", ""),)
    assert block(app).extra_tables[0].reference == frame.reference
    assert block(app).references == incoming.references


@pytest.mark.parametrize("generation_key", ("rfi_test_rich_text_epoch", "_monthly_qa_generation"))
def test_replaced_report_ignores_old_open_actions_and_native_grid_values(generation_key):
    app = workspace()
    add_request(app)
    old_key = grid_keys(app)[0]
    edit_grid(app, old_key, edited={0: {"Requested item": "Earlier report only."}})
    app.session_state[generation_key] = "new-report-incarnation"
    incoming = ResolvedBlock("rfi_matrix", "This month")
    install(app, incoming)
    assert not app.exception and not app.dataframe and block(app) == incoming
    # A late value under the previous native identity cannot populate this
    # replacement report, even if the old browser still sends its row delta.
    edit_grid(app, old_key, edited={0: {"Requested item": "Late old widget value."}})
    assert not app.exception and not app.dataframe and block(app) == incoming
    add_request(app)
    assert not app.exception and block(app) == incoming
    assert len(grid_keys(app)) == 1 and grid_keys(app)[0] != old_key


def test_source_replacement_with_the_same_report_has_fresh_native_grid_identity():
    app = workspace()
    original = ResolvedBlock("rfi_matrix", "Last month", rows=(("Demo North", "Old-source request", "Pending"),),
                             references=("source-a",))
    install(app, original)
    old_key = grid_keys(app)[0]
    incoming = replace(original, rows=(("Demo North", "Replacement-source request", ""),), references=("source-b",))
    install(app, incoming)
    assert not app.exception and block(app) == incoming
    assert len(grid_keys(app)) == 1 and grid_keys(app)[0] != old_key
    edit_grid(app, old_key, edited={0: {"Requested item": "Late old-source request"}})
    assert not app.exception and block(app) == incoming
