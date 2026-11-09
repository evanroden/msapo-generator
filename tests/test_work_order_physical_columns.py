"""Dedicated work-order grids preserve physical cells and row occurrences."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_import import inspect_docx, imported_draft
from app.monthly_report_model import ReportPeriod, ReportTable, ResolvedBlock, synthetic_profiles
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_sections import section_reviews, build_section_import
from test_work_order_imported_rows import APP, current, launch
from test_work_order_row_insertion import ABOVE, BELOW, wire


KEY = 'row_probe_edit_work_orders_imported_0_row_editor'
TABLE = ReportTable(('Work orders', 'Jan', 'Jan (3)', 'Jan (3)'),
                    (('Received', '0', '17', 'pending'), ('Closed', '2', '19', 'review')),
                    'synthetic:source-table')
BLANK = ('',) * 4
REVIEW = '''
import streamlit as st
from app.monthly_report_section_ui import _section_card
from app.monthly_report_ui import _field
from app.monthly_report_model import ReportPeriod
plans=st.session_state.setdefault('plans',{})
_section_card(st.session_state['section'],st.session_state['path'],st.session_state['inspection'],
              ReportPeriod(2026,9),'source_probe',_field,plans,True)
'''


def labels(app):
    state = app.session_state[KEY]
    return tuple(column for column in app.dataframe[0].value.columns
                 if column not in (state['identity'], state['action']))


@pytest.mark.parametrize('columns', [TABLE.columns, ('Value', 'Value', '1. Value', '2. Value'),
                                     ('', '', '1. ', ''),
                                     ('__work_order_row_id', '__work_order_row_id', '__work_order_row_action', 'Value')])
@pytest.mark.parametrize('source', ['Last month', 'Omit'])
def test_opening_and_rerun_preserve_all_physical_cells_and_source(columns, source):
    table = replace(TABLE, columns=columns)
    block = ResolvedBlock('work_orders', source, extra_tables=(table,), references=('manual-context',))
    app = AppTest.from_string(APP)
    app.session_state['block'] = block
    app.run()
    assert not app.exception
    displayed = labels(app)
    assert len(displayed) == len(set(displayed)) == 4
    assert tuple(map(tuple, app.dataframe[0].value[list(displayed)].values)) == table.rows
    assert app.session_state['block'] == block
    identity = app.dataframe[0].proto.id
    ids = app.session_state[KEY]['ids']
    wire(app)
    assert current(app) == table
    assert app.dataframe[0].proto.id == identity and app.session_state[KEY]['ids'] == ids


def test_native_edits_clears_additions_and_deletions_stay_column_specific():
    app = launch(TABLE)
    names = labels(app)
    assert len(names) == 4
    wire(app, edited={0: {names[1]: '', names[2]: '23'}},
         added=[dict(zip(names, ('Added', '0', '31', 'pending')))], deleted=[1])
    expected = (('Received', '', '23', 'pending'), ('Added', '0', '31', 'pending'))
    assert current(app).rows == expected
    wire(app)
    assert current(app) == replace(TABLE, rows=expected)
    app.session_state['show'] = False
    app.run()
    app.session_state['show'] = True
    app.run()
    assert current(app) == replace(TABLE, rows=expected)


@pytest.mark.parametrize('action,row,position', [(ABOVE, 0, 0), (BELOW, 1, 2)])
def test_insert_preserves_same_delivery_and_replayed_action_cannot_duplicate(action, row, position):
    app = launch(TABLE)
    names = labels(app)
    assert len(names) == 4
    old = app.dataframe[0].proto
    message = wire(app, row, action, edited={0: {names[2]: '23'}})
    expected = [('Received', '0', '23', 'pending'), TABLE.rows[1]]
    expected.insert(position, BLANK)
    assert current(app).rows == tuple(expected)
    app._run(message)
    assert not app.exception and current(app).rows == tuple(expected)
    wire(app)
    wire(app, row, action, proto=old, edited={0: {names[2]: 'retired'}})
    assert current(app).rows == tuple(expected)


def test_visible_menu_survives_acknowledgment_then_insert_uses_latest_values():
    app = launch(TABLE)
    names = labels(app)
    assert len(names) == 4
    old = app.dataframe[0].proto
    ids = app.session_state[KEY]['ids']
    wire(app, edited={1: {names[2]: '23'}})
    wire(app)
    assert app.dataframe[0].proto.id == old.id and app.session_state[KEY]['ids'] == ids
    wire(app, 1, ABOVE, proto=old, edited={1: {names[2]: '24'}})
    assert current(app).rows == (TABLE.rows[0], BLANK, ('Closed', '2', '24', 'review'))


@pytest.mark.parametrize('acknowledged', [False, True])
def test_interrupted_insert_keeps_newer_delivered_values(acknowledged):
    app = launch(TABLE)
    names = labels(app)
    assert len(names) == 4
    original = app.session_state['block']
    wire(app, 0, ABOVE, edited={1: {names[2]: '23'}})
    if not acknowledged:
        app.session_state['block'] = original
    wire(app, edited={1: {names[2]: '24'}})
    assert current(app).rows == (BLANK, TABLE.rows[0], ('Closed', '2', '24', 'review'))
    wire(app)
    assert current(app).rows == (BLANK, TABLE.rows[0], ('Closed', '2', '24', 'review'))


def test_duplicate_blank_rows_keep_occurrence_identity():
    table = replace(TABLE, rows=(BLANK, BLANK, TABLE.rows[0]))
    app = launch(table)
    names = labels(app)
    assert len(names) == 4
    wire(app, 1, ABOVE, edited={1: {names[2]: 'second occurrence'}})
    assert current(app).rows == (BLANK, BLANK, ('', '', 'second occurrence', ''), TABLE.rows[0])


def test_empty_artificial_slot_stays_empty_until_a_real_cell_edit():
    app = launch(replace(TABLE, rows=()))
    names = labels(app)
    assert len(names) == 4
    assert not current(app).rows
    wire(app, 0, ABOVE)
    assert not current(app).rows
    wire(app, edited={0: {names[2]: '0'}})
    assert current(app).rows == (('', '', '0', ''),)
    wire(app)
    wire(app, 0, BELOW)
    assert current(app).rows == (('', '', '0', ''), BLANK)


@pytest.mark.parametrize('duplicate', [False, True])
def test_legacy_seed_retirement_only_affects_duplicate_columns(duplicate):
    table = TABLE if duplicate else replace(TABLE, columns=('Work orders', 'Jan', 'Feb', 'Mar'))
    app = launch(table)
    state = app.session_state[KEY]
    old_epoch, old_ids = state['epoch'], state['ids']
    state.pop('columns', None)
    # Exact pre-fix cache shape, with the intact canonical report still saved.
    state['table'], state['pending'], state['intent'] = table, None, None
    state['seed'] = [dict(zip(table.columns, row)) | {
        state['identity']: identity, state['action']: [ABOVE, BELOW]}
        for row, identity in zip(table.rows, state['ids'])]
    old_key = 'row_probe_edit_work_orders_imported_0_' + old_epoch
    app.session_state[old_key + '_data'] = state['seed']
    app.session_state[old_key + '_data_seed'] = state['seed']
    app.session_state[KEY] = state
    app.session_state['block'] = replace(app.session_state['block'], extra_tables=(table,))
    wire(app)
    assert current(app) == table
    if duplicate:
        assert app.session_state[KEY]['epoch'] != old_epoch
        assert old_key + '_data' not in app.session_state and old_key + '_data_seed' not in app.session_state
    else:
        assert app.session_state[KEY]['epoch'] == old_epoch and app.session_state[KEY]['ids'] == old_ids
        assert labels(app) == table.columns


def reviewed_docx(tmp_path, unique=False):
    path = tmp_path / 'synthetic-work-order-counts.docx'
    document = Document()
    document.add_heading('2 Monthly Activity Summary', 1)
    source = document.add_table(rows=3, cols=4)
    columns = ('Work orders', 'Jan', 'Jan', 'Jan (2)' if unique else 'Jan (3)')
    for row, cells in zip(source.rows, (columns, *TABLE.rows)):
        for cell, value in zip(row.cells, cells):
            cell.text = value
    document.save(path)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    section = next(s for s in section_reviews(inspection) if s.key == 'activity')
    review = AppTest.from_string(REVIEW)
    for key, value in (('section', section), ('path', path), ('inspection', inspection)):
        review.session_state[key] = value
    review.run()
    assert not review.exception
    mapped, _ = build_section_import(path, inspection, (review.session_state['plans']['activity'],))
    draft = imported_draft(synthetic_profiles()[0], ReportPeriod(2026, 9), 'Synthetic Editor', mapped)
    block = next(b for b in draft.blocks if b.key == 'work_orders')
    assert block.extra_tables[0].rows == TABLE.rows
    assert block.extra_tables[0].columns == (('Work orders', 'Jan', 'Jan (3)', 'Jan (2)') if unique else TABLE.columns)
    return path, original, draft, block


def exported_rows(raw):
    return [[tuple(cell.text for cell in row.cells) for row in table.rows]
            for table in Document(BytesIO(raw)).tables]


@pytest.mark.parametrize('unique', [False, True])
def test_real_starting_report_review_editor_and_word_preserve_physical_values(tmp_path, unique):
    path, original, draft, block = reviewed_docx(tmp_path, unique)
    app = launch(block.extra_tables[0])
    edited = replace(draft, blocks=tuple(replace(b, extra_tables=(current(app),))
                                        if b.key == 'work_orders' else b for b in draft.blocks))
    tables = exported_rows(_build_native_docx(edited, path, section_key='activity'))
    assert any(rows[1:] == list(TABLE.rows) for rows in tables)
    assert current(app) == block.extra_tables[0] and edited == draft
    assert path.read_bytes() == original


def test_public_storage_history_reopen_and_word_keep_distinct_values(monkeypatch, tmp_path):
    """Enabled real Linux persistence/public Word; no persistence seams/skips."""
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    path, original, draft, block = reviewed_docx(tmp_path)
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor='Synthetic Editor')
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft
    app = launch(next(b for b in reopened.blocks if b.key == 'work_orders').extra_tables[0])
    names = labels(app)
    wire(app, 0, ABOVE, edited={1: {names[2]: '24'}})
    expected = replace(block.extra_tables[0], rows=(BLANK, TABLE.rows[0], ('Closed', '2', '24', 'review')))
    assert current(app) == expected
    edited = replace(reopened, blocks=tuple(replace(b, extra_tables=(current(app),))
                                            if b.key == 'work_orders' else b for b in reopened.blocks))
    library.save_snapshot(edited, expected_revision=saved.revision, entered_editor='Synthetic Editor')
    restored = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft
    assert next(b for b in restored.blocks if b.key == 'work_orders').extra_tables[0] == expected
    assert library.load_snapshot_version(draft.profile.contract, draft.profile.key, draft.period, saved.revision) == saved
    assert [expected.columns, *expected.rows] in exported_rows(build_native_docx(restored, path, section_key='activity'))
    assert path.read_bytes() == original
