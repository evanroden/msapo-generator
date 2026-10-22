"""Real Streamlit callback/yield dispatch protects against global serialization.

False is a deliberate negative control: a queued external rerun is mistaken
for a callback-requested rerun and swallowed. True dispatches the full replacement
and cancels the old callback. Only constructor wiring is synthetic.
"""
import pytest
from threading import current_thread, Lock
from types import SimpleNamespace
from streamlit import config
from streamlit.proto.ClientState_pb2 import ClientState
from streamlit.runtime.app_session import AppSession, AppSessionState
from streamlit.runtime.scriptrunner.script_runner import ScriptRunner
from streamlit.runtime.state.session_state import SessionState
from streamlit.runtime.state.safe_session_state import SafeSessionState
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.scriptrunner_utils.script_requests import ScriptRequests
from streamlit.runtime.scriptrunner_utils.exceptions import StopException

@pytest.mark.parametrize("fast", [False, True, None])
def test_external_full_rerun_during_callback_is_not_lost(monkeypatch, fast):
    req=ScriptRequests(); raw=SessionState()
    runner=object.__new__(ScriptRunner)
    runner._requests=req; runner._execing=True; runner._script_thread=current_thread()
    runner._join_wake_lock=Lock(); runner._join_wake_coordinator=None
    safe=SafeSessionState(raw,runner._maybe_handle_execution_control_request)
    def callback(): safe['action']='add'
    raw._new_widget_state.set_widget_metadata(WidgetMetadata(id='click', deserializer=lambda x:x,
        serializer=lambda x:x,value_type='trigger_value',callback=callback))
    raw._new_widget_state.set_from_value('click',True)
    replacements=[]
    session=SimpleNamespace(_state=AppSessionState.APP_IS_RUNNING,_scriptrunner=runner,
        _create_scriptrunner=lambda data: replacements.append(data))
    real_option=config.get_option
    if fast is None:
        fast = config.get_option('runner.fastReruns')
        assert fast is True, 'Production dispatch must not swallow external reruns in callbacks'
    else:
        monkeypatch.setattr(config, 'get_option', lambda k: fast if k == 'runner.fastReruns' else real_option(k))
    AppSession.request_rerun(session,ClientState(page_script_hash='full-report'))
    stopped=False
    try: raw._call_callbacks()
    except StopException: stopped=True
    pending=req.on_scriptrunner_yield()
    record={'fastReruns':fast,'replacement_full_runs':len(replacements),
        'callback_stopped':stopped,'action_recorded':raw.filtered_state.get('action'),
        'pending_request':pending.type.name if pending else None}
    if fast:
        assert stopped and len(replacements)==1
        assert replacements[0].page_script_hash=='full-report'
    else:
        assert not stopped and not replacements and pending is None
        assert record['action_recorded'] is None
