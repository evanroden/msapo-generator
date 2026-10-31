"""Native callback scheduling proof; no browser or production fault injection."""
import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.runtime.scriptrunner_utils.exceptions import StopException
from streamlit.runtime.state import session_state_proxy
from streamlit.testing.v1 import AppTest

from scripts import workspace_contact_observations as fixture


@pytest.mark.parametrize('retained', [False, True])
def test_native_fault_button_superseded_before_session_write(monkeypatch, retained):
    """Replay the hosted arm→Edit runner handoff at the actual native yield.

    Register real st.button callbacks, dispatch real WidgetStates through
    SessionState, and use SafeSessionState's own yield boundary. The old
    fixture loses its arm; capturing the offered dictionary does not yield.
    This does not claim native browser acceptance.
    """
    callback = ('fixture._arm_fault, args=(control, "after")' if retained else
                'st.session_state.__setitem__, args=("_contact_fault_once", "after")')
    app = AppTest.from_string('''
import streamlit as st
from scripts import workspace_contact_observations as fixture
control = fixture._fault_control()
st.button('Fail next synthetic shared save after commit', on_click=''' + callback + ''')
st.button('Edit contact')
''').run()
    assert not app.exception
    safe = app.session_state
    raw = safe._state
    control = raw['_contact_fault_control']
    monkeypatch.setattr(session_state_proxy, 'get_session_state', lambda: safe)

    def stop():
        raise StopException()

    object.__setattr__(safe, '_yield_callback', stop)
    arm = WidgetStates()
    arm.widgets.add(id=app.button[0].id, trigger_value=True)
    if retained:
        raw.on_script_will_rerun(arm)
        assert control == {'mode': 'after', 'armed': 1, 'consumed': 0}
        # A later stop still happens, but cannot undo the captured fault.
        with pytest.raises(StopException):
            safe['unrelated-read']
    else:
        with pytest.raises(StopException):
            raw.on_script_will_rerun(arm)
        assert '_contact_fault_once' not in raw
        assert control['mode'] == ''

    object.__setattr__(safe, '_yield_callback', lambda: None)
    edit = WidgetStates()
    edit.widgets.add(id=app.button[1].id, trigger_value=True)
    raw.on_script_will_rerun(edit)
    assert raw[app.button[0].id] is False  # Consumed trigger is not replayed.
    if retained:
        assert fixture._consume_fault() == 'after'
        assert control == {'mode': '', 'armed': 1, 'consumed': 1}
        assert fixture._consume_fault() == ''
    else:
        assert '_contact_fault_once' not in raw  # Exact old-fixture failure.


@pytest.mark.parametrize('mode', ['before', 'after'])
def test_fault_consumption_yields_before_not_after_consuming(monkeypatch, mode):
    control = {'mode': '', 'armed': 0, 'consumed': 0}
    fixture._arm_fault(control, mode)

    class State(dict):
        interrupted = True

        def get(self, key, default=None):
            if self.interrupted:
                self.interrupted = False
                raise StopException()
            return super().get(key, default)

    state = State(_contact_fault_control=control)
    import streamlit as st
    monkeypatch.setattr(st, 'session_state', state)
    with pytest.raises(StopException):
        fixture._consume_fault()
    assert control == {'mode': mode, 'armed': 1, 'consumed': 0}
    assert fixture._consume_fault() == mode
    assert fixture._consume_fault() == ''
    assert control == {'mode': '', 'armed': 1, 'consumed': 1}


def test_native_control_and_browser_still_require_the_injected_fault():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    source = (root / 'scripts/qa_compact_contact_journey.py').read_text()
    assert "assert state['attempts'][-1]['mode'] == fault" in source
    assert "record['pending_capture']" in source
    assert "record['last_receipt']" in source
    assert "timeout=30000" in source
    assert 'force=True' not in source
