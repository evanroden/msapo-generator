"""Same-session handoff must not confer admission or source-proof authority."""
import gc
from pathlib import Path
from threading import Event, Thread
from time import monotonic
import tomllib

import pytest
from streamlit.runtime.scriptrunner_utils.exceptions import RerunException, StopException
from streamlit.runtime.scriptrunner_utils.script_requests import RerunData
from streamlit.testing.v1 import AppTest
from app import monthly_report_render_jobs as jobs
from app import monthly_report_source_handoff as handoff
from test_monthly_report_native_art_review import sample


def test_global_fast_reruns_remain_enabled():
    config = tomllib.loads((Path(__file__).parents[1] / '.streamlit/config.toml').read_text())
    assert config.get('runner', {}).get('fastReruns', True) is True


def test_same_session_waits_without_busy_then_rechecks_global_admission(monkeypatch):
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 1024 ** 3)
    entered, release = Event(), Event()
    errors, calls = [], []
    def previous():
        try:
            with handoff.source_review_handoff('same-session', lambda: None):
                with jobs.work_slot(preview=True):
                    entered.set()
                    assert release.wait(5)
                    raise StopException()
        except StopException:
            pass
        except BaseException as exc:
            errors.append(exc)
    thread = Thread(target=previous); thread.start()
    assert entered.wait(5)
    def checkpoint():
        calls.append('yield')
        release.set()
    try:
        with handoff.source_review_handoff('same-session', checkpoint):
            with jobs.work_slot(preview=True):
                calls.append('proof')
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive() and not errors
    assert calls.count('yield') >= 2 and calls[-1] == 'proof'
    gc.collect()
    assert 'same-session' not in handoff._LOCKS


@pytest.mark.parametrize('control', [StopException(), RerunException(RerunData())])
def test_obsolete_waiter_cancels_and_owner_cleans_up(control):
    with handoff.source_review_handoff('cancel', lambda: None):
        def cancelled():
            raise control
        with pytest.raises(type(control)):
            with handoff.source_review_handoff('cancel', cancelled):
                pytest.fail('Superseded waiter must not run proof work')
    with pytest.raises(type(control)):
        with handoff.source_review_handoff('cancel', cancelled):
            pytest.fail('Post-acquire checkpoint must cancel before proof')
    with handoff.source_review_handoff('cancel', lambda: None, wait_seconds=0):
        pass
    # The test deliberately retains the exception object; real runner frames
    # are discarded after handling. Release its synthetic traceback too.
    control.__traceback__ = None
    gc.collect()
    assert 'cancel' not in handoff._LOCKS


def test_foreign_session_remains_immediately_busy(monkeypatch):
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 1024 ** 3)
    # A foreign source review has a distinct local gate, not a permission to
    # wait for or bypass the common monthly admission lock.
    with handoff.source_review_handoff('foreign-owner', lambda: None):
        assert jobs._WORK_SLOT.acquire(blocking=False)
        try:
            start = monotonic()
            with pytest.raises(jobs.RenderBusy):
                with handoff.source_review_handoff('new-session', lambda: None):
                    with jobs.work_slot(preview=True):
                        pytest.fail('External work must retain exclusive admission')
            assert monotonic() - start < 1
        finally:
            jobs._WORK_SLOT.release()


def test_finite_timeout_and_errors_release_gate():
    with handoff.source_review_handoff('deadline', lambda: None):
        start = monotonic()
        with pytest.raises(jobs.RenderBusy):
            with handoff.source_review_handoff('deadline', lambda: None, wait_seconds=.02):
                pytest.fail('Same session is not reentrant authority')
        assert monotonic() - start < 1
    with pytest.raises(ValueError):
        with handoff.source_review_handoff('deadline', lambda: None):
            raise ValueError('Synthetic invalid source')
    with handoff.source_review_handoff('deadline', lambda: None, wait_seconds=0):
        pass


@pytest.mark.parametrize('reason', ['headroom', 'foreground'])
def test_resource_checks_are_not_bypassed_after_handoff(monkeypatch, reason):
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 0 if reason == 'headroom' else 1024 ** 3)
    monkeypatch.setattr(jobs, '_FOREGROUND_WAITING', 1 if reason == 'foreground' else 0)
    with pytest.raises(jobs.RenderBusy):
        with handoff.source_review_handoff('same-session', lambda: None):
            with jobs.work_slot(preview=True):
                pytest.fail('Handoff is not resource admission')


def test_real_guided_boundary_preserves_fields_across_rerun():
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_busy_ui import recover_render_busy
@recover_render_busy
def render():
    st.text_input('Prepared by', key='report_test_actor')
    st.checkbox('Preserve artwork', key='report_test_keep')
render()
''').run()
    assert not app.exception
    app.text_input[0].set_value('Synthetic operator')
    app.checkbox[0].check().run()
    assert not app.exception
    assert app.text_input[0].value == 'Synthetic operator'
    assert app.checkbox[0].value


def test_guided_boundary_handoff_precedes_saved_source_reload(sample):
    from test_monthly_report_native_art_lifecycle import save_sample
    _, _, profile, _, *_ = sample
    save_sample(sample)
    # The former section-only boundary ran too late: guided editor reloads
    # the saved source before reaching that section. Exercise a real persisted
    # synthetic view through the same boundary while its old runner unwinds.
    app = AppTest.from_string(f'''
import streamlit as st
from threading import Event, Thread, Timer
from streamlit.runtime.scriptrunner import get_script_run_ctx
from app.monthly_report_source_handoff import source_review_handoff
from app.monthly_report_render_jobs import work_slot
from app.monthly_report_busy_ui import recover_render_busy
from app import monthly_report_library as library
session_id = get_script_run_ctx().session_id
entered, release = Event(), Event()
def old_run():
    with source_review_handoff(session_id, lambda: None):
        with work_slot(preview=True):
            entered.set()
            assert release.wait(5)
worker = Thread(target=old_run)
worker.start()
assert entered.wait(5)
timer = Timer(.15, release.set)
timer.start()
@recover_render_busy
def render():
    draft = library.load_imported_draft({profile.contract!r}, {profile.key!r})
    assert draft is not None
    st.success('Saved source independently revalidated')
try:
    render()
finally:
    release.set()
    worker.join(5)
    timer.cancel()
''', default_timeout=30).run()
    assert not app.exception
    assert any('independently revalidated' in item.value for item in app.success)
    assert not any('Another report' in item.value for item in app.info)
