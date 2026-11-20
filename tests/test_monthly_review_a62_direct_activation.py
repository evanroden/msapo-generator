"""A62 direct-Review visibility activation: deterministic synthetic server receipts.

These AppTests do not emulate a native browser's IntersectionObserver, actual
installed master, or live served build. Existing final DOCX/PDF tests cover the
output path separately.
"""
from dataclasses import replace

import pymupdf as fitz
import pytest

from app import monthly_report_review_preview_ui as review_ui
from app.monthly_report_review_activation import valid_activation
from app.monthly_report_source_view_runtime import preview_fingerprint
from test_monthly_report_review_direct_preview import (
    setup, initial, owner, preview_state, synthetic_preview,
)


@pytest.mark.parametrize("receipt", [
    None, {}, [], {"activation": None},
    {"activation": {"identity": "x" * 64, "visible": True}},
    {"activation": {"identity": "a" * 64, "visible": "true"}},
    {"activation": {"identity": "a" * 64, "visible": False}},
    {"activation": {"identity": 1, "visible": True}},
])
def test_missing_wrong_revision_or_malformed_visibility_does_not_activate(receipt):
    assert not valid_activation(receipt, "a" * 64)


def test_matching_receipt_is_revision_specific_and_carries_no_form_content():
    identity = "a" * 64
    assert valid_activation({"activation": {"identity": identity, "visible": True}}, identity)
    assert not valid_activation({"activation": {"identity": identity, "visible": True}}, "b" * 64)


def test_receipt_in_streamlits_own_component_state_type_activates():
    # Streamlit hands a v2 component's state over as an AttributeDictionary
    # (a dict subclass); a plain-dict-only check never activated in a browser.
    from streamlit.util import AttributeDictionary
    identity = "a" * 64
    state = AttributeDictionary({"activation": {"identity": identity, "visible": True}})
    assert type(state) is not dict
    assert valid_activation(state, identity)
    assert not valid_activation(AttributeDictionary({"activation": None}), identity)


def test_direct_review_visibility_auto_builds_unvisited_last_section_once(monkeypatch, tmp_path):
    app, store = setup(monkeypatch, tmp_path)
    try:
        calls = []
        def checked(draft, loader, *, ticket_only=False):
            calls.append(draft)
            return synthetic_preview(draft, loader)
        monkeypatch.setattr(review_ui, 'preview_report', checked)
        current = app.session_state['draft']
        identity = preview_fingerprint(current)
        assert not preview_state(app)
        # Simulates the validated browser activation, not a real browser.
        app.session_state['review_direct_review_preview_activation'] = identity
        app.run()
        assert not app.exception
        state = preview_state(app)
        assert state['fingerprint'] == identity
        assert calls == [current]
        assert app.session_state['draft'] == current
        assert store.available(owner(app), state['ticket'])
        with fitz.open(store._files[state['ticket'].key].path) as pdf:
            assert len(pdf) == 2
            assert 'last-section fact' in pdf[1].get_text()
        assert any('Current draft · page 1 of 2' in c.value for c in app.caption)
        app.run()
        assert calls == [current], "a routine rerun must not duplicate conversion"
        assert store.stats()['pdf_entries'] == 1
    finally:
        store.close()


def test_accepted_edit_refresh_failure_keeps_outdated_pages_and_retry(monkeypatch, tmp_path):
    app, store = setup(monkeypatch, tmp_path)
    try:
        monkeypatch.setattr(review_ui, 'preview_report', synthetic_preview)
        first = app.session_state['draft']
        app.session_state['review_direct_review_preview_activation'] = preview_fingerprint(first)
        app.run()
        assert not app.exception
        prior = preview_state(app)
        old_path = store._files[prior['ticket'].key].path
        changed = replace(first, prepared_by='Synthetic retained accepted text')
        app.session_state['draft'] = changed
        identity = preview_fingerprint(changed)
        attempts = []
        def broken(draft, loader, *, ticket_only=False):
            attempts.append(draft)
            raise ValueError('Synthetic retryable PDF conversion failure')
        monkeypatch.setattr(review_ui, 'preview_report', broken)
        app.session_state['review_direct_review_preview_activation'] = identity
        app.run()
        assert not app.exception and len(attempts) == 1
        assert preview_state(app) == prior
        assert old_path.exists()
        assert store.available(owner(app), prior['ticket'])
        assert any('latest changes not shown' in c.value for c in app.caption)
        assert not any('Current draft · page' in c.value for c in app.caption)
        assert any('retryable PDF conversion' in w.value for w in app.warning)
        app.run()
        assert len(attempts) == 1, 'failed automatic conversion must not loop'
        monkeypatch.setattr(review_ui, 'preview_report', synthetic_preview)
        next(b for b in app.button if b.label == 'Preview current draft').click().run()
        fresh = preview_state(app)
        assert fresh['fingerprint'] == identity and fresh['ticket'] != prior['ticket']
        assert store.available(owner(app), fresh['ticket'])
        assert not old_path.exists()
        assert app.session_state['draft'] == changed
        assert any('Current draft · page 1 of 2' in c.value for c in app.caption)
    finally:
        store.close()


def test_wrong_month_activation_never_renders_new_draft(monkeypatch, tmp_path):
    app, store = setup(monkeypatch, tmp_path)
    try:
        calls = []
        monkeypatch.setattr(review_ui, 'preview_report', lambda draft, loader, ticket_only=False:
                            calls.append(draft) or synthetic_preview(draft, loader))
        from app.monthly_report_model import ReportPeriod
        changed = replace(app.session_state['draft'], period=ReportPeriod(2026, 10))
        app.session_state['draft'] = changed
        app.session_state['review_direct_review_preview_activation'] = preview_fingerprint(initial())
        app.run()
        assert not app.exception and not calls and not preview_state(app)
        assert store.stats()['pdf_entries'] == 0
    finally:
        store.close()


def test_shared_snapshot_reopen_enters_review_directly_from_saved_draft(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_library as library
    from app.contracts import RRH_CONTRACT
    from app.monthly_report_model import ReportPeriod
    from test_monthly_report_ui import ROOT, monthly, choose_report
    # Run against the same synthetic profile and on-disk snapshot but a *new*
    # Streamlit session. No section preview component is activated by this test.
    calls = []
    def renderer(draft, loader, *, ticket_only=False):
        calls.append(draft)
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 72), 'Synthetic saved Review')
            return ReportPreview(pdf.tobytes(), 1, preview_fingerprint(draft), draft.period.label)
    from app.monthly_report_preview import ReportPreview
    from app.monthly_report_preview_store import PreviewStore
    store = PreviewStore()
    monkeypatch.setattr(review_ui, 'STORE', store)
    monkeypatch.setattr(review_ui, 'preview_report', lambda draft, loader, ticket_only=False:
                        renderer(draft, loader))
    try:
        app = monthly(monkeypatch, tmp_path)
        next(w for w in app.text_input if w.label == 'Prepared by').set_value(
            'Synthetic saved reviewer').run()
        next(w for w in app.text_area if w.label == 'Activity summary').set_value(
            'Synthetic saved final Review fact.').run()
        next(b for b in app.button if b.label == 'Save shared version').click().run()
        assert not app.exception
        saved = library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', ReportPeriod(2026, 9))
        assert any(b.text == 'Synthetic saved final Review fact.' for b in saved.draft.blocks)
        fresh = AppTest.from_file(ROOT / 'run_web.py', default_timeout=30).run()
        fresh.segmented_control[0].set_value('Monthly report').run()
        choose_report(fresh, saved.draft.profile.facilities[0].title)
        assert not fresh.exception
        state_key = next(k for k in fresh.session_state.filtered_state
                         if k.startswith('report_guided_') and k.endswith('_draft')
                         and hasattr(fresh.session_state[k], 'blocks'))
        prefix = state_key.removesuffix('_draft')
        current = fresh.session_state[state_key]
        assert any(b.text == 'Synthetic saved final Review fact.' for b in current.blocks)
        fresh.session_state[prefix + '_review_preview_activation'] = preview_fingerprint(current)
        fresh.run()
        assert not fresh.exception
        assert calls and calls[-1].fingerprint == current.fingerprint
        ticket = fresh.session_state[prefix + '_review_draft_preview']
        assert ticket['fingerprint'] == preview_fingerprint(current)
        assert any('Current draft · page 1 of 1' in c.value for c in fresh.caption)
        assert any(b.text == 'Synthetic saved final Review fact.' for b in calls[-1].blocks)
        assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided',
                                     ReportPeriod(2026, 9)) == saved
    finally:
        store.close()
