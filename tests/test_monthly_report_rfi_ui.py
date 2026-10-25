"""Add request opens one request's named fields; an open blank request is not content."""
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


def press(app, label, index=0):
    [button for button in app.button if button.label == label][index].click().run()
    assert not app.exception
    return app


def add_request(app, index=0):
    return press(app, "Add request", index)


def field(app, label):
    return next(item for item in (*app.text_area, *app.text_input) if item.label == label)


def type_into(app, label, value):
    field(app, label).set_value(value).run()
    assert not app.exception
    return app


def labels(app):
    return [item.label for item in (*app.text_input, *app.text_area)]


def empty_claim(app):
    return any(item.value == "No requests added." for item in app.caption)


def test_empty_report_opens_named_request_fields_without_changing_the_draft():
    app = workspace()
    before = app.session_state["draft"]
    assert not app.exception and not app.dataframe
    assert empty_claim(app)
    add_request(app)
    assert not app.dataframe, "Add request opens named fields, not an empty grid"
    assert {"Facility", "Requested item", "Status"} <= set(labels(app))
    assert field(app, "Requested item").type == "text_area", "the request itself is multiline"
    assert field(app, "Status").type == "text_input"
    assert all(field(app, label).value == "" for label in ("Facility", "Requested item", "Status"))
    assert app.session_state["draft"] == before
    assert not empty_claim(app)
    app.run()
    assert app.session_state["draft"] == before and "Requested item" in labels(app)
    press(app, "Close editing")
    assert app.session_state["draft"] == before, "a cancelled blank request is never a row"
    assert empty_claim(app) and not labels(app)


def test_entered_request_and_row_removal_keep_unknown_status_and_other_work():
    app = workspace()
    original = app.session_state["draft"]
    add_request(app)
    type_into(app, "Facility", "Demo North")
    type_into(app, "Requested item", "Confirm control sequence.")
    assert block(app).rows == (("Demo North", "Confirm control sequence.", ""),)
    assert not empty_claim(app)
    assert app.session_state["draft"].blocks[1] == original.blocks[1]
    press(app, "Close editing")
    summaries = [item.value for item in app.markdown]
    assert "Confirm control sequence." in summaries, "the summary shows the request, not a number"
    assert any(item.value == "Status: Not recorded" for item in app.caption)
    press(app, "Remove request")
    assert not block(app).rows
    assert app.session_state["draft"].blocks[1] == original.blocks[1]
    assert empty_claim(app)
    add_request(app)
    assert "Requested item" in labels(app), "a new request stays one action away"


def test_imported_continuation_schemas_rows_and_references_remain_native_and_editable():
    columns = ("Request #", "System / facility", "Requested details", "Recorded status", "Reference link")
    first = ReportTable(columns, (("0", "North / heating", "First line\nSecond line", "NR", "https://example.com/first"),), "native-frame-one")
    second = ReportTable(columns, (("2", "South / cooling", "Confirm drawing revision", "✓", "https://example.com/second"),), "native-frame-two")
    incoming = ResolvedBlock("rfi_matrix", "Last month", extra_tables=(first, second),
                             references=("synthetic-native-rfi",))
    app = install(workspace(), incoming)
    assert not app.exception and not app.dataframe
    assert block(app) == incoming
    assert any(item.value == "Confirm drawing revision" for item in app.markdown)
    press(app, "Edit request", 0)
    assert sorted(labels(app)) == sorted(columns), "every source column is a named field"
    assert field(app, "Requested details").type == "text_area"
    for metadata in ("Request #", "Recorded status", "Reference link"):
        assert field(app, metadata).type == "text_input"
    type_into(app, "Requested details", "Clarify the current sequence.")
    changed = block(app)
    assert changed.extra_tables[0].columns == columns
    assert changed.extra_tables[0].reference == first.reference
    assert changed.extra_tables[0].rows == (("0", "North / heating", "Clarify the current sequence.", "NR", "https://example.com/first"),)
    assert changed.extra_tables[1] == second and changed.references == incoming.references
    assert changed.source == "This month"
    assert not changed.rows


def test_blank_imported_frame_is_retained_when_a_request_is_opened():
    frame = ReportTable(("Site", "Question", "Recorded answer"), (("", "", ""),), "empty-native-frame")
    incoming = ResolvedBlock("rfi_matrix", "Last month", extra_tables=(frame,), references=("kept-source",))
    app = install(workspace(), incoming)
    assert not app.exception and not app.dataframe and block(app) == incoming
    assert not any(item.label == "Edit request" for item in app.button), "a blank source row is not a request"
    add_request(app)
    assert {"Site", "Question", "Recorded answer"} <= set(labels(app))
    assert field(app, "Question").type == "text_area"
    assert block(app) == incoming


def test_imported_request_notes_do_not_receive_a_false_empty_claim():
    incoming = ResolvedBlock("rfi_matrix", "Last month", text="Requested floor plans remain pending.",
                             references=("retained-source",))
    app = install(workspace(), incoming)
    assert not app.exception and not app.dataframe
    assert not empty_claim(app)
    assert next(item for item in app.text_area if item.label == "Notes included in this section").value == incoming.text
    add_request(app)
    assert not app.exception and "Requested item" in labels(app) and block(app) == incoming


def test_explicit_request_entry_in_an_omitted_imported_frame_includes_only_the_entered_content():
    frame = ReportTable(("Facility", "Question", "Status"), (("", "", ""),), "retained-empty-frame")
    incoming = ResolvedBlock("rfi_matrix", "Omit", extra_tables=(frame,), references=("retained-source",))
    app = install(workspace(), incoming)
    add_request(app)
    assert block(app) == incoming
    type_into(app, "Question", "   ")
    assert block(app) == incoming
    type_into(app, "Question", "Confirm the equipment list.")
    assert not app.exception and block(app).source == "This month"
    assert block(app).extra_tables[0].rows == (("", "Confirm the equipment list.", ""),)
    assert block(app).extra_tables[0].reference == frame.reference
    assert block(app).references == incoming.references


@pytest.mark.parametrize("generation_key", ("rfi_test_rich_text_epoch", "_monthly_qa_generation"))
def test_replaced_report_ignores_old_open_requests_and_native_field_values(generation_key):
    app = workspace()
    add_request(app)
    old = field(app, "Requested item")
    old.set_value("Earlier report only.").run()
    app.session_state[generation_key] = "new-report-incarnation"
    incoming = ResolvedBlock("rfi_matrix", "This month")
    install(app, incoming)
    assert not app.exception and block(app) == incoming
    assert not labels(app), "an open request from the earlier report does not reopen"
    # A late value under the previous native identity cannot populate this
    # replacement report, even if the old browser still sends it.
    app.session_state[old.key] = "Late old widget value."
    app.run()
    assert not app.exception and block(app) == incoming
    add_request(app)
    assert not app.exception and block(app) == incoming
    assert field(app, "Requested item").key != old.key and field(app, "Requested item").value == ""


def test_source_replacement_with_the_same_report_has_fresh_native_identity():
    app = workspace()
    original = ResolvedBlock("rfi_matrix", "Last month", rows=(("Demo North", "Old-source request", "Pending"),),
                             references=("source-a",))
    install(app, original)
    press(app, "Edit request")
    old = field(app, "Requested item")
    incoming = replace(original, rows=(("Demo North", "Replacement-source request", ""),), references=("source-b",))
    install(app, incoming)
    assert not app.exception and block(app) == incoming
    assert not labels(app)
    app.session_state[old.key] = "Late old-source request"
    app.run()
    assert not app.exception and block(app) == incoming
