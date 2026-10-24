"""Pinned protocol guards, not a claim of native-browser timing coverage."""
import logging

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.proto.WidgetStates_pb2 import WidgetStates

ACTOR = "Synthetic current editor"
APP = '''
import streamlit as st
from app.monthly_report_ui import _field, preserve_report_draft_state, restore_report_draft_state
from app.monthly_report_preparer_ui import render_preparer, pending_preparer
restore_report_draft_state()
st.session_state.setdefault('canonical', 'Synthetic current editor')
st.session_state.setdefault('report_test_rich_text_epoch', 'first-report')
st.session_state['early_action_actor'] = pending_preparer('report_test', canonical=st.session_state['canonical'])
if not st.session_state.get('hidden'):
    result = render_preparer('report_test', st.session_state['canonical'], _field)
    if not st.session_state.get('defer_canonical'):
        st.session_state['canonical'] = result
preserve_report_draft_state(finalize=True)
st.button('Unrelated action')
'''


def editor(app):
    return next(w for w in app.text_input if w.label == 'Prepared by')


def wire(identity, text):
    value = WidgetStates()
    value.widgets.add(id=identity, string_value=text)
    return value


def run(app, state=None):
    app._run(state) if state is not None else app.run()
    assert not app.exception
    return app


def assert_native(app, text, identity=None):
    item = editor(app)
    assert item.value == item.proto.default == app.session_state['canonical'] == text
    assert not item.proto.set_value
    if identity is not None:
        assert item.proto.id == identity
    return item.proto.id


def test_initial_native_default_matches_actor_and_default_echo_is_noop(caplog):
    caplog.set_level(logging.WARNING)
    app = run(AppTest.from_string(APP))
    identity = assert_native(app, ACTOR)
    assert app.session_state['early_action_actor'] == ACTOR
    run(app, wire(identity, editor(app).proto.default))
    assert_native(app, ACTOR, identity)
    assert not any('default value but also had its value set' in record.message for record in caplog.records)


@pytest.mark.parametrize('seed', [ACTOR, ''])
def test_stable_fixture_seed_is_not_a_native_session_state_seed(seed, caplog):
    app = AppTest.from_string(APP)
    app.session_state['report_test_prepared'] = seed
    run(app)
    assert_native(app, seed)
    assert not any('default value but also had its value set' in record.message for record in caplog.records)


def test_deliberate_clear_reentry_and_unrelated_rerun_keep_native_id(caplog):
    app = run(AppTest.from_string(APP))
    identity = editor(app).proto.id
    for text in ('', 'Synthetic explicit replacement', ACTOR):
        run(app, wire(identity, text))
        assert_native(app, text, identity)
        run(app)
        assert_native(app, text, identity)
    assert not any('default value but also had its value set' in record.message for record in caplog.records)


def test_new_canonical_actor_retires_native_id_and_rejects_old_empty_echo():
    app = run(AppTest.from_string(APP))
    old = editor(app).proto.id
    app.session_state['canonical'] = 'Synthetic newer canonical actor'
    run(app)
    current = assert_native(app, 'Synthetic newer canonical actor')
    assert current != old
    run(app, wire(old, ''))
    assert_native(app, 'Synthetic newer canonical actor')


def test_hidden_widget_mirror_restores_pending_edit_and_rejects_old_frontend_echo():
    app = run(AppTest.from_string(APP))
    old = editor(app).proto.id
    app.session_state['hidden'] = True
    run(app, wire(old, 'Synthetic pending before hide'))
    assert not app.text_input
    app.session_state['hidden'] = False
    run(app)
    current = assert_native(app, 'Synthetic pending before hide')
    assert current != old
    run(app, wire(old, ''))
    assert_native(app, 'Synthetic pending before hide')


def test_hidden_mirror_cannot_override_newer_canonical_actor():
    app = run(AppTest.from_string(APP))
    old = editor(app).proto.id
    app.session_state['hidden'] = True
    run(app, wire(old, 'Synthetic obsolete hidden actor'))
    app.session_state['canonical'] = 'Synthetic canonical replacement while hidden'
    app.session_state['hidden'] = False
    run(app)
    current = assert_native(app, 'Synthetic canonical replacement while hidden')
    run(app, wire(old, ''))
    assert_native(app, 'Synthetic canonical replacement while hidden')


def test_new_epoch_retires_old_input_even_when_canonical_text_is_unchanged():
    app = run(AppTest.from_string(APP))
    old = editor(app).proto.id
    app.session_state['report_test_rich_text_epoch'] = 'replacement-report'
    run(app)
    current = assert_native(app, ACTOR)
    assert current != old
    run(app, wire(old, ''))
    assert_native(app, ACTOR)


def test_edit_before_capacity_yield_survives_unacknowledged_canonical_baseline():
    app = run(AppTest.from_string(APP))
    identity = editor(app).proto.id
    app.session_state['defer_canonical'] = True
    run(app, wire(identity, 'Synthetic edit before yield'))
    assert app.session_state['canonical'] == ACTOR
    assert editor(app).proto.default == editor(app).value == 'Synthetic edit before yield'
    app.session_state['defer_canonical'] = False
    run(app)
    assert_native(app, 'Synthetic edit before yield', identity)


@pytest.mark.parametrize('text', ['', 'Synthetic same-event action actor'])
def test_action_before_input_reads_delivered_native_edit_including_clear(text):
    app = run(AppTest.from_string(APP))
    run(app, wire(editor(app).proto.id, text))
    assert app.session_state['early_action_actor'] == text
    assert_native(app, text)


@pytest.mark.parametrize('text', ['', 'Synthetic newer canonical before action'])
def test_action_before_input_uses_new_canonical_actor_instead_of_old_stable(text):
    app = run(AppTest.from_string(APP))
    app.session_state['canonical'] = text
    run(app)
    assert app.session_state['early_action_actor'] == text
    assert_native(app, text)


@pytest.mark.parametrize('text', ['', ACTOR])
def test_action_before_input_obeys_replacement_epoch_even_if_actor_is_unchanged(text):
    app = run(AppTest.from_string(APP))
    old = editor(app).proto.id
    app.session_state['hidden'] = True
    run(app, wire(old, 'Synthetic stale hidden attribution'))
    app.session_state['report_test_rich_text_epoch'] = 'new-report'
    app.session_state['canonical'] = text
    app.session_state['hidden'] = False
    run(app)
    assert app.session_state['early_action_actor'] == text
    assert_native(app, text)


@pytest.mark.parametrize('latest,stale', [(ACTOR, ''), ('', 'Synthetic retired attribution')])
def test_packet_after_completed_hidden_frame_cannot_replace_preserved_actor(latest, stale):
    app = run(AppTest.from_string(APP))
    old = editor(app).proto.id
    run(app, wire(old, latest))
    app.session_state['hidden'] = True
    run(app)
    assert not app.text_input
    run(app, wire(old, stale))
    app.session_state['hidden'] = False
    run(app)
    assert_native(app, latest)


def test_capture_only_boundary_does_not_retire_an_ordinary_current_editor():
    source = APP.replace('restore_report_draft_state()', 'preserve_report_draft_state()\nrestore_report_draft_state()')
    app = run(AppTest.from_string(source))
    identity = editor(app).proto.id
    for _ in range(3):
        run(app)
        assert_native(app, ACTOR, identity)


@pytest.mark.parametrize('finalize,fragments,retired', [
    (False, None, False), (True, ['synthetic-preview-fragment'], False), (True, None, True),
])
def test_only_explicit_full_render_end_retires_absent_preparer(monkeypatch, finalize, fragments, retired):
    from types import SimpleNamespace
    from app import monthly_report_ui as ui
    from streamlit.runtime import scriptrunner
    key = 'report_test_prepared_native_previous'
    state = {'report_widget_keys': (key, 'report_test_unrelated'),
             key: 'Synthetic same-navigation actor', 'report_test_unrelated': 'Other pending text'}
    context = SimpleNamespace(fragment_ids_this_run=fragments,
        shared=SimpleNamespace(widget_user_keys_this_run=SimpleNamespace(snapshot=lambda: frozenset())))
    monkeypatch.setattr(ui, 'st', SimpleNamespace(session_state=state))
    monkeypatch.setattr(scriptrunner, 'get_script_run_ctx', lambda **kwargs: context)
    ui.preserve_report_draft_state(finalize=finalize)
    assert state['report_draft_mirror'][key] == 'Synthetic same-navigation actor'
    assert state['report_draft_mirror']['report_test_unrelated'] == 'Other pending text'
    assert (key not in state['report_widget_keys']) == retired
    assert 'report_test_unrelated' in state['report_widget_keys']
    if retired:
        state[key] = ''  # An old ID packet after the completed hidden frame.
        ui.preserve_report_draft_state()
        assert state['report_draft_mirror'][key] == 'Synthetic same-navigation actor'
