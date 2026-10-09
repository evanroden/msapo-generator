"""Audit F14: unrelated validation cannot remove monthly training work."""
from dataclasses import replace
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_training_ui as ui
from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable, ResolvedBlock, default_sections
from app.monthly_report_training import EVENT_REF, MATRIX_REF, add_event, load_training, save_training

NOTE = "TEST ONLY QA-TRAIN-RET-02: keep this note after adding a requirement."
APP = '''
import streamlit as st
from app.monthly_report_training_ui import render_training

def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
st.session_state['blocks'] = render_training(st.session_state['draft'], st.session_state['blocks'], 'test', field)
'''


def widget(app, kind, label):
    return next(w for w in getattr(app, kind) if w.label == label)


def current(app):
    return app.session_state['blocks']['training_summary']


@pytest.fixture
def training(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    from app import monthly_report_directory
    monkeypatch.setattr(monthly_report_directory, 'load_directory', lambda *_: None)
    profile = ReportProfile('Synthetic Retention', 'north', 'Synthetic North', (Facility('north', 'Synthetic North'),))
    period = ReportPeriod(2026, 9)
    matrix = ReportTable(('Team member', 'Site', 'TEST fire safety'), (('Synthetic Hospital Tech', 'Synthetic North', 'Not recorded'),), MATRIX_REF)
    event = add_event(None, title='Accepted safety event', when=date(2026, 9, 1), mode='In person', participants=['Synthetic Hospital Tech'], hours='0.75', period=period)
    block = ResolvedBlock('training_summary', 'This month', text=NOTE, extra_tables=(matrix, event), references=('synthetic:reviewed-training',))
    draft = ReportDraft(profile, period, 'Synthetic Editor', default_sections(), (block,))
    stored = save_training(profile, matrix, expected_revision=0, actor=draft.prepared_by)
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state['draft'] = draft
    app.session_state['blocks'] = {block.key: block}
    app.run()
    assert not app.exception and not app.error
    return app, draft, matrix, event, stored, saved


def assert_work(app, note=NOTE):
    assert not app.exception
    assert current(app).text == note
    assert widget(app, 'text_area', 'Training notes').value == note
    assert widget(app, 'text_input', 'Training topic') is not None
    assert widget(app, 'button', 'Add completed training') is not None


def test_invalid_event_keeps_notes_visible_and_saved_history_unchanged(training):
    app, draft, matrix, event, stored, saved = training
    widget(app, 'button', 'Add completed training').click().run()
    assert app.error
    assert_work(app)
    assert current(app).extra_tables == (matrix, event)
    assert load_training(draft.profile.contract) == stored
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved


@pytest.mark.parametrize('new_note', ['Corrected current note, not the saved wording.', ''])
def test_note_edit_in_same_event_as_validation_is_not_lost(training, new_note):
    app, *_ = training
    widget(app, 'text_area', 'Training notes').set_value(new_note)
    widget(app, 'button', 'Add completed training').click().run()
    assert app.error
    assert_work(app, new_note)
    app.run()
    assert_work(app, new_note)


def test_invalid_event_inputs_survive_until_corrected(training):
    app, draft, matrix, event, *_ = training
    widget(app, 'text_input', 'Training topic').set_value('New safety topic')
    widget(app, 'multiselect', 'Participants').set_value(['Synthetic Hospital Tech'])
    widget(app, 'text_input', 'Hours (leave blank if unknown)').set_value('invalid')
    widget(app, 'button', 'Add completed training').click().run()
    assert app.error
    assert_work(app)
    app.run()
    assert widget(app, 'text_input', 'Training topic').value == 'New safety topic'
    assert widget(app, 'multiselect', 'Participants').value == ['Synthetic Hospital Tech']
    widget(app, 'text_input', 'Hours (leave blank if unknown)').set_value('0.75')
    widget(app, 'button', 'Add completed training').click().run()
    assert not app.error
    assert_work(app)
    rows = next(t.rows for t in current(app).extra_tables if t.reference == EVENT_REF)
    assert len(rows) == 2 and rows[-1] == ('New safety topic', '2026-09-01', 'In person', 'Synthetic Hospital Tech', '0.75')
    app.run()
    assert len(next(t.rows for t in current(app).extra_tables if t.reference == EVENT_REF)) == 2


def test_missing_site_error_does_not_hide_notes_or_events(training, monkeypatch):
    app, draft, matrix, event, stored, *_ = training
    original = ui._grid
    monkeypatch.setattr(ui, '_grid', lambda key, rows, **kw: [dict(row, Site='') for row in rows])
    widget(app, 'text_area', 'Training notes').set_value('Current edit during a matrix error.')
    app.run()
    assert app.error
    assert_work(app, 'Current edit during a matrix error.')
    assert current(app).extra_tables == (matrix, event)
    assert load_training(draft.profile.contract) == stored
    monkeypatch.setattr(ui, '_grid', original)
    app.run()
    assert not app.error
    assert_work(app, 'Current edit during a matrix error.')


def test_invalid_event_then_first_and_later_columns_preserves_notes(training):
    app, draft, matrix, event, *_ = training
    widget(app, 'button', 'Add completed training').click().run()
    assert_work(app)
    for title in ('TEST lockout', 'TEST additional requirement'):
        widget(app, 'text_input', 'Add a training requirement').set_value(title).run()
        widget(app, 'button', 'Add training column').click().run()
        assert not app.exception and not app.error
        assert_work(app)
        assert event in current(app).extra_tables
    saved_matrix = next(t for t in current(app).extra_tables if t.reference == MATRIX_REF)
    assert saved_matrix.columns == (*matrix.columns, 'TEST lockout', 'TEST additional requirement')
    assert saved_matrix.rows[0][2:] == ('Not recorded',) * 3


def test_column_storage_error_preserves_pending_note_and_event_form(training, monkeypatch):
    app, *_ = training
    def fail(*args, **kwargs):
        raise OSError('Synthetic storage failure')
    monkeypatch.setattr(ui, 'save_training', fail)
    widget(app, 'text_input', 'Add a training requirement').set_value('Unsaved requirement').run()
    widget(app, 'text_area', 'Training notes').set_value('Retain despite a failed standing write.')
    widget(app, 'button', 'Add training column').click().run()
    assert app.error
    assert_work(app, 'Retain despite a failed standing write.')
    assert not app.success


def test_conflict_reload_preserves_current_note_not_just_older_block(training, monkeypatch):
    app, draft, matrix, event, *_ = training
    latest_matrix = replace(matrix, rows=(('Synthetic Hospital Tech', 'Synthetic North', 'Pending'),))
    latest = save_training(draft.profile, latest_matrix, expected_revision=1, actor='Other Editor')
    original = ui._grid
    monkeypatch.setattr(ui, '_grid', lambda key, rows, **kw: [dict(row, **{'TEST fire safety': 'Completed'}) for row in rows])
    widget(app, 'text_area', 'Training notes').set_value('Latest note entered during conflict.')
    app.run()
    assert app.error
    assert_work(app, 'Latest note entered during conflict.')
    assert event in current(app).extra_tables
    assert load_training(draft.profile.contract) == latest
    monkeypatch.setattr(ui, '_grid', original)
    widget(app, 'button', 'Reload saved training matrix').click().run()
    assert not app.error
    assert_work(app, 'Latest note entered during conflict.')
    assert latest_matrix in current(app).extra_tables
    assert event in current(app).extra_tables


def test_empty_event_error_does_not_discard_successful_matrix_write(training):
    app, draft, matrix, event, *_ = training
    widget(app, 'text_input', 'Add a training requirement').set_value('TEST next').run()
    widget(app, 'button', 'Add training column').click().run()
    accepted = current(app)
    widget(app, 'button', 'Add completed training').click().run()
    assert app.error
    assert_work(app)
    assert current(app) == accepted


def test_valid_note_clear_is_not_repopulated_by_column_change(training):
    app, *_ = training
    widget(app, 'text_area', 'Training notes').set_value('').run()
    widget(app, 'text_input', 'Add a training requirement').set_value('TEST next').run()
    widget(app, 'button', 'Add training column').click().run()
    assert_work(app, '')


def test_shared_read_failure_preserves_matrix_notes_and_accepted_events(training, monkeypatch):
    app, draft, matrix, event, *_ = training
    for key in list(app.session_state.filtered_state):
        if key.startswith('test_training_') and key.endswith('_saved'):
            del app.session_state[key]
    def fail(*args, **kwargs):
        raise OSError('Synthetic read failure')
    monkeypatch.setattr(ui, 'load_training', fail)
    widget(app, 'text_area', 'Training notes').set_value('Current note during read failure.')
    app.run()
    assert app.error
    assert_work(app, 'Current note during read failure.')
    assert current(app).extra_tables == (matrix, event)
    assert not app.success


def test_failed_column_write_does_not_publish_a_false_new_requirement(training, monkeypatch):
    app, draft, matrix, event, stored, *_ = training
    def fail(*args, **kwargs):
        raise OSError('Synthetic write failure')
    monkeypatch.setattr(ui, 'save_training', fail)
    widget(app, 'text_input', 'Add a training requirement').set_value('Must not appear saved').run()
    widget(app, 'button', 'Add training column').click().run()
    assert app.error
    assert_work(app)
    assert current(app).extra_tables == (matrix, event)
    assert load_training(draft.profile.contract) == stored
    assert widget(app, 'text_input', 'Add a training requirement').value == 'Must not appear saved'


def test_remove_event_remains_deliberate_and_does_not_change_matrix_status(training):
    app, _, matrix, event, *_ = training
    widget(app, 'multiselect', 'Remove a training entry').set_value([0])
    widget(app, 'button', 'Remove selected entries').click().run()
    assert not app.error
    assert_work(app)
    assert current(app).extra_tables == (matrix,)


def test_source_assets_and_provenance_survive_error_recovery(training):
    app, *_ = training
    original = replace(current(app), asset_hashes=('synthetic-picture',), asset_captions=('Keep this caption',))
    app.session_state['blocks'] = {original.key: original}
    app.run()
    widget(app, 'button', 'Add completed training').click().run()
    assert app.error
    assert_work(app)
    assert current(app).asset_hashes == original.asset_hashes
    assert current(app).asset_captions == original.asset_captions
    assert current(app).references == original.references


def test_ordered_report_validation_save_and_reopen_preserve_both_sections(monkeypatch, tmp_path):
    from app.contracts import RRH_CONTRACT
    from test_monthly_report_ui import monthly, choose_report, ROOT
    app = monthly(monkeypatch, tmp_path)
    widget(app, 'text_input', 'Prepared by').set_value('Synthetic Editor').run()
    widget(app, 'text_area', 'Activity summary').set_value('Independent Activity stays unchanged.').run()
    widget(app, 'text_area', 'Training notes').set_value(NOTE).run()
    widget(app, 'button', 'Save progress').click().run()
    historical = library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', ReportPeriod(2026, 9))
    historical_path = {p: p.read_bytes() for p in library._root().rglob('*.json')}
    correction = 'Training corrected in the same action as an invalid event.'
    widget(app, 'text_area', 'Training notes').set_value(correction)
    widget(app, 'button', 'Add completed training').click().run()
    assert not app.exception and app.error
    assert widget(app, 'text_area', 'Training notes').value == correction
    assert widget(app, 'text_area', 'Activity summary').value == 'Independent Activity stays unchanged.'
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', ReportPeriod(2026, 9)) == historical
    assert all(p.read_bytes() == raw for p, raw in historical_path.items())
    widget(app, 'text_input', 'Add a training requirement').set_value('TEST fire safety').run()
    widget(app, 'button', 'Add training column').click().run()
    assert not app.exception and not app.error
    assert widget(app, 'text_area', 'Training notes').value == correction
    widget(app, 'button', 'Save progress').click().run()
    latest = library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', ReportPeriod(2026, 9))
    assert next(b for b in latest.draft.blocks if b.key == 'training_summary').text == correction
    reopened = AppTest.from_file(ROOT / 'run_web.py', default_timeout=30).run()
    reopened.segmented_control[0].set_value('Monthly report').run()
    choose_report(reopened, latest.draft.profile.facilities[0].title)
    widget(reopened, 'text_input', 'Prepared by').set_value('Synthetic Editor').run()
    assert not reopened.exception
    assert widget(reopened, 'text_area', 'Training notes').value == correction
    assert widget(reopened, 'text_area', 'Activity summary').value == 'Independent Activity stays unchanged.'
    # Reopening must not rewrite the earlier completed version.
    assert next(b for b in historical.draft.blocks if b.key == 'training_summary').text == NOTE
