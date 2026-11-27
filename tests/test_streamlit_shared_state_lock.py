"""Replacement runners cannot finish native callbacks out of order."""
from pathlib import Path
from threading import Event, Thread, local
from types import ModuleType
import gc
import weakref

import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.state.session_state import SessionState
from scripts import streamlit_shared_state_lock as repair


def native_module(repaired):
    import streamlit.runtime.state.safe_session_state as module
    raw = Path(module.__file__).read_bytes()
    if repair.HELPER in raw:
        raw = raw.replace(repair.HELPER, b'', 1).replace(repair.AFTER, repair.BEFORE, 1)
    selected = repair.repaired_source(raw, installed_version='1.61.1') if repaired else raw
    result = ModuleType('synthetic_native_safe_state')
    exec(compile(selected, module.__file__, 'exec'), result.__dict__)
    return result, raw


@pytest.mark.parametrize('repaired', [False, True])
def test_late_stopped_runner_cannot_overwrite_newer_empty_callback(repaired):
    module, _ = native_module(repaired)
    raw = SessionState()
    first = module.SafeSessionState(raw, lambda: None)
    replacement = module.SafeSessionState(raw, lambda: None)
    entered, release, completed, started = Event(), Event(), Event(), Event()
    context = local()
    receipts, errors = [], []
    def callback():
        value = context.safe['value']
        if value == 'older edit':
            entered.set()
            assert release.wait(5)
        receipts.append(value)
        context.safe['receipt'] = value
    raw.register_widget(WidgetMetadata(id='$$ID-overlap-value', deserializer=lambda value: value or '',
        serializer=lambda value: value, value_type='string_value', callback=callback), user_key='value')
    raw._compact_state()
    def deliver(safe, value, finished=None):
        try:
            context.safe = safe
            packet = WidgetStates()
            packet.widgets.add(id='$$ID-overlap-value', string_value=value)
            if finished:
                started.set()
            safe.on_script_will_rerun(packet)
            if finished:
                finished.set()
        except BaseException as error:
            errors.append(error)
    older = Thread(target=deliver, args=(first, 'older edit'))
    newer = Thread(target=deliver, args=(replacement, '', completed))
    older.start()
    assert entered.wait(5)
    newer.start()
    assert started.wait(5)
    try:
        overlap = completed.wait(.2 if repaired else 5)
        assert overlap is not repaired
    finally:
        release.set()
        older.join(5)
        newer.join(5)
    assert not older.is_alive() and not newer.is_alive() and not errors
    assert receipts == (['older edit', ''] if repaired else ['', 'older edit'])
    assert raw['receipt'] == ('' if repaired else 'older edit')


def test_lock_is_shared_only_with_same_raw_state_and_is_weakly_retained():
    module, _ = native_module(True)
    state = SessionState()
    first = module.SafeSessionState(state, lambda: None)
    second = module.SafeSessionState(state, lambda: None)
    other = module.SafeSessionState(SessionState(), lambda: None)
    assert first._lock is second._lock
    assert first._lock is not other._lock
    reference = weakref.ref(first._lock)
    identity = id(state)
    del first, second
    gc.collect()
    assert reference() is None
    assert identity not in module._enfra_state_locks


def test_pins_idempotence_and_unknown_source_rejection():
    _, raw = native_module(False)
    fixed = repair.repaired_source(raw, installed_version='1.61.1')
    assert repair.repaired_source(fixed, installed_version='1.61.1') == fixed
    with pytest.raises(RuntimeError):
        repair.repaired_source(raw + b'\n', installed_version='1.61.1')
    with pytest.raises(RuntimeError):
        repair.repaired_source(raw, installed_version='other')
