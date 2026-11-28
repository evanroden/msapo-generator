from threading import Event, Thread
import time
from contextlib import contextmanager
from tests.test_monthly_report_start_conflicts import collision, button, manifest
from app import monthly_report_render_jobs as jobs


def test_use_incoming_waits_for_real_capacity_without_saving(collision):
    initial, _, _, _, app = collision
    before = manifest(initial).read_bytes()
    held, release = Event(), Event()
    failures = []
    def holder():
        try:
            with jobs.work_slot(preview=False):
                held.set(); release.wait(10)
        except Exception as exc:
            failures.append(exc)
    worker = Thread(target=holder); worker.start(); assert held.wait(3)
    timer = Thread(target=lambda: (time.sleep(.25), release.set()))
    try:
        timer.start()
        button(app, 'Use incoming organization chart').click().run()
        timer.join(3)
        assert not app.exception
        assert not button(app, 'Continue to this month’s updates').disabled
        assert manifest(initial).read_bytes() == before
    finally:
        release.set(); worker.join(3); timer.join(3)
    assert not failures


def test_use_priority_consumed_then_automatic_rerun_stays_fail_fast(collision, monkeypatch):
    initial, _, _, _, app = collision
    before = manifest(initial).read_bytes()
    real = jobs.work_slot
    calls = []
    @contextmanager
    def gate(**kwargs):
        calls.append(kwargs)
        if not kwargs.get('review'):
            raise jobs.RenderBusy('Synthetic occupied slot')
        with real(**kwargs): yield
    monkeypatch.setattr(jobs, 'work_slot', gate)
    button(app, 'Use incoming organization chart').click().run()
    assert calls == [{'preview': True, 'review': True}]
    assert not button(app, 'Continue to this month’s updates').disabled
    assert manifest(initial).read_bytes() == before
    app.run()
    assert calls[-1] == {'preview': True, 'review': False}
    assert button(app, 'Continue to this month’s updates').disabled
    assert manifest(initial).read_bytes() == before


def test_use_memory_refusal_retires_choice_and_keeps_storage(collision, monkeypatch):
    initial, _, _, _, app = collision
    before = manifest(initial).read_bytes()
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 0)
    button(app, 'Use incoming organization chart').click().run()
    assert not app.exception
    assert button(app, 'Continue to this month’s updates').disabled
    assert manifest(initial).read_bytes() == before
    assert not any(v for k,v in app.session_state.filtered_state.items() if k.endswith('_image_replacements'))
    assert not any(k.endswith('_comparison_retry') for k in app.session_state.filtered_state)


def test_choice_with_stale_source_cannot_stage_or_request_review(collision, monkeypatch):
    _, first, _, upload, app = collision
    from app import monthly_report_section_ui as ui
    original_button = ui.st.button
    captured = {}
    def observe(label, *args, **kwargs):
        if label == 'Use incoming organization chart':
            captured.update(callback=kwargs.get('on_click'), args=kwargs.get('args'))
        return original_button(label, *args, **kwargs)
    monkeypatch.setattr(ui.st, 'button', observe)
    app.run()
    assert captured.get('callback')
    scope = next(k for k in app.session_state.filtered_state if k.endswith('_image_review_scope'))
    prefix = scope.removesuffix('_image_review_scope')
    # Deliver the displayed click with changed upload bytes. Fresh preflight must retire it.
    upload['raw'] = first.read_bytes()
    calls = []
    real = jobs.work_slot
    @contextmanager
    def gate(**kwargs):
        calls.append(kwargs)
        with real(**kwargs): yield
    monkeypatch.setattr(jobs, 'work_slot', gate)
    button(app, 'Use incoming organization chart').click().run()
    assert not app.exception
    assert all(not call.get('review') for call in calls)
    assert not app.session_state.filtered_state.get(prefix + '_image_replacements')
    assert prefix + '_comparison_choice' not in app.session_state.filtered_state


def test_mismatched_choice_envelope_is_consumed_without_priority(collision, monkeypatch):
    _, _, _, _, app = collision
    scope_key = next(k for k in app.session_state.filtered_state if k.endswith('_image_review_scope'))
    prefix = scope_key.removesuffix('_image_review_scope')
    app.session_state[prefix + '_comparison_choice'] = ('obsolete', 'obsolete', (('org_chart', 'obsolete'),))
    calls = []
    @contextmanager
    def gate(**kwargs):
        calls.append(kwargs)
        raise jobs.RenderBusy('Synthetic occupied slot')
        yield
    monkeypatch.setattr(jobs, 'work_slot', gate)
    app.run()
    assert calls == [{'preview': True, 'review': False}]
    assert prefix + '_comparison_choice' not in app.session_state.filtered_state
    assert button(app, 'Continue to this month’s updates').disabled
