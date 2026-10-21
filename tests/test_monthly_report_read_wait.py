"""Real global admission, fresh source proof, and cooperative cancellation."""
from threading import Event, Thread
from time import monotonic

import pytest
from streamlit.runtime.scriptrunner_utils.exceptions import RerunException, StopException
from streamlit.runtime.scriptrunner_utils.script_requests import RerunData

from app import monthly_report_library as library, monthly_report_render_jobs as jobs
from app.monthly_report_read_wait import read_with_capacity_wait
from app.monthly_report_start import read_starting_state
from test_monthly_report_native_art_review import sample
from test_monthly_report_native_art_lifecycle import save_sample


@pytest.mark.parametrize('damage', [None, 'receipt', 'source'])
def test_async_preview_owner_releases_then_source_is_freshly_proved(sample, monkeypatch, damage):
    _, _, profile, period, *_ = sample
    draft, _ = save_sample(sample)
    entered, release = Event(), Event()
    errors, attempts, notices = [], [], []
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 1024 ** 3)
    def preview_worker():
        try:
            with jobs.work_slot(preview=True):
                entered.set()
                assert release.wait(5)
        except BaseException as exc:
            errors.append(exc)
    worker = Thread(target=preview_worker); worker.start()
    assert entered.wait(5)
    manifest = library._profile_path(profile.contract, profile.key) / 'manifest.json'
    before = manifest.read_bytes()
    def read():
        attempts.append(1)
        return read_starting_state(profile.contract, profile.key, period)
    def waiting():
        notices.append(1)
        if damage == 'receipt':
            receipt = next((manifest.parent / 'imports').glob('*.source-view.json'))
            receipt.write_bytes(b'{}')
        elif damage == 'source':
            original = manifest.parent / 'imports' / (draft.profile.imported_from + '.docx')
            replacement = original.with_suffix('.tampered')
            replacement.write_bytes(b'changed synthetic source')
            replacement.replace(original)
        release.set()
    try:
        if damage:
            with pytest.raises(ValueError):
                read_with_capacity_wait(read, lambda: None, waiting)
        else:
            result = read_with_capacity_wait(read, lambda: None, waiting)
            assert result[0] == draft
    finally:
        release.set(); worker.join(5)
    assert not worker.is_alive() and not errors
    assert notices and len(attempts) >= 2
    assert manifest.read_bytes() == before


def test_capacity_deadline_is_finite_and_original_busy_is_preserved():
    calls = []
    # Hold the slot directly to model a foreign owner's thread-local admission.
    assert jobs._WORK_SLOT.acquire(blocking=False)
    try:
        def read():
            calls.append(1)
            with jobs.work_slot(wait_seconds=0):
                pytest.fail('Capacity must not be bypassed')
        start = monotonic()
        with pytest.raises(jobs.RenderBusy):
            read_with_capacity_wait(read, lambda: None, lambda: None, wait_seconds=.15)
        assert .1 <= monotonic() - start < 1
        assert len(calls) >= 2
    finally:
        jobs._WORK_SLOT.release()


@pytest.mark.parametrize('control', [StopException, lambda: RerunException(RerunData())])
def test_superseded_waiter_never_restarts_read(control):
    calls = []
    def read():
        calls.append('read')
        raise jobs.RenderBusy('occupied')
    def checkpoint():
        if calls:
            raise control()
    with pytest.raises((StopException, RerunException)):
        read_with_capacity_wait(read, checkpoint, lambda: None)
    assert calls == ['read']


def test_non_capacity_errors_are_not_retried():
    calls = []
    def read():
        calls.append(1)
        raise ValueError('Source changed')
    with pytest.raises(ValueError, match='Source changed'):
        read_with_capacity_wait(read, lambda: None, lambda: pytest.fail('Not capacity'))
    assert calls == [1]


def test_only_starting_read_is_wrapped_not_save_or_generate():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).parents[1] / 'app/monthly_report_guided.py').read_text())
    wrappers = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == 'read_with_capacity_wait']
    assert len(wrappers) == 1
    read = wrappers[0].args[0]
    assert isinstance(read, ast.Lambda) and isinstance(read.body, ast.Call)
    assert isinstance(read.body.func, ast.Name) and read.body.func.id == 'read_starting_state'


def test_script_wait_recovers_without_retry_and_preserves_edit():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_read_wait import read_with_capacity_wait
from app.monthly_report_render_jobs import RenderBusy
st.text_input('Prepared by', key='prepared')
status = st.empty()
checkpoint = st.empty()
attempts = [0]
def read():
    attempts[0] += 1
    if attempts[0] == 1:
        raise RenderBusy('Synthetic occupied preview')
    return 'Freshly verified'
try:
    result = read_with_capacity_wait(read, checkpoint.empty,
        lambda: status.info('Waiting for report capacity… Your edits are kept.'))
finally:
    status.empty()
st.success(result)
''').run()
    app.text_input[0].set_value('Synthetic unsaved editor').run()
    assert not app.exception
    assert app.text_input[0].value == 'Synthetic unsaved editor'
    assert app.success[0].value == 'Freshly verified'
    assert not app.button and not app.info
