"""Review regressions for proposal pagination and interrupted input recovery.

Synthetic AppTest proves real callbacks and authoritative assignment boundaries.
No genuine report, directory, or source data is used.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import (
    ReportDraft, ReportFollowUp, ReportPeriod, ReportSource, synthetic_profiles,
)
from app.monthly_report_sources import source_reference


SCRIPT = """
import streamlit as st
from app.monthly_report_followups import render_followups, acknowledge_followup_controls
from app.monthly_report_ui import _field
result = render_followups(st.session_state['draft'], 'review_paged_proposals', _field,
                          category='proposal', defer_commit=True)
if st.session_state.pop('interrupt_once', False):
    st.session_state['interrupted_result'] = result
    st.stop()
st.session_state['draft'] = result
acknowledge_followup_controls(result, 'review_paged_proposals')
"""


def workspace(count=30, *, legacy_last=False):
    source = ReportSource(
        'invented', 'invented-review.txt', 'c' * 64, '.txt',
        page_texts=('Invented observation A.', 'Invented observation B.'),
    )
    rows = tuple(
        ReportFollowUp(
            f'proposal-{i}', 'proposal',
            ('Inspect fan drive; Status: Declined' if legacy_last and i == count - 1
             else f'Inspect synthetic fan drive {i:03}.'),
            '2026-09',
            status=('ongoing' if legacy_last and i == count - 1 else 'pending'),
        )
        for i in range(count)
    )
    draft = ReportDraft(
        synthetic_profiles()[0], ReportPeriod(2026, 10), 'Synthetic editor',
        (), (), sources=(source,), follow_ups=rows, synthetic=True,
    )
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state['draft'] = draft
    app.run()
    assert not app.exception
    return app, draft, source


def edit_first(app):
    next(widget for widget in app.button if widget.label == 'Update proposal').click().run()
    assert not app.exception


def page(app):
    return next(widget for widget in app.selectbox if widget.label == 'Proposal page')


def codes(app):
    return '\n'.join(widget.proto.code_text for widget in app.get('code'))


def test_legacy_proposal_on_hidden_page_normalizes_without_visiting_that_page():
    app, before, _ = workspace(30, legacy_last=True)
    assert before.follow_ups[-1].status == 'ongoing'
    assert app.session_state['draft'].follow_ups[-1].status == 'declined'
    assert app.session_state['draft'].follow_ups[-1].text == 'Inspect fan drive'
    assert len(app.session_state['draft'].follow_ups) == 30
    assert page(app).value == 1


def test_removed_last_proposal_still_shows_its_interrupted_edit():
    app, before, _ = workspace(1)
    edit_first(app)
    app.session_state['interrupt_once'] = True
    next(widget for widget in app.text_area if widget.label == 'Proposal scope').set_value(
        'Earlier unsaved scope that must stay copyable').run()
    assert not app.exception and app.session_state['draft'] == before
    app.session_state['draft'] = replace(before, follow_ups=())
    app.run()
    assert not app.exception
    assert app.session_state['draft'].follow_ups == ()
    assert 'Earlier unsaved scope that must stay copyable' in codes(app)
    key = 'review_paged_proposals_pending_followup_proposal_proposal-0'
    assert app.session_state[key]['conflicted'] is True
    assert app.session_state[key]['after'].text == 'Earlier unsaved scope that must stay copyable'


@pytest.mark.parametrize('kind', ['text', 'source'])
def test_rejected_off_page_receipt_cannot_reapply_when_old_row_returns(kind):
    app, before, source = workspace(30)
    edit_first(app)
    original = before.follow_ups[0]
    if kind == 'text':
        control = next(widget for widget in app.text_area if widget.label == 'Proposal scope')
        earlier = 'Earlier delivered but not committed proposal scope'
    else:
        control = next(widget for widget in app.multiselect
                       if widget.label == 'Supporting source pages (optional)')
        earlier = [source_reference(source, 2)]
    app.session_state['interrupt_once'] = True
    control.set_value(earlier).run()
    assert not app.exception and app.session_state['draft'] == before
    newer = replace(original, text='New independently saved proposal scope.')
    app.session_state['draft'] = replace(before, follow_ups=(newer, *before.follow_ups[1:]))
    page(app).set_value(2).run()
    assert not app.exception
    assert app.session_state['draft'].follow_ups[0] == newer
    earlier_text = earlier if isinstance(earlier, str) else 'invented-review.txt'
    assert earlier_text in codes(app)
    stale = [key for key in app.session_state if key.startswith(
        'review_paged_proposals_follow_proposal-0_compact_') and key.endswith('_change')]
    assert stale == [], 'Rejected off-page callback must be retired immediately.'
    # A later row restoration cannot turn an earlier rejected callback into
    # a new authorization, even if its pending recovery panel is dismissed.
    app.session_state.pop('review_paged_proposals_pending_followup_proposal_proposal-0', None)
    app.session_state['draft'] = before
    page(app).set_value(1).run()
    assert not app.exception
    assert app.session_state['draft'].follow_ups[0] == original
    assert earlier_text in codes(app), 'Earlier entered data stays copyable.'


def test_missing_row_recovery_does_not_touch_other_proposals():
    app, before, _ = workspace(30)
    edit_first(app)
    app.session_state['interrupt_once'] = True
    next(widget for widget in app.text_area if widget.label == 'Proposal scope').set_value(
        'Removed proposal earlier draft').run()
    app.session_state['draft'] = replace(before, follow_ups=before.follow_ups[1:])
    app.run()
    assert not app.exception
    assert len(app.session_state['draft'].follow_ups) == 29
    assert app.session_state['draft'].follow_ups == before.follow_ups[1:]
    assert 'Removed proposal earlier draft' in codes(app)
