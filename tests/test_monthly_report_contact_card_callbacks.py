"""Receipt-level tests are synthetic; they do not substitute for browser delivery."""
from dataclasses import replace
from types import SimpleNamespace

from app import monthly_report_contact_cards_ui as cards
from app.monthly_report_model import ReportTable


def setup(monkeypatch):
    state = {'card': {'epoch': 'render-1'}, 'phone': 'corrected'}
    monkeypatch.setattr(cards, 'st', SimpleNamespace(session_state=state))
    tables = (ReportTable(('Name', 'Phone'), (('Same', 'old'), ('Same', 'old'), ('', '')), 'source'),)
    return state, tables, (('name', 'Same'), ('phone', 'old'))


def test_other_row_removal_keeps_separate_edit_only_receipt_and_duplicate_occurrences(monkeypatch):
    state, tables, fields = setup(monkeypatch)
    cards._queue('card', 'render-1', tables, (0, 0), fields, 'remove', (0, 1))
    pending = state['card']['pending']
    assert pending['corrected'][0].rows == (('Same', 'corrected'), ('Same', 'old'), ('', ''))
    assert pending['result'][0].rows == (('Same', 'corrected'), ('', ''))
    assert tables[0].rows == (('Same', 'old'), ('Same', 'old'), ('', ''))
    # Identical callback delivery never removes a second occurrence.
    cards._queue('card', 'render-1', tables, (0, 0), fields, 'remove', (0, 1))
    assert state['card']['pending'] == pending
    cards._queue('card', 'render-1', tables, (0, 0), fields, 'edit')
    assert state['card']['pending'] == pending


def test_stale_callback_cannot_replace_pending_or_current_state(monkeypatch):
    state, tables, fields = setup(monkeypatch)
    cards._queue('card', 'render-1', tables, (0, 0), fields, 'close')
    previous = state['card'].copy()
    cards._queue('card', 'older-render', tables, (0, 0), fields, 'remove', (0, 1))
    assert state['card'] == previous


def test_untouched_ragged_rows_and_unexposed_trailing_cells_are_not_normalized(monkeypatch):
    state, tables, fields = setup(monkeypatch)
    tables = (replace(tables[0], rows=(('Same',), ('Same', 'old', 'custom overflow'))),)
    assert cards._capture(tables, (0, 0), (('name', 'Same'), ('empty', ''))) == tables
    result = cards._capture(tables, (0, 1), fields)
    assert result[0].rows[1] == ('Same', 'corrected', 'custom overflow')


def test_pending_standing_phone_is_saved_before_report_only_remove(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_directory as directory
    from app.monthly_report_model import synthetic_profiles
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    sites = tuple(directory.DirectorySite(facility.key, facility.title, contacts=(
        directory.DirectoryContact('Operator', 'Invented Person', 'old-phone', ''),
        directory.DirectoryContact('Supervisor', 'Other Invented Person', 'other-phone', ''),
    )) for i, facility in enumerate(profile.facilities))
    original = directory.save_directory(profile.contract, sites, expected_revision=0,
                                        actor='Synthetic Editor', confirmed=True)
    before, missing = directory.contact_block(original, profile.facilities)
    assert not missing
    before = replace(before, source='Library')
    app = AppTest.from_string('''
from dataclasses import replace
import streamlit as st
from app.monthly_report_visual_ui import edit_contacts
from app.monthly_report_ui import _field
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_directory import CONTACT_SPEC
block = st.session_state['block']
draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026,9)), prepared_by='Synthetic Editor', blocks=(block,))
st.session_state['block'] = edit_contacts(draft, CONTACT_SPEC, block, 'standing', {}, _field, show_preview=False)
''')
    app.session_state['block'] = before
    app.run()
    next(b for b in app.button if b.label == 'Edit contact').click().run()
    next(w for w in app.text_input if w.label == 'Phone').set_value('corrected-phone')
    next(b for b in app.button if b.label == 'Remove contact').click().run()
    assert not app.exception
    after = app.session_state['block']
    latest = directory.load_directory(profile.contract)
    assert latest.revision == original.revision + 1
    assert latest.sites[0].contacts[0].phone == 'corrected-phone'
    assert len(latest.sites[0].contacts) == len(original.sites[0].contacts)
    assert after.rows == before.rows[1:]
    assert after.source == 'This month'
    assert directory.load_directory(profile.contract, original.revision) == original
    app.run()
    assert directory.load_directory(profile.contract).revision == latest.revision


def test_conflict_recovery_binds_current_snapshot_and_does_not_replay_removal(monkeypatch):
    state, tables, fields = setup(monkeypatch)
    cards._queue('card', 'render-1', tables, (0, 0), fields, 'remove', (0, 1))
    pending = state['card']['pending']
    current = (replace(tables[0], rows=((*tables[0].rows[0][:1], 'external'), *tables[0].rows[1:])),)
    cards._resolve_conflict('card', current, pending, True)
    recovered = state['card']['pending']
    assert recovered['expected'] == current
    assert recovered['result'] == pending['corrected']
    assert len(recovered['result'][0].rows) == 3
    cards._resolve_conflict('card', current, pending, False)
    assert state['card']['pending'] == recovered  # stale decision cannot discard recovery

def test_outer_close_captures_pending_contact_fields_then_rekeys_on_reopen(monkeypatch):
    state, tables, fields = setup(monkeypatch)
    state['card'].update(tables=tables, active=(0, 0), fields=fields, field_scope='native-old')
    cards.parent_visibility('card', opening=False)
    retained = state['card']['pending']
    assert retained['corrected'][0].rows[0][1] == 'corrected'
    assert state['card']['parent_hidden'] is True
    cards.parent_visibility('card', opening=True)
    assert state['card']['pending'] == retained
    assert state['card']['field_scope'] != 'native-old'
    assert state['card'].get('parent_hidden') is None
