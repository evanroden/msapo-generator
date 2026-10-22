"""Independent review probes; AppTest input delivery, not browser timing."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportPeriod, default_sections, synthetic_profiles


SCRIPT = '''
import streamlit as st
from app.monthly_report_followups import render_followups
from app.monthly_report_issues import acknowledge_issue_controls
from app.monthly_report_ui import _field, preserve_report_draft_state, restore_report_draft_state
restore_report_draft_state()
st.session_state['draft'] = render_followups(st.session_state['draft'], 'review_pages', _field,
    category=st.session_state['category'])
# Issue receipts are retired only by the authoritative caller, as the
# guided workspace does after assigning its canonical draft.
acknowledge_issue_controls(st.session_state['draft'], 'review_pages')
preserve_report_draft_state()
'''


def workspace(category):
    items = tuple(ReportFollowUp(f'{category}-{i}', category, f'Inspect damper D-{i:03}', '2026-09',
        status='pending' if category == 'proposal' else 'ongoing') for i in range(30))
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10), 'Synthetic Editor',
        default_sections(), (), follow_ups=items)
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state['category'] = category
    app.session_state['draft'] = draft
    app.run()
    if category == 'proposal':
        next(button for button in app.button if button.label == 'Update proposal').click().run()
    assert not app.exception
    return app


def text_field(app, category):
    label = 'Proposal scope' if category == 'proposal' else 'Issue description'
    return next(widget for widget in app.text_area if widget.label == label)


def page(app, category):
    return next(widget for widget in app.selectbox
                if widget.label == ('Proposal page' if category == 'proposal' else 'Issue page'))


@pytest.mark.parametrize('category', ['issue', 'proposal'])
def test_delivered_old_editor_text_cannot_modify_replacement_report_on_page_change(category):
    app = workspace(category)
    current = app.session_state['draft']
    text_field(app, category).set_value('Earlier editor wording must remain recoverable')
    app.session_state['draft'] = replace(current, period=ReportPeriod(2026, 11))
    app.session_state['review_pages_rich_text_epoch'] = 'replacement-report-incarnation'
    page(app, category).set_value(2).run()
    assert not app.exception
    assert app.session_state['draft'].follow_ups[0].text == current.follow_ups[0].text


@pytest.mark.parametrize('category', ['issue', 'proposal'])
def test_acknowledged_off_page_text_cannot_replay_after_a_later_canonical_replacement(category):
    app = workspace(category)
    before = app.session_state['draft']
    text_field(app, category).set_value('Accepted earlier edit')
    page(app, category).set_value(2).run()
    assert not app.exception
    current = app.session_state['draft']
    assert current.follow_ups[0].text == 'Accepted earlier edit'
    replacement = replace(current, follow_ups=(before.follow_ups[0], *current.follow_ups[1:]))
    app.session_state['draft'] = replacement
    app.run()
    assert not app.exception
    assert app.session_state['draft'].follow_ups[0] == before.follow_ups[0]
