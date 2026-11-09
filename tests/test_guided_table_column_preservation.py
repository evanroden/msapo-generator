"""The guided grid retains the physical cells accepted in Starting Report review."""
from dataclasses import replace
from io import BytesIO
import json

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_content_policy import table_has_pricing
from app.monthly_report_editor import _signature
from app.monthly_report_import import inspect_docx, imported_draft
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportTable, ResolvedBlock,
    SectionSpec, synthetic_profiles,
)
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_sections import section_reviews, build_section_import


APP = '''
import streamlit as st
from dataclasses import replace
from app.monthly_report_guided import _edit_content
from app.monthly_report_ui import _field
draft=st.session_state['draft']
block=draft.blocks[0]
spec=draft.sections[0].blocks[0]
changed=_edit_content(spec,block,None,'probe',{},_field,draft)
st.session_state['draft']=replace(draft,blocks=(changed,*draft.blocks[1:]))
'''

REVIEW = '''
import streamlit as st
from app.monthly_report_section_ui import _section_card
from app.monthly_report_ui import _field
from app.monthly_report_model import ReportPeriod
plans=st.session_state.setdefault('plans',{})
_section_card(st.session_state['section'],st.session_state['path'],st.session_state['inspection'],
              ReportPeriod(2026,9),'source_probe',_field,plans,True)
'''


def report(table, *, key='water_monthly_update', source='This month'):
    spec = BlockSpec(key, 'rich_text' if key == 'water_monthly_update' else 'table')
    section = SectionSpec('water', '7', 'Water Treatment Reports', (spec,))
    block = ResolvedBlock(key, source, extra_tables=(table,), references=('manual-context',))
    sibling = ResolvedBlock('activity_summary', 'This month', text='Independent manual work.')
    return ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), 'Synthetic Editor',
                       (section,), (block, sibling))


def start(draft, *, old_seed=None):
    app = AppTest.from_string(APP)
    app.session_state['draft'] = draft
    if old_seed is not None:
        key = 'probe_edit_' + draft.blocks[0].key + '_imported_0_' + _signature(draft.blocks[0].extra_tables[0].columns)
        app.session_state[key + '_data'] = old_seed
        app.session_state[key + '_data_seed'] = old_seed
    app.run()
    assert not app.exception
    return app


def current(app):
    return app.session_state['draft'].blocks[0].extra_tables[0]


def wire(app, *, edited=None, added=None, deleted=None):
    # Deliver real native data_editor wire state; do not replace _grid.
    frame = app.dataframe[-1]
    message = app._tree.get_widget_states()
    for old in list(message.widgets):
        if old.id == frame.proto.id:
            message.widgets.remove(old)
    message.widgets.add(id=frame.proto.id, string_value=json.dumps({
        'edited_rows': edited or {}, 'added_rows': added or [], 'deleted_rows': deleted or []}))
    app._run(message)
    assert not app.exception


@pytest.mark.parametrize('columns', [
    ('Reading', 'Reading (2)', 'Reading (2)'),
    ('Reading', 'Reading', '1. Reading'),
    ('', '', '1. '),
    ('Value', '2. Value', 'Value'),
])
@pytest.mark.parametrize('source', ['This month', 'Omit'])
def test_passive_grid_preserves_every_physical_cell_and_omission(columns, source):
    table = ReportTable(columns, (('pump P-001', '0', 'pending'), ('pump P-002', '17', 'review')), 'synthetic:table')
    draft = report(table, source=source)
    app = start(draft)
    frame = app.dataframe[-1].value
    assert frame.shape == (2, 3)
    assert tuple(map(tuple, frame.values)) == table.rows
    assert len(set(frame.columns)) == 3
    assert current(app) == table
    assert app.session_state['draft'] == draft
    identity = app.dataframe[-1].proto.id
    wire(app)
    assert app.dataframe[-1].proto.id == identity
    assert app.session_state['draft'] == draft


@pytest.mark.parametrize('key', ['water_monthly_update', 'capital_renewal'])
@pytest.mark.parametrize('source', ['This month', 'Omit'])
def test_native_corrections_blanks_and_row_changes_stay_column_specific(key, source):
    table = ReportTable(('Reading', 'Reading', '1. Reading'),
                        (('A', 'B', 'C'), ('D', 'E', 'F')), 'synthetic:retained')
    draft = report(table, key=key, source=source)
    app = start(draft)
    labels = tuple(app.dataframe[-1].value.columns)
    wire(app, edited={'0': {labels[0]: 'corrected-A', labels[1]: ''}},
         added=[dict(zip(labels, ('0', '', 'kW')))], deleted=[1])
    expected = replace(table, rows=(('corrected-A', '', 'C'), ('0', '', 'kW')))
    assert current(app) == expected
    result = app.session_state['draft']
    assert result.blocks[0].source == 'This month'
    assert result.blocks[0].references == draft.blocks[0].references
    assert result.blocks[1:] == draft.blocks[1:] and result.profile == draft.profile
    reopened = start(result)
    assert current(reopened) == expected
    assert tuple(map(tuple, reopened.dataframe[-1].value.values)) == expected.rows


def test_legacy_collapsed_seed_cannot_rewrite_intact_canonical_columns():
    table = ReportTable(('Reading', 'Reading'), (('first', 'second'),), 'synthetic:retained')
    app = start(report(table), old_seed=[{'Reading': 'old-collapsed'}])
    assert current(app) == table
    assert tuple(map(tuple, app.dataframe[-1].value.values)) == table.rows


def test_ordinary_unique_columns_keep_existing_native_key_and_labels():
    table = ReportTable(('Equipment', 'Reading', 'Status'), (('pump', '0', 'pending'),))
    app = start(report(table))
    key = 'probe_edit_water_monthly_update_imported_0_' + _signature(table.columns)
    assert app.dataframe[-1].proto.id.endswith('-' + key)
    assert tuple(app.dataframe[-1].value.columns) == table.columns
    assert current(app) == table
    wire(app, edited={'0': {'Reading': '17'}})
    assert current(app).rows == (('pump', '17', 'pending'),)


@pytest.mark.parametrize('rows', [(), (('', '', ''),)])
def test_empty_optional_frame_keeps_original_schema_without_phantom_content(rows):
    table = ReportTable(('Reading', 'Reading', 'Status'), rows, 'synthetic:empty')
    draft = report(table, key='capital_renewal')
    app = start(draft)
    next(b for b in app.button if b.label == 'Add capital item').click().run()
    assert not app.exception
    assert current(app) == table
    wire(app)
    assert current(app) == table


def test_price_evidence_in_earlier_duplicate_cell_is_retained_for_existing_gate():
    table = ReportTable(('Reading', 'Reading', 'Status'), (('$500', 'pump P-001', 'pending'),))
    assert table_has_pricing(table.columns, table.rows)
    app = start(report(table))
    assert current(app) == table
    assert table_has_pricing(current(app).columns, current(app).rows)


def reviewed_docx(tmp_path, unique=False):
    path = tmp_path / 'synthetic-water-readings.docx'
    document = Document()
    document.add_heading('7 Water Treatment Reports', 1)
    source = document.add_table(rows=3, cols=3)
    columns = ('Equipment', 'Reading', 'Status') if unique else ('Reading', 'Reading', 'Reading (2)')
    values = (columns, ('pump P-001', '0', 'pending'), ('pump P-002', '17', 'review'))
    for row, cells in zip(source.rows, values):
        for cell, value in zip(row.cells, cells):
            cell.text = value
    document.save(path)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    section = next(s for s in section_reviews(inspection) if s.key == 'water')
    app = AppTest.from_string(REVIEW)
    app.session_state['section'] = section
    app.session_state['path'] = path
    app.session_state['inspection'] = inspection
    app.run()
    assert not app.exception
    plan = app.session_state['plans']['water']
    mapped, _ = build_section_import(path, inspection, (plan,))
    draft = imported_draft(synthetic_profiles()[0], ReportPeriod(2026, 9), 'Synthetic Editor', mapped)
    table = draft.blocks[0].extra_tables[0]
    assert table.rows == values[1:]
    assert table.columns == (columns if unique else ('Reading', 'Reading (2)', 'Reading (2)'))
    assert table.reference.startswith('docx:' + inspection.sha256 + ':')
    return path, original, draft


def word_tables(raw):
    return [[tuple(c.text for c in row.cells) for row in table.rows]
            for table in Document(BytesIO(raw)).tables]


@pytest.mark.parametrize('unique', [False, True])
def test_real_reviewed_docx_through_guided_editor_and_internal_word_keeps_readings(tmp_path, unique):
    path, original, draft = reviewed_docx(tmp_path, unique)
    table = draft.blocks[0].extra_tables[0]
    app = start(draft)
    edited = app.session_state['draft']
    # Check actual emitted values before comparing canonical objects.
    output = _build_native_docx(edited, path, section_key='water')
    exported = word_tables(output)
    assert any(rows[1:] == list(table.rows) for rows in exported)
    # Unchanged native content retains its source heading spelling, while
    # canonical review headings keep the adapter's existing disambiguation.
    original_headers = tuple(cell.text for cell in Document(path).tables[0].rows[0].cells)
    assert [original_headers, *table.rows] in exported
    assert edited == draft
    assert path.read_bytes() == original


def test_public_storage_history_and_public_word_keep_distinct_cells(tmp_path, monkeypatch):
    """Required actual Linux persistence/public output; no replacement or skip."""
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    path, original, draft = reviewed_docx(tmp_path)
    previous = library.save_snapshot(draft, expected_revision=0, entered_editor='Synthetic Editor')
    app = start(library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft)
    labels = tuple(app.dataframe[-1].value.columns)
    wire(app, edited={'0': {labels[0]: 'pump corrected', labels[1]: '19'}})
    edited = app.session_state['draft']
    expected = replace(draft.blocks[0].extra_tables[0], rows=(('pump corrected', '19', 'pending'), ('pump P-002', '17', 'review')))
    library.save_snapshot(edited, expected_revision=previous.revision, entered_editor='Synthetic Editor')
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft
    assert reopened.blocks[0].extra_tables[0] == expected
    assert library.load_snapshot_version(draft.profile.contract, draft.profile.key, draft.period, previous.revision).draft == previous.draft
    assert [expected.columns, *expected.rows] in word_tables(build_native_docx(reopened, path, section_key='water'))
    assert path.read_bytes() == original
