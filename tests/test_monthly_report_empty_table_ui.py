"""Empty Capital/RFI entry keeps blank native slots out of saved/exported rows."""
from dataclasses import replace
from io import BytesIO

import pytest
from docx import Document
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import ReportTable, ResolvedBlock
from app.monthly_report_row_cards_ui import CARD_TABLES
from app.monthly_report_table_entry_ui import EMPTY_TABLES
from test_monthly_report_rfi_ui import SCRIPT, field, labels, press


# Requests open named row fields; Capital and end-of-life keep their grids.
CAPITAL_TABLES = ('capital_renewal', 'end_of_life')


def edit_grid(app, key, *, edited=None, added=None, removed=None):
    app.session_state[key] = {"edited_rows": edited or {}, "added_rows": added or [],
                              "deleted_rows": removed or []}
    return app.run()


def workspace(key):
    return AppTest.from_string(SCRIPT.replace('"rfi_matrix"', repr(key))).run()


def current(app, key):
    return next(block for block in app.session_state['draft'].blocks if block.key == key)


def grid(app, key):
    return next(name for name, value in app.session_state.filtered_state.items()
                if name.startswith('rfi_test_edit_' + key) and isinstance(value, dict) and 'edited_rows' in value)


def open_entry(app, key):
    next(button for button in app.button if button.label == CARD_TABLES.get(key, (None, EMPTY_TABLES[key][1]))[1]).click().run()


def test_open_request_removes_the_empty_sentence_and_none_cell_placeholders():
    app = workspace('rfi_matrix')
    before = app.session_state['draft']
    open_entry(app, 'rfi_matrix')
    assert not app.exception and app.session_state['draft'] == before
    assert not any(item.value in {'No requests added.', 'No information requests added.'} for item in app.caption)
    assert {field(app, label).value for label in labels(app)} == {''}


def test_blank_and_removed_requests_do_not_enter_durable_data_or_actual_word_output(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = workspace('rfi_matrix')
    open_entry(app, 'rfi_matrix')
    field(app, 'Requested item').set_value('   ').run()
    assert not app.exception and not current(app, 'rfi_matrix').rows
    field(app, 'Requested item').set_value('Synthetic item to remove.').run()
    assert current(app, 'rfi_matrix').rows[0][1] == 'Synthetic item to remove.'
    press(app, 'Remove request')
    assert not current(app, 'rfi_matrix').rows
    open_entry(app, 'rfi_matrix')
    press(app, 'Close editing')  # A cancelled blank request is not a row.
    assert not current(app, 'rfi_matrix').rows
    draft = app.session_state['draft']
    kept = active.save('e' * 32, draft, expected_revision=0, base_snapshot_revision=0)
    loaded = active.load('e' * 32, draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.draft == draft and loaded.revision == kept.revision
    output_draft = replace(draft, sections=tuple(replace(section, included=any(spec.key == 'rfi_matrix' for spec in section.blocks))
                                                for section in draft.sections))
    assert all(check.code == 'empty' and not check.blocking for check in preflight(output_draft))
    document = Document(BytesIO(assemble_docx(output_draft, acknowledged_fingerprint=output_draft.fingerprint)))
    table_text = '\n'.join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    assert 'Synthetic item to remove.' not in table_text
    assert 'None' not in table_text
    assert EMPTY_TABLES['rfi_matrix'][0] not in table_text



@pytest.mark.parametrize('key', CAPITAL_TABLES)
def test_fresh_entry_opens_blank_native_cells_without_stale_empty_copy_or_data(key):
    app = workspace(key)
    original = app.session_state['draft']
    assert not app.exception and not app.dataframe
    assert any(item.value == EMPTY_TABLES[key][0] for item in app.caption)
    open_entry(app, key)
    assert not app.exception and not app.dataframe
    assert app.session_state['draft'] == original
    fields = (*app.text_input, *app.text_area)
    assert len(fields) == 3 and {widget.value for widget in fields} == {''}
    identity = fields[0].proto.id
    assert not any(item.value == EMPTY_TABLES[key][0] for item in app.caption)
    label = CARD_TABLES[key][1]
    assert next(button for button in app.button if button.label == label).disabled
    app.run()
    assert not app.exception and app.session_state['draft'] == original
    assert (*app.text_input, *app.text_area)[0].proto.id == identity



@pytest.mark.parametrize('key', CAPITAL_TABLES)
def test_blank_and_removed_rows_do_not_enter_durable_data_or_actual_word_output(monkeypatch, tmp_path, key):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = workspace(key)
    open_entry(app, key)
    field_name = 'Recommendation' if key == 'capital_renewal' else 'Asset'
    def chosen():
        return next(widget for widget in (*app.text_input, *app.text_area)
                    if widget.label == field_name)
    chosen().set_value('   ').run()
    assert not app.exception and not current(app, key).rows
    chosen().set_value('Synthetic item to remove.').run()
    index = 2 if key == 'capital_renewal' else 1
    assert current(app, key).rows[0][index] == 'Synthetic item to remove.'
    assert not app.dataframe
    next(button for button in app.button if button.label == 'Remove ' + CARD_TABLES[key][0]).click().run()
    assert not app.exception and not current(app, key).rows
    draft = app.session_state['draft']
    kept = active.save('e' * 32, draft, expected_revision=0, base_snapshot_revision=0)
    loaded = active.load('e' * 32, draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.draft == draft and loaded.revision == kept.revision
    output_draft = replace(draft, sections=tuple(replace(section, included=any(spec.key == key for spec in section.blocks))
                                                for section in draft.sections))
    # The intentionally empty section is qualified without weakening site
    # identity, source review, or the client-facing price gate.
    assert all(check.code == 'empty' and not check.blocking for check in preflight(output_draft))
    document = Document(BytesIO(assemble_docx(output_draft, acknowledged_fingerprint=output_draft.fingerprint)))
    table_text = '\n'.join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    assert 'Synthetic item to remove.' not in table_text
    assert 'None' not in table_text
    assert EMPTY_TABLES[key][0] not in table_text


@pytest.mark.parametrize('key', ('capital_renewal', 'end_of_life'))
def test_omitted_imported_empty_capital_frame_keeps_schema_until_deliberate_entry(key):
    app = workspace(key)
    original = app.session_state['draft']
    frame = ReportTable(('Source identifier', 'Asset / recommendation', 'Timing', 'Recorded status'), (('', '', '', ''),), 'native-source-frame')
    incoming = ResolvedBlock(key, 'Omit', extra_tables=(frame,), references=('synthetic-retained-source',))
    app.session_state['draft'] = replace(original, blocks=tuple(incoming if block.key == key else block for block in original.blocks))
    app.run()
    assert not app.dataframe and current(app, key) == incoming
    open_entry(app, key)
    assert not app.dataframe and current(app, key) == incoming
    timing = next(widget for widget in app.text_input if widget.label == 'Timing')
    identity = timing.proto.id
    timing.set_value('   ').run()
    assert current(app, key) == incoming  # Whitespace never reincludes an omitted frame.
    assert next(widget for widget in app.text_input if widget.label == 'Timing').proto.id == identity
    next(widget for widget in app.text_input if widget.label == 'Source identifier').set_value('0007')
    next(widget for widget in app.text_area if widget.label == 'Asset / recommendation').set_value('Replace motor')
    next(widget for widget in app.text_input if widget.label == 'Timing').set_value('Unknown')
    next(button for button in app.button if button.label == 'Close editing').click().run()
    result = current(app, key)
    assert not app.exception and not app.dataframe and result.source == 'This month'
    assert result.extra_tables[0].columns == frame.columns
    assert result.extra_tables[0].reference == frame.reference
    assert result.extra_tables[0].rows == (('0007', 'Replace motor', 'Unknown', ''),)
    assert result.references == incoming.references
