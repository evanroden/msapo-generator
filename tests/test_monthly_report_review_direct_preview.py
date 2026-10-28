"""Review's full-draft preview is revision-bound and independent of scroll order.

These are synthetic AppTest/real PDF cache controls. Actual served browser,
installed client-master and native Word/PDF parity remain separate gates.
"""
from dataclasses import replace

import pymupdf as fitz
from streamlit.testing.v1 import AppTest

from app import monthly_report_review_preview_ui as review_ui
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_preview import ReportPreview
from app.monthly_report_preview_store import PreviewStore
from app.monthly_report_source_view_runtime import preview_fingerprint


APP = """
import streamlit as st
from app.monthly_report_review_preview_ui import render_review_preview
render_review_preview(st.session_state['draft'], {}, 'review_direct')
"""


def initial():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    # The last section was never visited or rendered through a section pane.
    blocks = tuple(replace(block, text="Synthetic last-section fact for Review.")
                   if block.key == "demo_training" else block
                   for block in draft.blocks)
    return replace(draft, blocks=blocks)


def setup(monkeypatch, tmp_path, *, draft=None):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    store = PreviewStore()
    monkeypatch.setattr(review_ui, "STORE", store)
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state['draft'] = draft or initial()
    app.run()
    assert not app.exception
    return app, store


def synthetic_preview(draft, loader):
    """Render two actual PDF pages with the last-section draft fact."""
    assert any('last-section fact' in block.text for block in draft.blocks)
    text = '\n'.join(block.text for block in draft.blocks)
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Synthetic review cover")
        pdf.new_page().insert_text((72, 72), "Synthetic last-section fact for Review.")
        return ReportPreview(pdf.tobytes(), len(pdf), preview_fingerprint(draft),
                             draft.period.label)


def preview_state(app):
    # AppTest exposes SafeSessionState, which has no dict-style .get method.
    return app.session_state.filtered_state.get('review_direct_review_draft_preview')


def owner(app):
    return app.session_state['review_direct_review_preview_owner']


def click_preview(app):
    next(button for button in app.button
         if button.label == "Preview current draft").click().run()
    assert not app.exception


def test_direct_review_renders_unvisited_section_on_first_activation(monkeypatch, tmp_path):
    app, store = setup(monkeypatch, tmp_path)
    try:
        assert not app.number_input
        assert not preview_state(app)
        unchanged = app.session_state['draft']
        calls = []
        def render(draft, loader):
            calls.append(draft)
            return synthetic_preview(draft, loader)
        monkeypatch.setattr(review_ui, 'preview_report', render)
        click_preview(app)
        assert calls == [unchanged]
        assert app.session_state['draft'] == unchanged
        state = preview_state(app)
        assert state['fingerprint'] == preview_fingerprint(unchanged)
        assert store.available(owner(app), state['ticket'])
        with fitz.open(store._files[state['ticket'].key].path) as pdf:
            assert len(pdf) == 2
            assert 'last-section fact' in pdf[1].get_text()
        assert any('Current draft · page 1 of 2' in value.value for value in app.caption)
        next(field for field in app.number_input
             if field.label == 'Draft preview page').set_value(2).run()
        assert not app.exception and preview_state(app) == state
        assert any('Current draft · page 2 of 2' in value.value for value in app.caption)
        assert calls == [unchanged]
    finally:
        store.close()


def test_new_edit_retire_old_ticket_before_any_current_claim(monkeypatch, tmp_path):
    app, store = setup(monkeypatch, tmp_path)
    try:
        monkeypatch.setattr(review_ui, 'preview_report', synthetic_preview)
        click_preview(app)
        before = preview_state(app)
        assert store.available(owner(app), before['ticket'])
        old = app.session_state['draft']
        revised = replace(old, prepared_by='Synthetic changed author')
        app.session_state['draft'] = revised
        app.run()
        assert not app.exception
        assert not preview_state(app)
        assert not store.available(owner(app), before['ticket'])
        assert any('report changed' in c.value.lower() for c in app.caption)
        assert not any('Current draft · page' in c.value for c in app.caption)
        click_preview(app)
        assert preview_state(app)['fingerprint'] == preview_fingerprint(revised)
        assert preview_state(app)['ticket'] != before['ticket']
        assert app.session_state['draft'] == revised
    finally:
        store.close()


def test_profile_switch_and_cache_expiry_never_display_wrong_report(monkeypatch, tmp_path):
    app, store = setup(monkeypatch, tmp_path)
    try:
        monkeypatch.setattr(review_ui, 'preview_report', synthetic_preview)
        click_preview(app)
        prior = preview_state(app)
        changed = replace(app.session_state['draft'], profile=synthetic_profiles()[1],
                          period=ReportPeriod(2026, 10))
        app.session_state['draft'] = changed
        app.run()
        assert not app.exception and not preview_state(app)
        assert not store.available(owner(app), prior['ticket'])
        click_preview(app)
        newer = preview_state(app)
        assert newer['profile'] == (changed.profile.contract,
                                    changed.profile.key, changed.period.key)
        store._files[newer['ticket'].key].path.unlink()
        app.run()
        assert not app.exception and not preview_state(app)
        assert not store.available(owner(app), newer['ticket'])
        assert any('expired' in value.value.lower() for value in app.caption)
    finally:
        store.close()


def test_failed_preview_has_scoped_retry_and_does_not_change_canonical_data(
        monkeypatch, tmp_path):
    app, store = setup(monkeypatch, tmp_path)
    try:
        draft = app.session_state['draft']
        attempts = []
        def flaky(current, loader):
            attempts.append(current)
            if len(attempts) == 1:
                raise ValueError('Synthetic output image is beyond preview budget.')
            return synthetic_preview(current, loader)
        monkeypatch.setattr(review_ui, 'preview_report', flaky)
        click_preview(app)
        assert not preview_state(app)
        assert any('beyond preview budget' in warning.value for warning in app.warning)
        assert app.session_state['draft'] == draft and store.stats()['pdf_entries'] == 0
        click_preview(app)
        assert len(attempts) == 2 and all(x == draft for x in attempts)
        assert preview_state(app)
        assert store.stats()['pdf_entries'] == 1
    finally:
        store.close()


def test_no_included_sections_does_not_create_preview(monkeypatch, tmp_path):
    empty = replace(initial(), sections=())
    app, store = setup(monkeypatch, tmp_path, draft=empty)
    try:
        assert not preview_state(app)
        assert not any(b.label == 'Preview current draft' for b in app.button)
        assert any('No report sections' in c.value for c in app.caption)
        assert store.stats()['pdf_entries'] == 0
    finally:
        store.close()


def test_full_guided_review_preview_uses_current_draft_after_all_editors(
        monkeypatch, tmp_path):
    from test_monthly_report_ui import monthly
    calls = []
    def checked(draft, loader):
        calls.append(draft)
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 72), "Synthetic guided Review")
            return ReportPreview(pdf.tobytes(), 1, preview_fingerprint(draft),
                                 draft.period.label)
    monkeypatch.setattr(review_ui, 'preview_report', checked)
    cache = PreviewStore()
    monkeypatch.setattr(review_ui, 'STORE', cache)
    try:
        app = monthly(monkeypatch, tmp_path)
        assert not app.exception
        assert any(button.label == 'Preview current draft' for button in app.button)
        # No section was opened, visited, or used to seed the preview.
        editor = next(w for w in app.text_area if w.label == 'Activity summary')
        editor.set_value('Synthetic direct Review activity.').run()
        assert not app.exception
        current = next(v for k,v in app.session_state.filtered_state.items()
                       if k.startswith('report_guided_') and k.endswith('_draft')
                       and hasattr(v,'blocks'))
        next(b for b in app.button if b.label == 'Preview current draft').click().run()
        assert not app.exception
        assert calls and calls[-1].fingerprint == current.fingerprint
        assert any('Synthetic direct Review activity.' == block.text
                   for block in calls[-1].blocks if block.key == 'activity_summary')
        assert any('Current draft · page 1 of 1' in c.value for c in app.caption)
    finally:
        cache.close()
