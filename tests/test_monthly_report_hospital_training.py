"""Hospital training must not auto-enroll the service provider's personnel."""
from dataclasses import replace

import pytest

from app.monthly_report_directory import DirectoryContact, DirectorySite, DirectoryState
from app.monthly_report_model import Facility, ReportProfile, ReportTable, ResolvedBlock
from app.monthly_report_training import MATRIX_REF, seed_matrix


@pytest.fixture
def context():
    profile=ReportProfile('Synthetic Training Contract','north','North',(Facility('north','Synthetic North'),))
    contacts=tuple(DirectoryContact(role,name) for role,name in (
        ('Hospital Facilities Director','Hospital Person'),('Client Technician','Hospital Tech'),
        ('ENFRA Technician','Provider Person'),('Asset Manager','Asset Person'),
        ('Hospital Vendor','Vendor Person'),('Operator','Unknown Person')))
    directory=DirectoryState(profile.contract,1,(DirectorySite('north','Synthetic North',contacts=contacts),), 'Editor','today')
    return profile,directory


def test_only_explicit_hospital_contacts_auto_seed(context):
    profile,directory=context
    result=seed_matrix(profile,ResolvedBlock('training_summary','This month'),{'sites':{'north':{'columns':['Safety']}}},directory)
    assert result.rows == (('Hospital Person','Synthetic North','Not recorded'),('Hospital Tech','Synthetic North','Not recorded'))


def test_proved_provider_rows_removed_only_from_working_matrix(context):
    profile,directory=context
    table=ReportTable(('Team member','Site','Safety'),(
        ('Provider Person','Synthetic North','Completed'),('Hospital Person','Synthetic North','Pending'),
        ('Manual Unknown','Synthetic North','Completed')),MATRIX_REF)
    block=ResolvedBlock('training_summary','Last month',text='Historical narrative',extra_tables=(table,))
    result=seed_matrix(profile,block,{},directory)
    assert result.rows == table.rows[1:]
    assert block.extra_tables == (table,) and table.rows[0][0] == 'Provider Person'


def test_saved_provider_status_does_not_reappear_in_new_report(context):
    profile,directory=context
    stored={'sites':{'north':{'columns':['Safety'],'rows':[['Provider Person','Completed'],['Hospital Person','Pending']]}}}
    result=seed_matrix(profile,ResolvedBlock('training_summary','This month'),stored,directory)
    assert not any(r[0]=='Provider Person' for r in result.rows)
    assert next(r for r in result.rows if r[0]=='Hospital Person')[2]=='Pending'
    assert stored['sites']['north']['rows'][0] == ['Provider Person','Completed']


def test_foreign_directory_never_seeds_or_filters_this_contract(context):
    profile,directory=context
    directory=replace(directory,contract='Different Contract')
    assert not seed_matrix(profile,ResolvedBlock('training_summary','This month'),{},directory).rows


def test_ambiguous_same_name_is_not_automatically_classified(context):
    profile,directory=context
    contacts=(DirectoryContact('Hospital Technician','Shared Name'),DirectoryContact('ENFRA Technician','Shared Name'))
    directory=replace(directory,sites=(replace(directory.sites[0],contacts=contacts),))
    assert not seed_matrix(profile,ResolvedBlock('training_summary','This month'),{},directory).rows
    recorded=ReportTable(('Team member','Site','Safety'),(('Shared Name','Synthetic North','Completed'),),MATRIX_REF)
    assert seed_matrix(profile,ResolvedBlock('training_summary','This month',extra_tables=(recorded,)),{},directory)==recorded


def test_ui_drops_cached_provider_rows_without_writing_shared_or_snapshot_data(context, monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_directory as directory_store, monthly_report_library as library
    from app.monthly_report_model import ReportDraft, ReportPeriod, default_sections
    from app.monthly_report_training import load_training, save_training

    profile, directory = context
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    old = ReportTable(('Team member', 'Site', 'Safety'), (
        ('Provider Person', 'Synthetic North', 'Completed'),
        ('Hospital Person', 'Synthetic North', 'Pending')), MATRIX_REF)
    block = ResolvedBlock('training_summary', 'This month', text='Preserve the source narrative', extra_tables=(old,))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Editor', default_sections(), (block,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    stored = save_training(profile, old, expected_revision=0, actor=draft.prepared_by)
    history = {p: p.read_bytes() for p in library._root().rglob('*.json')}
    monkeypatch.setattr(directory_store, 'load_directory', lambda *_: directory)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_training_ui import render_training
from app.monthly_report_editor import _signature
p = st.session_state['draft']
key = 'test_training_' + _signature((p.profile.contract, tuple(f.key for f in p.profile.facilities), p.period.key))
if 'seed_cache' not in st.session_state:
    st.session_state[key + '_matrix_draft'] = st.session_state['old']
    st.session_state['seed_cache'] = True
st.session_state['matrix_key'] = key

def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
st.session_state['blocks'] = render_training(p, st.session_state['blocks'], 'test', field)
''', default_timeout=30)
    app.session_state['draft'] = draft
    app.session_state['old'] = old
    app.session_state['blocks'] = {'training_summary': block}
    app.run()
    assert not app.exception and not app.error
    working = app.session_state['blocks']['training_summary']
    assert working.extra_tables[0].rows == old.rows[1:]
    assert working.text == block.text
    key = app.session_state['matrix_key']
    assert app.session_state[key + '_generation'] == 1
    assert app.session_state[key + '_matrix_draft'] == working.extra_tables[0]
    assert list(next(w for w in app.multiselect if w.label == 'Participants').options) == ['Hospital Person']
    app.run()
    assert app.session_state['blocks']['training_summary'] == working
    assert app.session_state[key + '_generation'] == 1
    assert load_training(profile.contract) == stored
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == saved
    assert all(p.read_bytes() == value for p, value in history.items())


def test_ui_rejects_identified_provider_reintroduced_by_grid_edit(context, monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_directory as directory_store, monthly_report_training_ui as ui
    from app.monthly_report_model import ReportDraft, ReportPeriod, default_sections
    from app.monthly_report_training import load_training

    profile, directory = context
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(directory_store, 'load_directory', lambda *_: directory)
    monkeypatch.setattr(ui, '_grid', lambda key, rows, **kwargs: [
        *rows, {'Team member': 'Provider Person', 'Site': 'Synthetic North'}])
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_training_ui import render_training
def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
st.session_state['blocks'] = render_training(st.session_state['draft'], {}, 'test', field)
''', default_timeout=30)
    app.session_state['draft'] = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Editor', default_sections(), ())
    app.run()
    assert not app.exception
    assert any('hospital staff' in e.value for e in app.error)
    assert load_training(profile.contract)['revision'] == 0
    assert app.session_state['blocks'] == {}


def test_provider_classification_is_scoped_to_one_site_not_just_the_name(context):
    from app.monthly_report_training import hospital_matrix
    profile, directory = context
    table = ReportTable(('Team member', 'Site', 'Safety'), (
        ('Provider Person', 'Different Site', 'Completed'),), MATRIX_REF)
    assert hospital_matrix(profile, table, directory) == table
    assert hospital_matrix(profile, table, replace(directory, archived=True)) == table
