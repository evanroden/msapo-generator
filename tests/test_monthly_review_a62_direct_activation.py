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


def test_direct_review_visibility_auto_builds_unvisited_last_section_once(monkeypatch, tmp_path):
    app, store = setup(monkeypatch, tmp_path)
    try:
        calls = []
        def checked(draft, loader):
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
        def broken(draft, loader):
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
        monkeypatch.setattr(review_ui, 'preview_report', lambda draft, loader:
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
