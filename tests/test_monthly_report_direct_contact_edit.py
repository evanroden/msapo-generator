"""Synthetic AppTest acceptance for opening a saved contact in one activation.

The native-widget submissions below exercise Streamlit's callback delivery;
they are not claims about a real browser's focus or document rendering.
"""

from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    BlockSpec, ReportPeriod, ReportTable, SectionSpec, synthetic_draft,
    synthetic_profiles,
)
from test_monthly_report_organization_ui import SCRIPT, app, click


@pytest.fixture(autouse=True)
def isolated_data(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")


def _app(customize="", *, show_preview=True, delayed_callback=False):
    if not customize and show_preview and not delayed_callback:
        at = app()
        assert not at.exception
        return at
    script = SCRIPT.replace(
        'st.session_state.setdefault("original", original)',
        customize + '\nst.session_state.setdefault("original", original)',
    )
    if not show_preview:
        script = script.replace('"test", assets, _field, editor)',
                                '"test", assets, _field, editor, show_preview=False)')
    if delayed_callback:
        script = script.replace(
            "updated = render_organization",
            '''if "delayed_callback" in st.session_state:
    callback, args, kwargs = st.session_state.pop("delayed_callback")
    callback(*args, **(kwargs or {}))
updated = render_organization''',
        )
    at = AppTest.from_string(script).run()
    assert not at.exception
    return at


def _direct_actions(at, count):
    actions = [button for button in at.button if button.label == "Edit contact"]
    assert len(actions) == count, "Each saved contact needs a direct Edit contact action."
    return actions


def _name(at):
    return next(widget for widget in at.text_input if widget.label == "Name")


@pytest.mark.parametrize("show_preview", [True, False])
def test_direct_edit_done_captures_delivered_field_and_reopens_immediately(show_preview):
    at = _app(show_preview=show_preview)
    before = dict(at.session_state["blocks"])
    assert not at.text_input
    _direct_actions(at, 1)[0].click().run()
    assert not at.exception
    assert _name(at).value == "Synthetic Person"
    assert at.session_state["blocks"] == before

    # Deliberately deliver the field and parent Done in the same native run.
    _name(at).input("Updated Synthetic Person")
    click(at, "Done")
    assert not at.exception
    contacts = at.session_state["blocks"]["contact_matrix"]
    assert contacts.extra_tables[0].rows == (("Operator", "Updated Synthetic Person"),)
    assert contacts.text == before["contact_matrix"].text
    assert contacts.references == before["contact_matrix"].references
    assert all(block == before[key] for key, block in at.session_state["blocks"].items()
               if key != "contact_matrix")
    assert not at.text_input
    action = _direct_actions(at, 1)[0]  # Present without another rerun or outer click.
    immediate_identity = (action.key, action.proto.id)
    action.click().run()
    assert not at.exception
    assert _name(at).value == "Updated Synthetic Person"
    assert at.session_state["blocks"]["contact_matrix"] == contacts
    click(at, "Done")
    action = _direct_actions(at, 1)[0]
    assert (action.key, action.proto.id) == immediate_identity
    at.run()
    action = _direct_actions(at, 1)[0]
    assert (action.key, action.proto.id) == immediate_identity


MULTI_TABLE = '''
original["contact_matrix"] = replace(original["contact_matrix"], extra_tables=(
    ReportTable(("Role", "Name", "", "Name"), (
        ("Operator", "Same Person", "", "custom-cell"),
        ("Operator", "Same Person", "", "custom-cell"),
    ), "imported-table-one"),
    ReportTable(("Name", "Phone", ""), (
        ("Same Person", "0007", ""),
        ("Same Person", "", "other custom cell"),
    ), "imported-table-two"),
))
'''


@pytest.mark.parametrize("table_index,row_index,action_index", [(0, 1, 1), (1, 0, 2), (1, 1, 3)])
def test_direct_edit_binds_duplicate_occurrence_and_preserves_imported_cells(
        table_index, row_index, action_index):
    at = _app(MULTI_TABLE)
    before = at.session_state["blocks"]["contact_matrix"]
    actions = _direct_actions(at, 4)
    assert len({button.key for button in actions}) == 4
    actions[action_index].click().run()
    assert not at.exception
    assert tuple(widget.value for widget in at.text_input) == before.extra_tables[table_index].rows[row_index]
    _name(at).input("Corrected occurrence").run()
    click(at, "Done")
    assert not at.exception
    after = at.session_state["blocks"]["contact_matrix"]
    expected_tables = list(before.extra_tables)
    rows = list(expected_tables[table_index].rows)
    cells = list(rows[row_index])
    cells[1 if table_index == 0 else 0] = "Corrected occurrence"
    rows[row_index] = tuple(cells)
    expected_tables[table_index] = replace(expected_tables[table_index], rows=tuple(rows))
    assert after.extra_tables == tuple(expected_tables)
    assert after.text == before.text and after.references == before.references
    assert after.source == "This month"
    assert all(block == at.session_state["original"][key]
               for key, block in at.session_state["blocks"].items() if key != "contact_matrix")


def test_direct_primary_row_uses_existing_contact_schema():
    at = _app('''original["contact_matrix"] = replace(
    original["contact_matrix"], extra_tables=(), rows=(
        ("Synthetic North", "Operator", "Same Person", "0007", ""),
        ("Synthetic North", "Operator", "Same Person", "", ""),
    ))''')
    before = at.session_state["blocks"]["contact_matrix"]
    _direct_actions(at, 2)[1].click().run()
    assert not at.exception
    assert [widget.label for widget in at.text_input] == ["Facility", "Role", "Name", "Phone", "Email"]
    next(widget for widget in at.text_input if widget.label == "Phone").input("0008").run()
    click(at, "Done")
    after = at.session_state["blocks"]["contact_matrix"]
    assert after.rows == (before.rows[0], (*before.rows[1][:3], "0008", ""))
    assert not after.extra_tables


def test_direct_open_and_close_preserve_reviews_artwork_notes_and_other_blocks():
    at = _app('''from app.monthly_report_asset_review import normalize_asset_reviews
contact = replace(original["contact_matrix"], asset_hashes=("chart.png",),
                  asset_captions=("Synthetic contact page",), reviewed_fingerprint="saved-review")
contact = replace(contact, client_reviewed_fingerprint=contact.fingerprint)
original["contact_matrix"] = normalize_asset_reviews(contact)
''')
    before = dict(at.session_state["blocks"])
    assets = dict(at.session_state["assets"])
    initial_action = _direct_actions(at, 1)[0]
    action_identity = (initial_action.key, initial_action.proto.id)
    initial_action.click().run()
    assert not at.exception
    assert at.session_state["blocks"] == before
    click(at, "Done")
    assert not at.exception
    assert at.session_state["blocks"] == before
    assert at.session_state["assets"] == assets
    closed_action = _direct_actions(at, 1)[0]
    assert (closed_action.key, closed_action.proto.id) == action_identity


def test_omitted_contacts_have_no_direct_edit_and_keep_retained_content():
    at = _app('original["contact_matrix"] = replace(original["contact_matrix"], source="Omit")')
    _direct_actions(at, 0)
    assert not at.text_input
    assert at.session_state["blocks"] == at.session_state["original"]
    assert any(button.label == "Edit contacts" for button in at.button)
    assert any("Not included in this report" in caption.value for caption in at.caption)


@pytest.mark.parametrize("scope_key", ["test_rich_text_epoch", "_monthly_qa_generation"])
def test_direct_native_action_identity_retires_on_report_replacement_with_same_rows(scope_key):
    at = app()
    before = dict(at.session_state["blocks"])
    original_id = _direct_actions(at, 1)[0].proto.id
    at.run()
    assert _direct_actions(at, 1)[0].proto.id == original_id
    # Reset/import may preserve every displayed cell and reference. Its old
    # native trigger must not be rebound to the replacement report's callback.
    at.session_state[scope_key] = "replacement-with-identical-contact-content"
    at.run()
    assert not at.exception
    assert _direct_actions(at, 1)[0].proto.id != original_id
    assert at.session_state["blocks"] == before
    assert not at.text_input


@pytest.mark.parametrize("scope_key", ["test_rich_text_epoch", "_monthly_qa_generation"])
def test_stale_direct_callback_cannot_open_contact_in_replaced_report(scope_key):
    at = _app(delayed_callback=True)
    button = _direct_actions(at, 1)[0]
    metadata = at.session_state._state._new_widget_state.widget_metadata[button.proto.id]
    blocks = dict(at.session_state["blocks"])
    blocks["contact_matrix"] = replace(blocks["contact_matrix"], extra_tables=(
        ReportTable(("Role", "Name"), (("Supervisor", "Replacement Person"),)),
    ))
    at.session_state["blocks"] = blocks
    at.session_state[scope_key] = "replacement-report-incarnation"
    at.session_state["test_organization_change"] = "org_chart"
    at.session_state["delayed_callback"] = (
        metadata.callback, metadata.callback_args, metadata.callback_kwargs,
    )
    at.run()
    assert not at.exception
    assert at.session_state["test_organization_change"] == "org_chart"
    assert at.session_state["blocks"] == blocks
    assert not at.text_input


def test_direct_open_preserves_unresolved_contact_receipt_and_current_tables():
    at = _app(MULTI_TABLE)
    _direct_actions(at, 4)[0].click().run()
    state = at.session_state.filtered_state
    editor_key = next(value for key, value in state.items() if key.endswith("_compact_editor_key"))
    record = dict(at.session_state[editor_key])
    expected = record["tables"]
    corrected = (replace(expected[0], rows=(
        ("Operator", "Pending Person", "", "custom-cell"), *expected[0].rows[1:],
    )), *expected[1:])
    pending = dict(expected=expected, corrected=corrected,
                   result=(replace(corrected[0], rows=corrected[0].rows[1:]), *corrected[1:]),
                   active=None, action="remove")
    record["pending"] = pending
    at.session_state[editor_key] = record
    blocks = dict(at.session_state["blocks"])
    blocks["contact_matrix"] = replace(blocks["contact_matrix"], extra_tables=(
        replace(expected[0], rows=(("Operator", "Concurrent Person", "", "custom-cell"), *expected[0].rows[1:])),
        *expected[1:],
    ))
    at.session_state["blocks"] = blocks
    at.session_state["test_organization_change"] = ""
    at.run()
    _direct_actions(at, 4)[2].click().run()
    assert not at.exception
    assert at.session_state[editor_key]["pending"] == pending
    assert at.session_state["blocks"] == blocks
    assert not at.text_input
    assert any("Contacts changed after this editor opened" in warning.value for warning in at.warning)
    assert {button.label for button in at.button} >= {"Use pending contact edits", "Keep current contacts"}
    click(at, "Done")
    assert at.session_state["test_organization_change"] == "contact_matrix"
    assert at.session_state[editor_key]["pending"] == pending
    assert at.session_state["blocks"] == blocks


def test_direct_edit_survives_snapshot_reopen_and_contact_docx():
    at = _app('''original["contact_matrix"] = replace(original["contact_matrix"],
    source="This month", references=(), extra_tables=(
        ReportTable(("Role", "Name", "Phone", "Custom detail"),
                    (("Operator", "Synthetic Person", "0007", ""),)),
    ))''')
    before = at.session_state["blocks"]["contact_matrix"]
    # A synthetic manually entered contact has no invented source reference.
    # This contact-only output fixture retains the normal assembler preflight.
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)),
                    sections=(SectionSpec("organization", "2", "Organization", (
                        BlockSpec("contact_matrix", "image_page"),)),),
                    blocks=(before,))
    original = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    _direct_actions(at, 1)[0].click().run()
    _name(at).input("Saved Corrected Person").run()
    click(at, "Done")
    assert not at.exception
    changed = at.session_state["blocks"]["contact_matrix"]
    saved = library.save_snapshot(replace(draft, blocks=(changed,)), expected_revision=1,
                                  entered_editor=draft.prepared_by)
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened == saved
    assert library.load_snapshot_version(draft.profile.contract, draft.profile.key, draft.period, 1) == original
    second = AppTest.from_string(SCRIPT)
    second.session_state["blocks"] = {"contact_matrix": reopened.draft.blocks[0]}
    second.run()
    _direct_actions(second, 1)[0].click().run()
    assert not second.exception
    assert _name(second).value == "Saved Corrected Person"
    assert second.session_state["blocks"]["contact_matrix"] == changed
    document = Document(BytesIO(assemble_docx(
        reopened.draft, acknowledged_fingerprint=reopened.draft.fingerprint,
    )))
    tables = [tuple(tuple(cell.text for cell in row.cells) for row in table.rows)
              for table in document.tables]
    assert (("Role", "Name", "Phone", "Custom detail"),
            ("Operator", "Saved Corrected Person", "0007", "")) in tables
    assert any(paragraph.text == before.text for paragraph in document.paragraphs)
