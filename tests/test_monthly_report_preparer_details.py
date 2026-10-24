"""Prepared-by attribution survives early real report-details actions."""
from dataclasses import replace
import pytest
from streamlit.testing.v1 import AppTest
from app import monthly_report_guided as guided, monthly_report_library as library
from app.monthly_report_model import ReportDraft, ReportPeriod, profile_sections, synthetic_profiles

APP = '''
import streamlit as st
from dataclasses import replace
from app import monthly_report_guided as guided
from app.monthly_report_ui import _field, preserve_report_draft_state, restore_report_draft_state
from app.monthly_report_preparer_ui import render_preparer
restore_report_draft_state()
old, candidate, working = guided._review_details
prefix = 'report_guided_' + guided._signature((old.contract, old.key, working.period.key))
st.session_state.setdefault(prefix + '_draft', working)
st.session_state.setdefault(prefix + '_rich_text_epoch', 'first')
guided._render_report_details_action(candidate, old, working.period, 'd' * 32)
current = st.session_state[prefix + '_draft']
prepared = render_preparer(prefix, current.prepared_by, _field)
st.session_state[prefix + '_draft'] = replace(current, prepared_by=prepared)
preserve_report_draft_state(finalize=True)
'''

def fixture(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    old = synthetic_profiles()[1]
    library.save_profile(old, expected_revision=0, actor='Original editor', confirmed=True)
    working = ReportDraft(old, ReportPeriod(2026,9), 'Original editor', profile_sections(old), ())
    candidate = replace(old, title='Renamed region')
    monkeypatch.setattr(guided, '_review_details', (old,candidate,working), raising=False)
    app = AppTest.from_string(APP).run()
    assert not app.exception
    return app, old, candidate

def field(app):
    return next(w for w in app.text_input if w.label == 'Prepared by')

def click_with(app, text):
    field(app).set_value(text)
    next(w for w in app.button if w.label == 'Save report details').click().run()
    assert not app.exception

@pytest.mark.parametrize('actor', ['Changed same-event actor', '', '   '])
def test_same_event_details_action(monkeypatch,tmp_path,actor):
    app,old,candidate = fixture(monkeypatch,tmp_path)
    calls=[]
    original = library.save_profile
    def observed(*args, **kwargs):
        calls.append(kwargs['actor'])
        return original(*args,**kwargs)
    monkeypatch.setattr(library,'save_profile', observed)
    click_with(app,actor)
    saved=library.load_profile(old.contract,old.key)
    if actor.strip():
        assert saved.profile == candidate
        assert calls == [actor]
    else:
        assert saved.profile == old
        assert not calls or calls == [actor]
    assert field(app).value == actor

@pytest.mark.parametrize('kind', ['canonical', 'epoch'])
def test_replacement_clear_cannot_save_with_previous_actor(monkeypatch,tmp_path,kind):
    app,old,candidate = fixture(monkeypatch,tmp_path)
    prefix='report_guided_' + guided._signature((old.contract,old.key,'2026-09'))
    app.session_state[prefix+'_draft'] = replace(app.session_state[prefix+'_draft'],prepared_by='')
    if kind == 'epoch':
        app.session_state[prefix+'_rich_text_epoch'] = 'replacement'
    next(w for w in app.button if w.label == 'Save report details').click().run()
    assert not app.exception
    assert library.load_profile(old.contract,old.key).profile == old

CONTEXT_APP = '''
import streamlit as st
from app.monthly_report_ui import _field, preserve_report_draft_state, restore_report_draft_state
from app.monthly_report_preparer_ui import render_preparer
restore_report_draft_state()
context = st.selectbox('Report', ['A', 'B'])
prefix='report_context_'+context
st.session_state.setdefault(prefix+'_canonical', '')
st.session_state.setdefault(prefix+'_rich_text_epoch', context)
if not st.session_state.get('hide'):
    value=render_preparer(prefix, st.session_state[prefix+'_canonical'], _field)
    if not st.session_state.get('defer'):
        st.session_state[prefix+'_canonical'] = value
preserve_report_draft_state(finalize=True)
'''

def test_other_report_does_not_inherit_pending_actor():
    app=AppTest.from_string(CONTEXT_APP).run()
    field(app).set_value('Report A unsaved actor').run()
    original_id=field(app).proto.id
    app.selectbox[0].set_value('B').run()
    assert field(app).value == ''
    field(app).set_value('Report B actor').run()
    app.selectbox[0].set_value('A').run()
    assert field(app).value == 'Report A unsaved actor'
    assert field(app).proto.default == field(app).value
    assert field(app).proto.id != original_id
    app.selectbox[0].set_value('B').run()
    assert field(app).value == 'Report B actor'

@pytest.mark.parametrize('text', ['', '   ', 'Unacknowledged edit'])
def test_unacknowledged_native_mirror_survives_widget_teardown(text):
    app=AppTest.from_string(CONTEXT_APP).run()
    field(app).set_value('Canonical original').run()
    app.session_state['defer'] = True
    field(app).set_value(text).run()
    assert app.session_state['report_context_A_canonical'] == 'Canonical original'
    app.session_state['hide'] = True
    app.run()
    assert not app.text_input
    app.session_state['hide'] = False
    app.session_state['defer'] = False
    app.run()
    assert field(app).value == text
    assert app.session_state['report_context_A_canonical'] == text

def test_real_workflow_details_action_retains_same_event_actor_and_unsaved_text(monkeypatch,tmp_path):
    from test_monthly_report_ui import monthly
    from app import web_ui, monthly_report_active_work as active
    from app.contracts import RRH_CONTRACT
    monkeypatch.setattr(web_ui, 'device_token', lambda cookies: 'd'*32)
    app=monthly(monkeypatch,tmp_path)
    field(app).set_value('First actor').run()
    alias=next(w for w in app.text_input if w.label.startswith('Other names for '))
    alias.set_value('Independent synthetic alias').run()
    field(app).set_value('Same-event details actor')
    next(w for w in app.text_area if w.label == 'Activity summary').set_value('Independent pending report text.')
    next(w for w in app.button if w.label == 'Save report details').click().run()
    assert not app.exception
    assert field(app).value == 'Same-event details actor'
    assert next(w for w in app.text_area if w.label == 'Activity summary').value == 'Independent pending report text.'
    journal=active.load('d'*32,RRH_CONTRACT,'synthetic-guided',ReportPeriod(2026,9))
    assert journal.draft.prepared_by == 'Same-event details actor'
    assert next(b for b in journal.draft.blocks if b.key == 'activity_summary').text == 'Independent pending report text.'
    assert library.load_snapshot(RRH_CONTRACT,'synthetic-guided',ReportPeriod(2026,9)) is None

@pytest.mark.parametrize('actor', ['Changed acceptance actor', ''])
def test_same_event_conflict_acceptance_obeys_actor_clear(monkeypatch,tmp_path,actor):
    app,old,candidate=fixture(monkeypatch,tmp_path)
    dynamic=APP.replace("old, candidate, working = guided._review_details", """original, candidate, working = guided._review_details
from app import monthly_report_library as library
old = library.load_profile(original.contract, original.key).profile
candidate = replace(old, title=candidate.title)""")
    app=AppTest.from_string(dynamic).run()
    library.save_profile(replace(old,title='Concurrent group'),expected_revision=1,actor='Concurrent actor',confirmed=True)
    app.run()
    field(app).set_value(actor)
    next(w for w in app.button if w.label == 'Continue with these report details').click().run()
    assert not app.exception
    assert field(app).value == actor
    prefix='report_guided_' + guided._signature((old.contract,old.key,'2026-09'))
    assert app.session_state[prefix+'_identity_details_base'] == (2 if actor else 1)

@pytest.mark.parametrize('latest,stale', [('Latest report actor', ''), ('', 'Retired report actor')])
def test_real_navigation_ignores_packet_from_already_unmounted_preparer(monkeypatch,tmp_path,latest,stale):
    from test_monthly_report_ui import monthly
    app=monthly(monkeypatch,tmp_path)
    field(app).set_value(latest).run()
    retired_id=field(app).proto.id
    app.segmented_control[0].set_value('Expense reimbursement').run()
    assert not any(w.label == 'Prepared by' for w in app.text_input)
    states=app._tree.get_widget_states()
    states.widgets.add(id=retired_id,string_value=stale)
    app._run(states)
    assert not app.exception
    app.segmented_control[0].set_value('Monthly report').run()
    assert not app.exception
    assert field(app).value == latest


def test_real_navigation_keeps_actor_delivered_with_switch(monkeypatch,tmp_path):
    from test_monthly_report_ui import monthly
    app=monthly(monkeypatch,tmp_path)
    field(app).set_value('Previous report actor').run()
    field(app).set_value('Same-event navigation actor')
    app.segmented_control[0].set_value('Expense reimbursement').run()
    app.segmented_control[0].set_value('Monthly report').run()
    assert not app.exception
    assert field(app).value == 'Same-event navigation actor'


def test_real_workflow_ordinary_reruns_and_edits_keep_native_identity(monkeypatch, tmp_path):
    from test_monthly_report_ui import monthly
    app = monthly(monkeypatch, tmp_path)
    identity = field(app).proto.id
    for actor in ('Synthetic first actor', '', 'Synthetic re-entered actor'):
        field(app).set_value(actor).run()
        assert not app.exception
        assert field(app).proto.id == identity
        assert field(app).value == field(app).proto.default == actor
        app.run()
        assert not app.exception
        assert field(app).proto.id == identity
        assert field(app).value == actor
