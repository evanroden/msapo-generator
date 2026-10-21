"""Saved source validation yields promptly without accepting stale authority."""
from time import monotonic

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_render_jobs as jobs
from app.monthly_report_start import latest_saved_draft
from app.monthly_report_preview import section_preview_fingerprint, section_preview_docx
from test_monthly_report_native_art_review import sample
from test_monthly_report_native_art_lifecycle import save_sample


@pytest.mark.parametrize('operation', ['reload', 'latest', 'replay', 'preview'])
def test_busy_saved_view_yields_immediately_and_retry_revalidates(sample, operation):
    path, view, profile, period, *_ = sample
    draft, loader = save_sample(sample)
    calls = {
        'reload': lambda: library.load_imported_draft(profile.contract, profile.key),
        'latest': lambda: latest_saved_draft(profile.contract, profile.key, period),
        'replay': lambda: library.starting_contribution(profile.contract, profile.key, period, view.original_inspection.sha256),
        'preview': lambda: section_preview_docx(draft, 'cover', loader),
    }
    before = (library._profile_path(profile.contract, profile.key)/'manifest.json').read_bytes()
    # A valid cached preview identity remains exact, but never substitutes for
    # validation needed to reload/render while another worker occupies admission.
    identity = section_preview_fingerprint(draft, 'cover')
    assert jobs._WORK_SLOT.acquire(blocking=False)
    try:
        start = monotonic()
        with pytest.raises(jobs.RenderBusy):
            calls[operation]()
        assert monotonic() - start < 1
        assert section_preview_fingerprint(draft, 'cover') == identity
    finally:
        jobs._WORK_SLOT.release()
    assert (library._profile_path(profile.contract, profile.key)/'manifest.json').read_bytes() == before
    assert calls[operation]() is not None
    receipt = next((library._profile_path(profile.contract, profile.key)/'imports').glob('*.source-view.json'))
    receipt.write_bytes(b'{}')
    with pytest.raises(ValueError):
        calls[operation]()
    with pytest.raises(ValueError):
        section_preview_fingerprint(draft, 'cover')


@pytest.mark.parametrize('blocked_call', [1, 2])
def test_real_guided_busy_retry_preserves_browser_edits(sample, monkeypatch, blocked_call):
    from app import monthly_report_guided as guided, monthly_report_start_ui as start_ui
    path, view, profile, period, *_ = sample
    draft, _ = save_sample(sample)
    monkeypatch.setattr(guided, 'remembered_report_preferences', lambda token: (profile.contract, profile.key))
    monkeypatch.setattr(guided.active_work, 'enabled', lambda token: False)
    monkeypatch.setattr(start_ui, 'choose_contract', lambda *args: profile.contract)
    monkeypatch.setattr(start_ui, 'select_sites', lambda *args, **kwargs: (profile, profile))
    monkeypatch.setattr(guided, 'month_selector', lambda *args: period)
    real = library.load_imported_draft
    state = {'calls': 0, 'held': False, 'blocked': False, 'armed': False}
    def load(*args, **kwargs):
        state['calls'] += 1
        if state['armed'] and not state['blocked'] and state['calls'] == blocked_call:
            assert jobs._WORK_SLOT.acquire(blocking=False)
            state.update(held=True, blocked=True)
        return real(*args, **kwargs)
    monkeypatch.setattr(library, 'load_imported_draft', load)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_ui import _field, _move, restore_report_draft_state
from app.monthly_report_guided import render_guided_workflow
restore_report_draft_state()
_field('report_synthetic_pending_edit', 'Synthetic unsaved wording')
render_guided_workflow('', '', _field, _move)
''', default_timeout=30)
    app.run()
    assert not app.exception
    prepared = next(w for w in app.text_input if w.label == 'Prepared by')
    prepared.set_value('Synthetic unsaved editor name')
    state.update(calls=0, armed=True)
    try:
        app.run()
        assert not app.exception
        assert not any(w.label == 'Prepared by' for w in app.text_input)
        assert any('Another report is being prepared' in x.value for x in app.info)
        assert app.session_state['report_draft_mirror']['report_synthetic_pending_edit'] == 'Synthetic unsaved wording'
        retry = next(b for b in app.button if b.label == 'Retry')
    finally:
        if state['held']:
            jobs._WORK_SLOT.release()
            state['held'] = False
    retry.click().run()
    assert not app.exception
    assert not any('Another report is being prepared' in x.value for x in app.info)
    assert app.session_state['report_synthetic_pending_edit'] == 'Synthetic unsaved wording'
    assert next(w for w in app.text_input if w.label == 'Prepared by').value == 'Synthetic unsaved editor name'
    assert state['calls'] > blocked_call


def test_section_setup_default_branch_handles_busy():
    app = AppTest.from_string('''
from app.monthly_report_section_ui import _source_view_admission
from app.monthly_report_render_jobs import RenderBusy
@_source_view_admission
def render():
    raise RenderBusy('Synthetic contention')
render()
''').run()
    assert not app.exception
    assert any(b.label == 'Retry' for b in app.button)


def test_monthly_boundary_handles_busy_from_alternate_workflow(monkeypatch):
    from app import monthly_report_guided as guided
    def busy(*args, **kwargs):
        raise jobs.RenderBusy('Synthetic alternate workflow contention')
    monkeypatch.setattr(guided, 'render_guided_workflow', busy)
    app = AppTest.from_string('''
from app.monthly_report_ui import render_monthly_report_workflow
render_monthly_report_workflow('')
''').run()
    assert not app.exception and not app.error
    assert any(b.label == 'Retry' for b in app.button)
