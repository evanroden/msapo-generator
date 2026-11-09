"""An annual requirement addition must first consume the current native grid."""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_library as library
from app import monthly_report_training as training
from app import monthly_report_training_ui as ui
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable, ResolvedBlock, default_sections,
)
from app.monthly_report_native_layout import _build_native_docx, build_native_docx


PROFILE = ReportProfile('Synthetic Training Contract', 'combined', 'Synthetic Sites', (
    Facility('north', 'Synthetic North'), Facility('south', 'Synthetic South')), scope_type='multi_site')
SCRIPT = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_training_ui import render_training
from app.monthly_report_ui import _field
blocks = render_training(st.session_state['draft'], st.session_state['blocks'], 'capture', _field)
st.session_state['blocks'] = blocks
st.session_state['draft'] = replace(st.session_state['draft'], blocks=tuple(blocks.values()))
'''


def matrix(year=None):
    return ReportTable(('Team member', 'Site', 'Safety'), (
        ('Synthetic Learner', 'Synthetic North', 'Pending'),
        ('Synthetic Colleague', 'Synthetic South', 'Completed'),
    ), training.MATRIX_REF if year is None else training.year_matrix_reference(year))


def report(table, *, period=None):
    period = period or ReportPeriod(2026, 9)
    event = training.add_event(None, title='Current monthly session', when=period.start,
        mode='In person', participants=['Synthetic Learner'], hours='1.25', period=period)
    block = ResolvedBlock('training_summary', 'This month', text='Keep monthly note', extra_tables=(table, event))
    return ReportDraft(PROFILE, period, 'Synthetic Editor',
        (next(s for s in default_sections() if s.key == 'training'),), (block,))


def _record(value, table):
    result = deepcopy(value)
    sites = {facility.key: {'columns': list(table.columns[2:]),
        'rows': [[row[0], *row[2:]] for row in table.rows if row[1] == facility.title]}
        for facility in PROFILE.facilities}
    year = training.matrix_year(table.reference)
    if year is None:
        result['sites'] = sites
    else:
        result.setdefault('years', {})[str(year)] = {'sites': sites}
    return result


class StandingCapture:
    """Explicit in-memory read/save seam, not disk, locks or CAS acceptance."""
    def __init__(self, table):
        self.value = _record({'schema': 1, 'revision': 1, 'sites': {}}, table)
        self.calls = []
        self.failure = None

    def load(self, contract):
        return deepcopy(self.value)

    def save(self, profile, table, *, expected_revision, actor):
        training.validate_matrix(table)
        if any(row[1] not in {f.title for f in profile.facilities} for row in table.rows):
            raise ValueError('Training rows must belong to this report\'s selected sites.')
        if self.failure:
            raise self.failure
        assert expected_revision == self.value['revision']
        self.calls.append(table)
        self.value = _record(self.value, table)
        self.value['revision'] += 1
        return deepcopy(self.value)


def open_app(monkeypatch, table, *, period=None, real_storage=False):
    store = None
    if not real_storage:
        monkeypatch.setattr(directory, 'load_directory', lambda *_: None)
        store = StandingCapture(table)
        monkeypatch.setattr(ui, 'load_training', store.load)
        monkeypatch.setattr(ui, 'save_training', store.save)
    draft = report(table, period=period)
    app = AppTest.from_string(SCRIPT)
    app.session_state['draft'] = draft
    app.session_state['blocks'] = {b.key: b for b in draft.blocks}
    app.run()
    assert not app.exception and not app.error
    return app, store


def widget(app, kind, label):
    return next(w for w in getattr(app, kind) if w.label == label)


def current(app):
    return next(t for t in app.session_state['blocks']['training_summary'].extra_tables
                if training.is_matrix_reference(t.reference))


def prepare(app, name='Orientation'):
    widget(app, 'text_input', 'Requirement name').set_value(name).run()
    assert not app.exception and not app.error


def deliver(app, *, edits=None, added=(), deleted=()):
    grid = next(g for g in app.dataframe if '_grid_' in g.key)
    app.session_state[grid.key] = {'edited_rows': edits or {}, 'added_rows': list(added), 'deleted_rows': list(deleted)}
    return grid.key


def add(app):
    widget(app, 'button', 'Add requirement').click().run()
    assert not app.exception


def captured_cell(app, grid, column):
    # AppTest's dataframe.value is the unchanged native seed. The client applies
    # its edit delta to that seed; _grid records the actual returned cell values.
    return app.session_state[grid.key + '_data'][0][column]


def design(tmp_path):
    path = tmp_path / 'synthetic-training-design.docx'
    document = Document()
    document.add_heading('11 Training Summary', 1)
    document.add_paragraph('Old placeholder')
    table = document.add_table(rows=2, cols=4)
    for cell, text in zip(table.rows[0].cells, ('Team member', 'Site', 'Safety', 'Orientation')):
        cell.text = text
    for cell in table.rows[1].cells:
        cell.text = 'Old placeholder'
    document.save(path)
    return path


@pytest.mark.parametrize('value', ['Completed', '', 'Not required'])
@pytest.mark.parametrize('year', [None, 2026])
def test_add_captures_status_or_clear_before_new_column_and_word(monkeypatch, tmp_path, value, year):
    original = matrix(year)
    app, store = open_app(monkeypatch, original)
    prepare(app)
    old_key = deliver(app, edits={0: {'Safety': value}})
    event = training.events_for_period(app.session_state['blocks']['training_summary'], app.session_state['draft'].period)
    widget(app, 'text_area', 'Training notes').set_value('Delivered monthly note')
    add(app)
    assert not app.error
    expected = replace(original, columns=(*original.columns, 'Orientation'), rows=(
        (*original.rows[0][:2], value, 'Not recorded'), (*original.rows[1], 'Not recorded')))
    assert current(app) == expected and store.calls[-1] == expected
    assert next(g for g in app.dataframe if '_grid_' in g.key).key != old_key
    assert next(g for g in app.dataframe if '_grid_' in g.key).value.iloc[0]['Safety'] == value
    assert app.session_state['blocks']['training_summary'].text == 'Delivered monthly note'
    assert training.events_for_period(app.session_state['blocks']['training_summary'], app.session_state['draft'].period) == event
    path = design(tmp_path)
    before = path.read_bytes()
    output = Document(BytesIO(_build_native_docx(app.session_state['draft'], path, section_key='training')))
    exported = next(t for t in output.tables if tuple(c.text for c in t.rows[0].cells) == expected.columns)
    assert tuple(tuple(c.text for c in row.cells) for row in exported.rows[1:]) == expected.rows
    assert path.read_bytes() == before
    prior_calls = tuple(store.calls)
    app.run()
    assert not app.exception and current(app) == expected and tuple(store.calls) == prior_calls


@pytest.mark.parametrize('action', ['add_row', 'delete_row', 'site', 'name'])
def test_add_keeps_structural_and_identity_edits(monkeypatch, action):
    original = matrix()
    app, store = open_app(monkeypatch, original)
    prepare(app)
    rows = list(original.rows)
    if action == 'add_row':
        row = ('Synthetic New Learner', 'Synthetic North', 'Completed')
        deliver(app, added=[dict(zip(original.columns, row))])
        rows.append(row)
    elif action == 'delete_row':
        deliver(app, deleted=[1])
        rows.pop(1)
    else:
        column, value = ('Site', 'Synthetic South') if action == 'site' else ('Team member', 'Corrected Learner')
        deliver(app, edits={0: {column: value}})
        cells = list(rows[0]); cells[original.columns.index(column)] = value; rows[0] = tuple(cells)
    add(app)
    expected = replace(original, columns=(*original.columns, 'Orientation'), rows=tuple((*row, 'Not recorded') for row in rows))
    assert not app.error and current(app) == expected and store.calls[-1] == expected


@pytest.mark.parametrize('name', ['Safety', 'sAfEtY', 'Team  member'])
def test_rejected_requirement_keeps_delivered_grid_reachable(monkeypatch, name):
    app, store = open_app(monkeypatch, matrix())
    prepare(app, name)
    old_key = deliver(app, edits={0: {'Safety': 'Completed'}})
    add(app)
    assert app.error
    grid = next(g for g in app.dataframe if '_grid_' in g.key)
    assert grid.key == old_key and captured_cell(app, grid, 'Safety') == 'Completed'
    assert 'Orientation' not in current(app).columns
    # Correct the rejected name; the existing native edit must still survive.
    widget(app, 'text_input', 'Requirement name').set_value('Orientation').run()
    add(app)
    assert not app.error and current(app).rows[0][2:] == ('Completed', 'Not recorded')


@pytest.mark.parametrize('failure', [OSError('Synthetic storage unavailable'), library.RevisionConflict('Synthetic newer revision')])
def test_failed_add_keeps_visible_grid_and_retry_without_stale_replay(monkeypatch, failure):
    original = matrix()
    app, store = open_app(monkeypatch, original)
    prepare(app)
    old_key = deliver(app, edits={0: {'Safety': 'Completed'}})
    store.failure = failure
    add(app)
    assert app.error and not store.calls
    grid = next(g for g in app.dataframe if '_grid_' in g.key)
    assert grid.key == old_key and captured_cell(app, grid, 'Safety') == 'Completed'
    assert current(app) == original
    store.failure = None
    # The existing UI clears its conflict display once the exact retry succeeds.
    add(app)
    assert not app.exception and current(app).rows[0][2:] == ('Completed', 'Not recorded')
    calls = tuple(store.calls)
    app.run()
    assert tuple(store.calls) == calls


def test_year_transition_after_add_preserves_old_year_and_resets_only_new_year(monkeypatch):
    original = matrix(2026)
    app, store = open_app(monkeypatch, original, period=ReportPeriod(2027, 1))
    prepare(app)
    deliver(app, edits={0: {'Safety': 'Completed'}})
    add(app)
    old = deepcopy(store.value['years']['2026'])
    assert current(app).reference == original.reference and current(app).rows[0][2] == 'Completed'
    widget(app, 'button', 'Start 2027 requirements').click().run()
    assert not app.exception and not app.error
    assert current(app).reference == training.year_matrix_reference(2027)
    assert current(app).rows[0][2:] == ('Not recorded', 'Not recorded')
    assert store.value['years']['2026'] == old


@pytest.mark.parametrize('year', [None, 2026])
@pytest.mark.parametrize('action', ['status_only', 'add_only'])
def test_ordinary_status_and_requirement_controls_remain_unchanged(monkeypatch, year, action):
    original = matrix(year)
    app, store = open_app(monkeypatch, original)
    assert not store.calls and current(app) == original
    assert widget(app, 'button', 'Add requirement').disabled
    if action == 'status_only':
        deliver(app, edits={0: {'Safety': 'Completed'}})
        app.run()
        expected = replace(original, rows=((*original.rows[0][:2], 'Completed'), original.rows[1]))
    else:
        prepare(app)
        add(app)
        expected = replace(original, columns=(*original.columns, 'Orientation'),
            rows=tuple((*row, 'Not recorded') for row in original.rows))
    assert not app.exception and not app.error and current(app) == expected
    assert store.calls == [expected]
    app.run()
    assert store.calls == [expected] and current(app) == expected


def test_repeated_add_action_does_not_duplicate_requirement_or_write(monkeypatch):
    app, store = open_app(monkeypatch, matrix())
    prepare(app)
    add(app)
    expected, calls = current(app), tuple(store.calls)
    add(app)
    assert app.error and current(app) == expected and tuple(store.calls) == calls
    assert current(app).columns.count('Orientation') == 1


@pytest.mark.parametrize('year', [None, 2026])
def test_public_storage_add_preserves_real_standing_report_history_and_word(monkeypatch, tmp_path, year):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    original = matrix(year)
    draft = report(original)
    standing = training.save_training(PROFILE, original, expected_revision=0, actor=draft.prepared_by)
    saved = library.save_snapshot(draft, expected_revision=0)
    app, _ = open_app(monkeypatch, original, real_storage=True)
    prepare(app)
    deliver(app, edits={0: {'Safety': 'Completed'}})
    add(app)
    assert not app.error and current(app).rows[0][2:] == ('Completed', 'Not recorded')
    updated = app.session_state['draft']
    second = library.save_snapshot(updated, expected_revision=1)
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, draft.period)
    assert reopened == second and reopened.draft == updated
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, draft.period, 1) == saved
    root = training._path(PROFILE.contract)
    assert library._read(root / 'history' / '00000001.json') == standing
    current_standing = training.load_training(PROFILE.contract)
    assert current_standing['revision'] > standing['revision']
    output = Document(BytesIO(build_native_docx(reopened.draft, design(tmp_path), section_key='training')))
    table = next(t for t in output.tables if t.rows[0].cells[0].text == 'Team member')
    assert tuple(c.text for c in table.rows[1].cells)[2:] == ('Completed', 'Not recorded')


def test_public_storage_concurrent_change_refuses_add_and_retains_delivered_grid(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    original = matrix(2026)
    training.save_training(PROFILE, original, expected_revision=0, actor='Synthetic Editor')
    app, _ = open_app(monkeypatch, original, real_storage=True)
    prepare(app)
    old_key = deliver(app, edits={0: {'Safety': 'Not required'}})
    newer = training.save_training(PROFILE, replace(original, rows=(
        (*original.rows[0][:2], 'Completed'), original.rows[1])), expected_revision=1, actor='Synthetic Colleague')
    add(app)
    assert app.error and current(app) == original
    assert training.load_training(PROFILE.contract) == newer
    grid = next(g for g in app.dataframe if '_grid_' in g.key)
    assert grid.key == old_key and captured_cell(app, grid, 'Safety') == 'Not required'
