"""Installed Streamlit dispatch plus real admission, with bounded synthetic work."""
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
import tomllib
import subprocess
import sys

import pytest
from streamlit import config
from streamlit.proto.ClientState_pb2 import ClientState
from streamlit.runtime.app_session import AppSession, AppSessionState
from streamlit.runtime.scriptrunner_utils.script_requests import RerunData, ScriptRequests, ScriptRequestType
from streamlit.runtime.scriptrunner_utils.exceptions import RerunException, StopException
from app import monthly_report_render_jobs as jobs


def test_deployment_serializes_same_session_reruns():
    settings = tomllib.loads((Path(__file__).parents[1] / '.streamlit/config.toml').read_text())
    assert settings['runner']['fastReruns'] is False
    result = subprocess.run([sys.executable, '-c',
        'from streamlit import config; assert config.get_option("runner.fastReruns") is False'],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def _client(actor, *, checked=True, clicked=False):
    state = ClientState(page_script_hash='synthetic-report')
    state.widget_states.widgets.add(id='prepared_by', string_value=actor)
    state.widget_states.widgets.add(id='preserve_art', bool_value=checked)
    state.widget_states.widgets.add(id='continue', trigger_value=clicked)
    return state


@pytest.mark.parametrize('fast', [True, False])
def test_real_streamlit_dispatch_avoids_own_busy_and_coalesces_edits(monkeypatch, fast):
    # Real AppSession dispatch and ScriptRequests coalescing; only the browser
    # shell and heavy computation are represented. No genuine reports in CI.
    real_option = config.get_option
    monkeypatch.setattr(config, 'get_option', lambda key: fast if key == 'runner.fastReruns' else real_option(key))
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 1024 ** 3)
    requests = ScriptRequests()
    runner = SimpleNamespace(request_stop=requests.request_stop, request_rerun=requests.request_rerun)
    acquired, release = Event(), Event()
    result = {}
    def heavy_phase():
        try:
            with jobs.work_slot(preview=True):
                acquired.set()
                assert release.wait(5)
                result['pending'] = requests.on_scriptrunner_yield()
                # ScriptRunner's yield handler raises these control exceptions;
                # the real admission finally must unwind before the next run.
                if result['pending'].type == ScriptRequestType.RERUN:
                    raise RerunException(result['pending'].rerun_data)
                raise StopException()
        except (RerunException, StopException):
            with jobs.work_slot(preview=True):
                result['released_before_next_run'] = True
        except BaseException as exc:
            result['error'] = exc
    worker = Thread(target=heavy_phase)
    worker.start()
    assert acquired.wait(5)
    replacements = []
    def create_replacement(data):
        # Replacement dispatch is on a different thread than the old owner.
        try:
            with jobs.work_slot(preview=True):
                replacements.append('admitted')
        except jobs.RenderBusy:
            replacements.append('busy')
    session = SimpleNamespace(_state=AppSessionState.APP_IS_RUNNING,
                              _scriptrunner=runner, _create_scriptrunner=create_replacement)
    try:
        AppSession.request_rerun(session, _client('First editor', checked=False, clicked=True))
        if not fast:
            AppSession.request_rerun(session, _client('Latest editor'))
            assert session._scriptrunner is runner
            assert replacements == []
        else:
            assert replacements == ['busy']  # Reproduces the old failure.
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert 'error' not in result
    assert result['released_before_next_run']
    pending = result['pending']
    assert pending.type == (ScriptRequestType.STOP if fast else ScriptRequestType.RERUN)
    if not fast:
        values = {w.id: w for w in pending.rerun_data.widget_states.widgets}
        assert values['prepared_by'].string_value == 'Latest editor'
        assert values['preserve_art'].bool_value is True
        assert values['continue'].trigger_value is True
        assert pending.rerun_data.page_script_hash == 'synthetic-report'
    with jobs.work_slot(preview=True):
        pass


def test_serialized_dispatch_keeps_stop_and_navigation_requests():
    requests = ScriptRequests()
    assert requests.request_rerun(RerunData(page_script_hash='new-page'))
    assert requests.on_scriptrunner_yield().rerun_data.page_script_hash == 'new-page'
    requests.request_stop()
    assert requests.on_scriptrunner_yield().type == ScriptRequestType.STOP
    assert not requests.request_rerun(RerunData())  # Explicit Stop remains terminal.


def test_other_session_contention_still_requires_retry(monkeypatch):
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 1024 ** 3)
    assert jobs._WORK_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(jobs.RenderBusy):
            with jobs.work_slot(preview=True):
                pytest.fail('External contention must not bypass admission')
    finally:
        jobs._WORK_SLOT.release()
    with jobs.work_slot(preview=True):
        pass
