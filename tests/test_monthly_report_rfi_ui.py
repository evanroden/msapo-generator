"""Opening a native request slot is distinct from adding report content."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from conftest import requires_libreoffice
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


def button(app, label, index=0):
    return [item for item in app.button if item.label == label][index]


def deliver_retired_row_packet(app, old_field, text, old_action):
    # The current tree no longer owns these intentionally retired widgets.
    # Send their original frontend identities alongside the current tree's
    # native state; serializing the entire retired AppTest tree fails before
    # Streamlit can deliver the stale packet to the guarded application.
    states = app.button[0].root.get_widget_states()
    states.widgets.add(id=old_field.proto.id, string_value=text)
    states.widgets.add().CopyFrom(old_action.click()._widget_state)
    return app._run(states)


def field(app, label):
    return next(item for kind in (app.text_input, app.text_area) for item in kind if item.label == label)


def row_fields(app):
    return [item for kind in (app.text_input, app.text_area) for item in kind if "_row_cards_" in item.key]


def focus_markers(app):
    return [item.proto.body for item in app.get("html") if "data-epc-entry-focus=" in item.proto.body]


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
    assert any(item.value == "No requests added." for item in app.caption)
    add_request(app)
    assert not app.exception and not app.dataframe
    assert app.session_state["draft"] == before
    assert {item.label: item.value for item in row_fields(app)} == {
        "Facility": "", "Requested item": "", "Status": ""}
    identity = field(app, "Requested item").proto.id
    assert field(app, "Requested item").proto.placeholder == "What information is needed?"
    assert len(focus_markers(app)) == 1
    assert field(app, "Requested item").key in focus_markers(app)[0]
    assert not any(item.value == "No requests added." for item in app.caption)
    assert button(app, "Add request").disabled
    app.run()
    assert field(app, "Requested item").proto.id == identity and app.session_state["draft"] == before


def test_entered_request_and_native_row_removal_keep_unknown_status_and_other_work():
    app = workspace()
    original = app.session_state["draft"]
    add_request(app)
    field(app, "Facility").set_value("Demo North")
    field(app, "Requested item").set_value("Confirm control sequence.")
    button(app, "Close editing").click().run()
    assert not app.exception
    assert block(app).rows == (("Demo North", "Confirm control sequence.", ""),)
    assert not any(item.value == "No requests added." for item in app.caption)
    assert not row_fields(app)
    assert app.session_state["draft"].blocks[1] == original.blocks[1]
    button(app, "Remove request").click().run()
    assert not app.exception and not block(app).rows
    assert app.session_state["draft"].blocks[1] == original.blocks[1]
    assert any(item.value == "No requests added." for item in app.caption)
    add_request(app)
    assert not app.exception and field(app, "Requested item").value == ""
    assert not any(item.value == "No requests added." for item in app.caption)


def test_imported_continuation_schemas_rows_and_references_remain_native_and_editable():
    columns = ("Request #", "System / facility", "Requested details", "Recorded status", "Reference link")
    first = ReportTable(columns, (("0", "North / heating", "First line\nSecond line", "NR", "https://example.com/first"),), "native-frame-one")
    second = ReportTable(columns, (("2", "South / cooling", "Confirm drawing revision", "✓", "https://example.com/second"),), "native-frame-two")
    incoming = ResolvedBlock("rfi_matrix", "Last month", extra_tables=(first, second),
                             references=("synthetic-native-rfi",))
    app = install(workspace(), incoming)
    assert not app.exception and not app.dataframe and not row_fields(app)
    assert block(app) == incoming
    button(app, "Edit request").click().run()
    assert tuple(item.label for item in row_fields(app)) != ()
    assert {item.label for item in row_fields(app)} == set(columns)
    assert field(app, "Requested details").value == "First line\nSecond line"
    assert any(item.label == "Requested details" for item in app.text_area)
    field(app, "Requested details").set_value("Clarify the current sequence.\nKeep the response incomplete.")
    button(app, "Close editing").click().run()
    changed = block(app)
    assert changed.extra_tables[0].columns == columns
    assert changed.extra_tables[0].reference == first.reference
    assert changed.extra_tables[0].rows == (("0", "North / heating", "Clarify the current sequence.\nKeep the response incomplete.", "NR", "https://example.com/first"),)
    assert changed.extra_tables[1] == second and changed.references == incoming.references
    assert changed.source == "This month"
    assert not changed.rows
    button(app, "Edit request", 1).click().run()
    assert field(app, "Reference link").value == "https://example.com/second"
    assert field(app, "Recorded status").value == "✓"


def test_blank_imported_frame_is_retained_when_a_request_slot_is_opened():
    frame = ReportTable(("Site", "Question", "Recorded answer"), (("", "", ""),), "empty-native-frame")
    incoming = ResolvedBlock("rfi_matrix", "Last month", extra_tables=(frame,), references=("kept-source",))
    app = install(workspace(), incoming)
    assert not app.exception and not app.dataframe and block(app) == incoming
    add_request(app)
    assert not app.exception and not app.dataframe
    assert {item.label: item.value for item in row_fields(app)} == {column: "" for column in frame.columns}
    assert block(app) == incoming
    button(app, "Close editing").click().run()
    assert block(app) == incoming and not row_fields(app)


def test_imported_request_notes_do_not_receive_a_false_empty_claim():
    incoming = ResolvedBlock("rfi_matrix", "Last month", text="Requested floor plans remain pending.",
                             references=("retained-source",))
    app = install(workspace(), incoming)
    assert not app.exception and not app.dataframe
    assert not any(item.value == "No requests added." for item in app.caption)
    assert next(item for item in app.text_area if item.label == "Notes included in this section").value == incoming.text
    add_request(app)
    assert not app.exception and row_fields(app) and block(app) == incoming


def test_explicit_request_entry_in_an_omitted_imported_frame_includes_only_the_entered_content():
    frame = ReportTable(("Facility", "Question", "Status"), (("", "", ""),), "retained-empty-frame")
    incoming = ResolvedBlock("rfi_matrix", "Omit", extra_tables=(frame,), references=("retained-source",))
    app = install(workspace(), incoming)
    add_request(app)
    assert block(app) == incoming
    field(app, "Question").set_value("   ").run()
    assert block(app) == incoming
    field(app, "Question").set_value("Confirm the equipment list.")
    button(app, "Close editing").click().run()
    assert not app.exception and block(app).source == "This month"
    assert block(app).extra_tables[0].rows == (("", "Confirm the equipment list.", ""),)
    assert block(app).extra_tables[0].reference == frame.reference
    assert block(app).references == incoming.references


@pytest.mark.parametrize("generation_key", ("rfi_test_rich_text_epoch", "_monthly_qa_generation"))
def test_replaced_report_ignores_old_actions_and_native_field_values(generation_key):
    app = workspace()
    add_request(app)
    old_field = field(app, "Requested item")
    old_key = old_field.key
    old_close = button(app, "Close editing")
    old_field.set_value("Earlier report only.").run()
    app.session_state[generation_key] = "new-report-incarnation"
    incoming = ResolvedBlock("rfi_matrix", "This month")
    install(app, incoming)
    assert not app.exception and not row_fields(app) and block(app) == incoming
    # A late value under the previous native identity cannot populate this
    # replacement report, even if the old browser still sends its field value.
    deliver_retired_row_packet(app, old_field, "Late old widget value.", old_close)
    assert not app.exception and not row_fields(app) and block(app) == incoming
    add_request(app)
    assert not app.exception and block(app) == incoming
    assert field(app, "Requested item").key != old_key
    assert field(app, "Requested item").value == ""


def test_source_replacement_with_the_same_report_has_fresh_native_row_identity():
    app = workspace()
    original = ResolvedBlock("rfi_matrix", "Last month", rows=(("Demo North", "Old-source request", "Pending"),),
                             references=("source-a",))
    install(app, original)
    button(app, "Edit request").click().run()
    old_field = field(app, "Requested item")
    old_key = old_field.key
    old_close = button(app, "Close editing")
    incoming = replace(original, rows=(("Demo North", "Replacement-source request", ""),), references=("source-b",))
    install(app, incoming)
    assert not app.exception and block(app) == incoming
    assert not row_fields(app)
    deliver_retired_row_packet(app, old_field, "Late old-source request", old_close)
    assert not app.exception and block(app) == incoming
    button(app, "Edit request").click().run()
    assert field(app, "Requested item").key != old_key
    assert field(app, "Requested item").value == "Replacement-source request"


def test_switching_native_continuation_rows_keeps_one_active_editor_and_pending_text():
    columns = ("Facility", "Question", "Status", "Reference link")
    first = ReportTable(columns, (("Demo North", "Keep first", "", "https://example.com/first"),), "first-frame")
    second = ReportTable(columns, (("Demo South", "Keep second", "NR", "https://example.com/second"),), "second-frame")
    incoming = ResolvedBlock("rfi_matrix", "This month", extra_tables=(first, second), references=("native-source",))
    app = install(workspace(), incoming)
    button(app, "Edit request").click().run()
    identity = field(app, "Question").proto.id
    field(app, "Question").set_value("First delivered note\nSecond line")
    button(app, "Edit request").click().run()
    assert not app.exception
    assert len([item for item in row_fields(app) if item.label == "Question"]) == 1
    assert field(app, "Question").value == "Keep second"
    assert block(app).extra_tables[0].rows[0][1] == "First delivered note\nSecond line"
    assert block(app).extra_tables[1] == second
    button(app, "Edit request").click().run()
    assert field(app, "Question").proto.id == identity
    assert field(app, "Question").value == "First delivered note\nSecond line"


def test_blank_close_cancels_only_the_active_entry_and_removes_its_focus_marker():
    app = workspace()
    original = app.session_state["draft"]
    add_request(app)
    first_marker = focus_markers(app)[0]
    field(app, "Requested item").set_value("   ")
    button(app, "Close editing").click().run()
    assert not app.exception and app.session_state["draft"] == original
    assert not row_fields(app) and not focus_markers(app)
    assert any(item.value == "No requests added." for item in app.caption)
    add_request(app)
    assert focus_markers(app)[0] != first_marker
    field(app, "Requested item").set_value("A real new request.").run()
    assert not focus_markers(app)
    assert block(app).rows == (("", "A real new request.", ""),)


def test_unrecognized_schema_keeps_custom_fields_without_guessing_a_focus_destination():
    incoming = ResolvedBlock("rfi_matrix", "Omit", extra_tables=(
        ReportTable(("Item ID", "", "Recorded answer"), (), "custom-native-frame"),))
    app = install(workspace(), incoming)
    add_request(app)
    assert not app.exception and not focus_markers(app)
    assert {item.label for item in row_fields(app)} == {"Item ID", "Detail 2", "Recorded answer"}
    assert block(app) == incoming


@pytest.mark.parametrize("columns, requested", (
    (("Requested by", "Requested item", "Status"), "Requested item"),
    (("Requested date", "Question", "Status"), "Question"),
    (("Question #", "Requested details", "Requested by"), "Requested details"),
    (("Requested item #", "Requested\nItems:", "Status"), "Requested\nItems:"),
))
def test_imported_request_content_gets_focus_without_reinterpreting_author_date_or_identifier(columns, requested):
    frame = ReportTable(columns, (), "request-content-schema")
    incoming = ResolvedBlock("rfi_matrix", "Omit", extra_tables=(frame,), references=("kept-source",))
    app = install(workspace(), incoming)
    add_request(app)
    assert not app.exception and block(app) == incoming
    assert {item.label for item in row_fields(app)} == set(columns)
    assert len(focus_markers(app)) == 1
    assert field(app, requested).key in focus_markers(app)[0]
    assert any(item.label == requested for item in app.text_area)
    assert field(app, requested).proto.placeholder == "What information is needed?"
    for label in columns:
        if label != requested:
            assert any(item.label == label for item in app.text_input)
            assert not field(app, label).proto.placeholder
            field(app, label).set_value("2026-10-19" if "date" in label.lower() else "0042")
    field(app, requested).set_value("Confirm the drawing revision.\nThe response remains pending.")
    expected = tuple(field(app, label).value for label in columns)
    button(app, "Close editing").click().run()
    assert not app.exception
    assert block(app).extra_tables == (replace(frame, rows=(expected,)),)
    assert block(app).references == incoming.references
    assert any(item.value == expected[columns.index(requested)] for item in app.markdown)
    app.run()
    button(app, "Edit request").click().run()
    assert {item.label: item.value for item in row_fields(app)} == dict(zip(columns, expected))


@pytest.mark.parametrize("columns", (
    ("Requested by", "Requested date", "Question #", "Status"),
    ("Requested item #", "Question ID", "Date requested", "Status"),
    ("Requested item", "Question", "Status"),
))
def test_metadata_only_or_ambiguous_request_columns_have_no_guessed_focus(columns):
    incoming = ResolvedBlock("rfi_matrix", "Omit", extra_tables=(
        ReportTable(columns, (), "unresolved-content-schema"),))
    app = install(workspace(), incoming)
    add_request(app)
    assert not app.exception and not focus_markers(app) and block(app) == incoming
    assert {item.label for item in row_fields(app)} == set(columns)
    assert not any(item.proto.placeholder for item in row_fields(app))
    if columns[0] == "Requested item":
        assert {item.label for item in app.text_area if "_row_cards_" in item.key} == {"Requested item", "Question"}
    else:
        assert all(any(item.label == label for item in app.text_input) for label in columns)
    button(app, "Close editing").click().run()
    assert not app.exception and block(app) == incoming


@requires_libreoffice
def test_native_edits_preserve_continuation_schema_links_and_unknowns_in_durable_word_pdf(monkeypatch, tmp_path):
    from app import monthly_report_active_work as active, pdf_converter
    from app.monthly_report_checks import preflight
    from app.monthly_report_docx import assemble_docx
    import pymupdf
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path/'data'))
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    monkeypatch.setattr(pdf_converter, 'PDF_BACKEND', 'libreoffice')
    columns = ('Request #','Facility','Requested details','Recorded status','Reference link')
    first = ReportTable(columns, (('0007','Demo North','Current sequence needed','',
                                  'https://example.com/rfi-first'),), 'native-rfi-frame-one')
    second = ReportTable(columns, (('0008','Demo South','Confirm the drawing revision','NR',
                                   'https://example.com/rfi-second'),), 'native-rfi-frame-two')
    incoming = ResolvedBlock('rfi_matrix','This month', extra_tables=(first,second),
                             references=('synthetic-source-rfi',))
    app = install(workspace(), incoming)
    unrelated = app.session_state['draft'].blocks[1]
    button(app, 'Edit request').click().run()
    field(app, 'Requested details').set_value('Confirm the current sequence.\nResponse remains pending.')
    button(app, 'Close editing').click().run()
    assert not app.exception and app.session_state['draft'].blocks[1] == unrelated
    changed = block(app)
    assert changed.extra_tables[0].reference == first.reference
    assert changed.extra_tables[1] == second and changed.references == incoming.references
    draft = app.session_state['draft']
    saved = active.save('9'*32, draft, expected_revision=0, base_snapshot_revision=0)
    loaded = active.load('9'*32, draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.draft == draft and loaded.revision == saved.revision
    fresh = install(workspace(), next(item for item in loaded.draft.blocks if item.key == 'rfi_matrix'))
    assert block(fresh) == changed and not row_fields(fresh)
    button(fresh, 'Edit request').click().run()
    assert field(fresh, 'Requested details').value == 'Confirm the current sequence.\nResponse remains pending.'
    output = replace(loaded.draft, sections=tuple(replace(section, included=section.key=='rfi')
                                                for section in loaded.draft.sections))
    assert not any(check.blocking for check in preflight(output))
    word = assemble_docx(output, acknowledged_fingerprint=output.fingerprint)
    word_path = tmp_path/'native-rfi-requests.docx'
    word_path.write_bytes(word)
    tables = [table for table in Document(BytesIO(word)).tables
              if tuple(cell.text for cell in table.rows[0].cells) == columns]
    assert len(tables) == 2
    assert tuple(cell.text for cell in tables[0].rows[1].cells) == changed.extra_tables[0].rows[0]
    assert tuple(cell.text for cell in tables[1].rows[1].cells) == second.rows[0]
    pdf_path = pdf_converter.convert_to_pdf(word_path)
    with pymupdf.open(pdf_path) as document:
        text = ' '.join(' '.join(page.get_text().split()) for page in document)
        assert text.count('Confirm the current sequence. Response remains pending.') == 1
        assert text.count('Confirm the drawing revision') == 1
        assert '0007' in text and '0008' in text and 'NR' in text
        # PDF text extraction inserts whitespace at legitimate cell wrapping
        # points. The editable DOCX cells above remain exact, including URLs.
        unwrapped = ''.join(text.split())
        assert unwrapped.count('https://example.com/rfi-first') == 1
        assert unwrapped.count('https://example.com/rfi-second') == 1
        assert 'What information is needed?' not in text and 'No requests added.' not in text
