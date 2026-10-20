"""Synthetic UI intent/lifecycle checks; no real source files or conversions."""
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import memory
from app import monthly_report_source_render_qa as preview
from app import monthly_report_source_preview_ui as ui
from app import monthly_report_testing as qa

P = ui._PREFIX


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    raw = BytesIO()
    document = Document()
    document.add_paragraph('Invented source')
    document.save(raw)
    source = raw.getvalue()
    state = {P + 'owner': 'b' * 32, 'report_important_draft': {'edits': 'keep me'}}
    monkeypatch.setattr(ui.st, 'session_state', state)
    with qa.isolated('a' * 32):
        memory._data_dir()
        state[P + 'epoch'] = preview.retire(state[P + 'owner'])
        yield source, state, qa.capture_namespace()


def upload(raw, identity='fresh-upload'):
    return SimpleNamespace(file_id=identity, getvalue=lambda: raw, size=len(raw))


def test_callback_binds_fresh_upload_and_deduplicates_requests(setup):
    raw, state, activate = setup
    state['upload'] = upload(raw)
    req = preview.new_request(state[P + 'owner'], state[P + 'epoch'], raw,
                              upload_id='fresh-upload', label='Original', kind='original')
    ui._queue(activate, req, 'upload')
    assert state[P + 'pending'] == req
    ui._queue(activate, req, 'upload')
    assert state[P + 'pending'] == req
    state['upload'] = upload(raw, 'new-incarnation-same-bytes')
    state.pop(P + 'pending')
    ui._queue(activate, req, 'upload')
    assert P + 'pending' not in state
    assert 'changed' in state[P + 'error']
    assert state['report_important_draft'] == {'edits': 'keep me'}


def test_upload_clear_and_a_b_a_retire_only_preview_keys(setup):
    raw, state, activate = setup
    old_epoch = state[P + 'epoch']
    state.update({P + 'pending': 'old', P + 'receipt': {'source_sha256': sha256(raw).hexdigest()}, P + 'request': 'old'})
    ui._clear(activate, state[P + 'owner'], old_epoch)
    assert state[P + 'epoch'] != old_epoch
    assert all(P + name not in state for name in ('pending', 'receipt', 'request'))
    assert state[P + 'uploader_epoch']
    assert state['report_important_draft'] == {'edits': 'keep me'}


def test_live_mode_never_exposes_source_preview(monkeypatch):
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_source_preview_ui import render
st.session_state['report_existing'] = 'untouched'
render()
''').run()
    assert not app.exception
    assert not app.get('file_uploader')
    assert not app.button
    assert app.session_state['report_existing'] == 'untouched'


def test_isolated_ui_has_fresh_upload_explicit_action_and_keeps_draft(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = AppTest.from_string('''
import streamlit as st
from app import memory
from app import monthly_report_testing as qa
from app.monthly_report_source_preview_ui import render
st.query_params['monthly_qa'] = 'isolated'
st.session_state['report_existing'] = 'untouched'
with qa.isolated('a' * 32):
    memory._data_dir()
    render()
''').run()
    assert not app.exception
    assert len(app.get('file_uploader')) == 1
    assert app.button(key=P + 'render').disabled
    assert any('SOURCE PREVIEW ONLY' in item.value for item in app.warning)
    app.text_input(key=P + 'label').set_value('Synthetic original').run()
    assert not app.exception
    next(button for button in app.button if button.key.startswith(P + 'clear_')).click().run()
    assert not app.exception
    assert app.session_state['report_existing'] == 'untouched'
    assert app.button(key=P + 'render').disabled


def test_disabled_or_stale_none_request_cannot_dereference_or_render(setup):
    raw, state, activate = setup
    state['upload'] = upload(raw)
    ui._queue(activate, None, 'upload')
    assert P + 'pending' not in state
    assert 'changed' in state[P + 'error']


def test_stale_clear_a_cannot_discard_newer_b(setup):
    _raw, state, activate = setup
    owner, epoch_a = state[P + 'owner'], state[P + 'epoch']
    ui._invalidate(activate)  # A -> B upload change intentionally retires A.
    epoch_b = state[P + 'epoch']
    state.update({P + 'request': 'B request', P + 'receipt': 'B receipt', P + 'pending': 'B pending'})
    before = dict(state)
    ui._clear(activate, owner, epoch_a)
    assert state == before
    assert preview._active(owner)['epoch'] == epoch_b


def test_cancel_then_same_a_reopen_is_not_cleared_by_old_cancel(setup):
    raw, state, activate = setup
    owner, epoch_a = state[P + 'owner'], state[P + 'epoch']
    state[P + 'request'] = 'A request'
    ui._clear(activate, owner, epoch_a)
    assert P + 'request' not in state
    reopened_epoch = state[P + 'epoch']
    assert reopened_epoch != epoch_a
    req = preview.new_request(owner, reopened_epoch, raw, upload_id='same-A-reopened', label='A', kind='original')
    state.update({P + 'request': req, P + 'receipt': 'reopened A receipt'})
    before = dict(state)
    ui._clear(activate, owner, epoch_a)
    assert state == before
    assert preview._active(owner)['epoch'] == reopened_epoch


def test_clear_rejects_disk_incarnation_change_without_touching_state(setup):
    _raw, state, activate = setup
    owner, old_epoch = state[P + 'owner'], state[P + 'epoch']
    newer = preview.retire(owner)
    state[P + 'receipt'] = 'must not be silently discarded'
    before = dict(state)
    ui._clear(activate, owner, old_epoch)
    assert state == before
    assert preview._active(owner)['epoch'] == newer


def test_stale_reset_invalidation_is_harmless_and_keeps_draft(setup, tmp_path):
    _raw, state, activate = setup
    before = dict(state)
    qa.reset(tmp_path)
    ui._invalidate(activate)
    assert state == before


def test_stale_earlier_cleanup_cannot_touch_new_selection(setup, monkeypatch):
    _raw, state, activate = setup
    owner, epoch = state[P + 'owner'], state[P + 'epoch']
    ui._invalidate(activate)
    before = dict(state)
    monkeypatch.setattr(preview, 'clear_earlier', lambda *_: pytest.fail('stale cleanup executed'))
    ui._clear_earlier(activate, owner, epoch, ())
    assert state == before


def test_owner_capacity_still_offers_browser_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(preview, 'MAX_OWNERS', 1)
    with qa.isolated('a' * 32):
        memory._data_dir()
        preview.retire('b' * 32)
    app = AppTest.from_string('''
import streamlit as st
from app import memory, monthly_report_testing as qa
from app.monthly_report_source_preview_ui import render
st.query_params['monthly_qa'] = 'isolated'
st.session_state['report_existing'] = 'untouched'
with qa.isolated('a' * 32):
    memory._data_dir()
    render()
''').run()
    assert not app.exception
    app.button(key=P + 'recover_at_capacity').click().run()
    assert not app.exception and len(app.get('file_uploader')) == 1
    assert app.session_state['report_existing'] == 'untouched'


def test_peer_expiry_recovers_idle_session_without_render_or_draft_reset(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = AppTest.from_string('''
import streamlit as st
from app import memory, monthly_report_testing as qa
from app.monthly_report_source_preview_ui import render
st.query_params['monthly_qa'] = 'isolated'
st.session_state['report_existing'] = 'untouched'
with qa.isolated('a' * 32):
    memory._data_dir()
    render()
''').run()
    old_owner = app.session_state[P + 'owner']
    old_epoch = app.session_state[P + 'epoch']
    app.session_state[P + 'request'] = 'expired request'
    with qa.isolated('a' * 32):
        memory._data_dir()
        active = preview._folder(old_owner) / 'active.json'
        old = preview.time.time() - preview.RETENTION_SECONDS - 1
        os.utime(active, (old, old))
    with qa.isolated('d' * 32):
        memory._data_dir()
        preview.retire('e' * 32)  # Another browser expires the idle owner.
    app.run()
    assert not app.exception and app.session_state[P + 'owner'] != old_owner
    assert app.session_state[P + 'epoch'] != old_epoch
    assert P + 'request' not in app.session_state
    assert app.button(key=P + 'render').disabled
    assert app.session_state['report_existing'] == 'untouched'
