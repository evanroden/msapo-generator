"""Exercise the pinned runner boundary with real native state and request queue."""
from pathlib import Path
from types import SimpleNamespace
from threading import RLock
import textwrap

import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.state.safe_session_state import SafeSessionState
from streamlit.runtime.state.session_state import SessionState
from streamlit.runtime.scriptrunner import RerunData, RerunException
from streamlit.runtime.scriptrunner.script_runner import ScriptRunner
from streamlit.runtime.scriptrunner_utils.script_requests import ScriptRequests
from scripts import streamlit_callback_delivery as repair


def boundary(repaired):
    import streamlit.runtime.scriptrunner.script_runner as module
    raw = Path(module.__file__).read_bytes()
    # Local installs may already have the exact repair. Recover pinned base only.
    if repair.LEGACY_AFTER in raw and repair.AFTER not in raw:
        raw = raw.replace(repair.LEGACY_AFTER, repair.BEFORE, 1)
    if repair.AFTER in raw:
        raw = raw.replace(repair.AFTER, repair.BEFORE, 1)
    selected = repair.repaired_source(raw, installed_version='1.61.1') if repaired else raw
    snippet = repair.AFTER if repaired else repair.BEFORE
    assert snippet in selected
    namespace = {}
    exec('def deliver(self, rerun_data):\n' + textwrap.indent(textwrap.dedent(snippet.decode()), '    '), namespace)
    return namespace['deliver'], raw


@pytest.mark.parametrize('repaired', [False, True])
@pytest.mark.parametrize('interrupt_at', [2, 3, 4])
def test_second_native_packet_cannot_drop_partially_delivered_callback(monkeypatch, repaired, interrupt_at):
    import streamlit.runtime.scriptrunner.script_runner as module
    monkeypatch.setattr(module, 'get_script_run_ctx', lambda **kw: None)
    runner = ScriptRunner.__new__(ScriptRunner)
    runner._execing = True
    runner._requests = ScriptRequests()
    monkeypatch.setattr(runner, '_is_in_script_thread', lambda: True)
    calls = 0
    armed = False
    packet = WidgetStates()
    packet.widgets.add(id='$$ID-probe-value', string_value='Synthetic pending edit')
    def yield_now():
        nonlocal calls
        calls += 1
        if armed and calls == interrupt_at:
            runner._requests.request_rerun(RerunData(widget_states=packet))
        runner._maybe_handle_execution_control_request()
    native = SessionState()
    safe = SafeSessionState(native, yield_now)
    def callback():
        text = safe['value']
        safe['scope'] = 'synthetic-report'
        safe['receipt'] = text
    native.register_widget(WidgetMetadata(id='$$ID-probe-value',
        deserializer=lambda value: value or '', serializer=lambda value: value,
        value_type='string_value', callback=callback), user_key='value')
    native._compact_state()
    runner._session_state = safe
    deliver, _ = boundary(repaired)
    armed = True
    deliver(runner, SimpleNamespace(widget_states=packet))
    armed = False
    assert runner._execing is True
    if repaired:
        assert native.filtered_state['receipt'] == 'Synthetic pending edit'
        # The queued native request was deferred, not discarded.
        with pytest.raises(RerunException):
            runner._maybe_handle_execution_control_request()
    else:
        assert 'receipt' not in native.filtered_state
    # An identical next packet never runs a lost native change callback again.
    deliver(runner, SimpleNamespace(widget_states=packet))
    assert native.filtered_state.get('receipt') == ('Synthetic pending edit' if repaired else None)


def test_delivery_restores_runner_flag_after_exception():
    deliver, _ = boundary(True)
    def fail(_):
        raise ValueError('Synthetic callback failure')
    runner = SimpleNamespace(_execing=True, _maybe_handle_execution_control_request=lambda: None,
        _session_state=SimpleNamespace(_lock=RLock(), on_script_will_rerun=fail))
    with pytest.raises(ValueError):
        deliver(runner, SimpleNamespace(widget_states=WidgetStates()))
    assert runner._execing is True


def test_source_is_pinned_idempotent_and_rejects_drift():
    _, raw = boundary(False)
    fixed = repair.repaired_source(raw, installed_version='1.61.1')
    assert repair.repaired_source(fixed, installed_version='1.61.1') == fixed
    legacy = raw.replace(repair.BEFORE, repair.LEGACY_AFTER, 1)
    assert repair.repaired_source(legacy, installed_version='1.61.1') == fixed
    with pytest.raises(RuntimeError):
        repair.repaired_source(raw + b'\n', installed_version='1.61.1')
    with pytest.raises(RuntimeError):
        repair.repaired_source(raw, installed_version='other')


def test_explicit_callback_rerun_still_uses_native_noop_semantics():
    deliver, _ = boundary(True)
    native = SessionState()
    safe = SafeSessionState(native, lambda: None)
    def callback():
        safe['receipt'] = 'captured before explicit rerun'
        raise RerunException(RerunData())
    native.register_widget(WidgetMetadata(id='$$ID-explicit-value',
        deserializer=lambda value: value or '', serializer=lambda value: value,
        value_type='string_value', callback=callback), user_key='value')
    native._compact_state()
    packet = WidgetStates()
    packet.widgets.add(id='$$ID-explicit-value', string_value='new value')
    runner = SimpleNamespace(_execing=True, _session_state=safe,
        _maybe_handle_execution_control_request=lambda: None)
    deliver(runner, SimpleNamespace(widget_states=packet))
    assert native.filtered_state['receipt'] == 'captured before explicit rerun'
    assert runner._execing is True


def test_queued_stop_runs_at_first_post_delivery_yield(monkeypatch):
    import streamlit.runtime.scriptrunner.script_runner as module
    from streamlit.runtime.scriptrunner import StopException
    monkeypatch.setattr(module, 'get_script_run_ctx', lambda **kw: None)
    runner = ScriptRunner.__new__(ScriptRunner)
    runner._execing = True
    runner._requests = ScriptRequests()
    monkeypatch.setattr(runner, '_is_in_script_thread', lambda: True)
    def deliver_and_request_stop(_):
        runner._requests.request_stop()
        runner._maybe_handle_execution_control_request()
        runner.completed_callback = True
    runner._session_state = SimpleNamespace(_lock=RLock(), on_script_will_rerun=deliver_and_request_stop)
    deliver, _ = boundary(True)
    deliver(runner, SimpleNamespace(widget_states=WidgetStates()))
    assert runner.completed_callback and runner._execing is True
    with pytest.raises(StopException):
        runner._maybe_handle_execution_control_request()


@pytest.mark.parametrize('repaired', [False, True])
def test_stopped_runner_waiting_for_shared_state_cannot_replay_older_packet(monkeypatch, repaired):
    from threading import Thread, Event
    from streamlit.runtime.scriptrunner import StopException
    import streamlit.runtime.scriptrunner.script_runner as module
    monkeypatch.setattr(module, 'get_script_run_ctx', lambda **kw: None)
    deliver, _ = boundary(True)
    if not repaired:
        namespace = {}
        exec('def deliver(self, rerun_data):\n' + textwrap.indent(
            textwrap.dedent(repair.LEGACY_AFTER.decode()), '    '), namespace)
        deliver = namespace['deliver']
    lock = RLock()
    waiting, completed = Event(), Event()
    class ObservedLock:
        def __enter__(self):
            waiting.set()
            lock.acquire()
        def __exit__(self, *args):
            lock.release()
    native = SessionState()
    safe = SafeSessionState(native, lambda: None)
    object.__setattr__(safe, '_lock', ObservedLock())
    native.register_widget(WidgetMetadata(id='$$ID-waiting-value', deserializer=lambda value: value or '',
        serializer=lambda value: value, value_type='string_value'), user_key='value')
    native._compact_state()
    packet = WidgetStates()
    packet.widgets.add(id='$$ID-waiting-value', string_value='obsolete value')
    runner = ScriptRunner.__new__(ScriptRunner)
    runner._execing = True
    runner._requests = ScriptRequests()
    runner._session_state = safe
    monkeypatch.setattr(runner, '_is_in_script_thread', lambda: True)
    errors = []
    def blocked_delivery():
        try:
            deliver(runner, SimpleNamespace(widget_states=packet))
        except StopException:
            completed.set()
        except BaseException as error:
            errors.append(error)
    lock.acquire()
    thread = Thread(target=blocked_delivery)
    thread.start()
    try:
        assert waiting.wait(5)
        # The stopped runner has not applied its stale packet yet. The latest
        # replacement owns the shared lock and already delivered an empty value.
        native['value'] = ''
        runner._requests.request_stop()
    finally:
        lock.release()
        thread.join(5)
    assert not thread.is_alive() and not errors
    assert completed.is_set() is repaired
    assert native['value'] == ('' if repaired else 'obsolete value')
