from contextlib import contextmanager
from threading import Event, Thread
import time

from app import monthly_report_render_jobs as jobs
from tests.test_monthly_report_start_conflicts import collision, button, manifest


def test_explicit_comparison_retry_waits_for_released_real_capacity(collision):
    initial, _, _, _, app = collision
    before = manifest(initial).read_bytes()
    held, release = Event(), Event()
    failures = []
    def holder():
        try:
            with jobs.work_slot(preview=False):
                held.set()
                release.wait(10)
        except Exception as exc:
            failures.append(exc)
    worker = Thread(target=holder)
    worker.start()
    assert held.wait(3)
    try:
        app.run()
        assert button(app, 'Continue to this month’s updates').disabled
        retry = button(app, 'Retry report page comparison')
        timer = Thread(target=lambda: (time.sleep(.25), release.set()))
        timer.start()
        retry.click().run()
        timer.join(3)
        assert not app.exception
        assert any(b.label == 'Use incoming organization chart' for b in app.button)
        assert button(app, 'Continue to this month’s updates').disabled
        assert manifest(initial).read_bytes() == before
    finally:
        release.set()
        worker.join(3)
    assert not failures


def test_retry_is_one_shot_while_automatic_preflight_stays_fail_fast(collision, monkeypatch):
    initial, _, _, _, app = collision
    real = jobs.work_slot
    calls = []
    @contextmanager
    def gate(**kwargs):
        calls.append(kwargs)
        if not kwargs.get('review'):
            raise jobs.RenderBusy('Synthetic occupied slot')
        with real(**kwargs):
            yield
    monkeypatch.setattr(jobs, 'work_slot', gate)
    app.run()
    assert calls[-1] == {'preview': True, 'review': False}
    button(app, 'Retry report page comparison').click().run()
    assert calls[-1] == {'preview': True, 'review': True}
    assert any(b.label == 'Use incoming organization chart' for b in app.button)
    app.run()
    assert calls[-1] == {'preview': True, 'review': False}
    assert button(app, 'Continue to this month’s updates').disabled


def test_stale_retry_intent_cannot_gain_review_admission(collision, monkeypatch):
    _, _, _, _, app = collision
    calls = []
    @contextmanager
    def gate(**kwargs):
        calls.append(kwargs)
        raise jobs.RenderBusy('Synthetic occupied slot')
        yield
    monkeypatch.setattr(jobs, 'work_slot', gate)
    app.run()
    scope_key = next(k for k in app.session_state.filtered_state if k.endswith('_image_review_scope'))
    prefix = scope_key.removesuffix('_image_review_scope')
    app.session_state[prefix + '_comparison_retry'] = 'obsolete-other-source-report-review'
    app.run()
    assert calls[-1] == {'preview': True, 'review': False}
    assert prefix + '_comparison_retry' not in app.session_state.filtered_state


def test_deliberate_retry_does_not_bypass_memory_refusal_or_change_storage(collision, monkeypatch):
    initial, _, _, _, app = collision
    before = manifest(initial).read_bytes()
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 0)
    app.run()
    button(app, 'Retry report page comparison').click().run()
    assert not app.exception
    assert not any(b.label == 'Use incoming organization chart' for b in app.button)
    assert button(app, 'Continue to this month’s updates').disabled
    assert manifest(initial).read_bytes() == before
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: None)
    # Prior deliberate request was consumed even though memory refused it.
    app.run()
    assert any(b.label == 'Use incoming organization chart' for b in app.button)
