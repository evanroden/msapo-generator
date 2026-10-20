"""Refs #278/#280: delivered native values survive an interrupted full commit.

AppTest deliberately stops after the real row renderer returns, before the
caller assigns the canonical draft. This models that precise boundary; the
unchanged Chromium/WebKit source-correction journey proves native delivery.
The signature adapter only lets the same desired assertion run before the
deferred-commit API existed. It does not implement the receipt behavior.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportPeriod, ReportSource, synthetic_profiles
from app.monthly_report_sources import source_reference


SCRIPT = '''
import inspect
import streamlit as st
from app import monthly_report_followups as followups
from app.monthly_report_ui import _field
kwargs = {'category': st.session_state['category']}
if 'defer_commit' in inspect.signature(followups.render_followups).parameters:
    kwargs['defer_commit'] = True
result = followups.render_followups(st.session_state['draft'], 'delivery', _field, **kwargs)
if st.session_state.pop('interrupt_once', False):
    st.session_state['interrupted_result'] = result
    st.stop()
st.session_state['draft'] = result
if hasattr(followups, 'acknowledge_followup_controls'):
    followups.acknowledge_followup_controls(result, 'delivery')
'''


def workspace(category):
    source = ReportSource('independent', 'independent-evidence.txt', 'b' * 64, '.txt',
                          page_texts=('First inspection.', 'Separate second inspection.'))
    item = ReportFollowUp('row-one', category, 'Inspect intake damper.', '2026-10',
        status='ongoing' if category == 'issue' else 'pending',
        references=('missing:original:page',))
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10), 'Synthetic editor',
        (), (), sources=(source,), follow_ups=(item,), synthetic=True)
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state['category'] = category
    app.session_state['draft'] = draft
    app.run()
    assert not app.exception
    return app, source


def source_picker(app):
    return next(widget for widget in app.multiselect if widget.label.startswith('Supporting source pages'))


@pytest.mark.parametrize('category', ['issue', 'proposal'])
def test_delivered_selection_survives_interruption_then_unrelated_missing_link_removal(category):
    app, source = workspace(category)
    before = app.session_state['draft']
    selected = source_reference(source, 2)
    app.session_state['interrupt_once'] = True
    source_picker(app).set_value([selected]).run()
    assert not app.exception
    assert app.session_state['interrupted_result'].follow_ups[0].references == (selected, 'missing:original:page')
    assert app.session_state['draft'] == before, 'The interruption must occur before canonical assignment.'
    next(widget for widget in app.checkbox if widget.label == 'Remove unavailable source links').check().run()
    assert not app.exception
    assert app.session_state['draft'].follow_ups[0].references == (selected,)
    assert source_picker(app).value == [selected]
    assert not any('source changed or is missing' in item.value or 'source links are unavailable' in item.value
                   for item in app.warning)
    app.run()
    assert app.session_state['draft'].follow_ups[0].references == (selected,)


@pytest.mark.parametrize('category', ['issue', 'proposal'])
@pytest.mark.parametrize('replacement', ['row', 'period', 'editor', 'source'])
def test_interrupted_selection_cannot_approve_a_replaced_row_report_or_source(category, replacement):
    app, source = workspace(category)
    before = app.session_state['draft']
    selected = source_reference(source, 2)
    app.session_state['interrupt_once'] = True
    source_picker(app).set_value([selected]).run()
    assert not app.exception and app.session_state['draft'] == before
    if replacement == 'row':
        before = replace(before, follow_ups=(replace(before.follow_ups[0], text='New independently saved finding.'),))
    elif replacement == 'period':
        before = replace(before, period=ReportPeriod(2026, 11))
    elif replacement == 'editor':
        app.session_state['delivery_rich_text_epoch'] = 'replacement-editor'
    else:
        before = replace(before, sources=(replace(source, page_texts=('Changed first page.', 'Changed second page.')),))
    app.session_state['draft'] = before
    app.run()
    assert not app.exception
    assert app.session_state['draft'] == before


@pytest.mark.parametrize('category', ['issue', 'proposal'])
def test_acknowledged_selection_does_not_replay_after_an_independent_canonical_change(category):
    app, source = workspace(category)
    before = app.session_state['draft']
    source_picker(app).set_value([source_reference(source, 2)]).run()
    assert not app.exception
    assert app.session_state['draft'].follow_ups[0].references[0] == source_reference(source, 2)
    app.session_state['draft'] = before
    app.run()
    assert not app.exception and app.session_state['draft'] == before


@pytest.mark.parametrize('category', ['issue', 'proposal'])
def test_native_source_default_matches_the_committed_selection_and_deliberate_clear(category):
    app, source = workspace(category)
    native_id = source_picker(app).id
    for selection in ([source_reference(source, 2)], []):
        source_picker(app).set_value(selection).run()
        assert not app.exception
        picker = source_picker(app)
        assert picker.value == selection
        assert list(picker.proto.default) == ([1] if selection else []), 'Native default must agree with the accepted source selection.'
        assert picker.id == native_id, 'Selecting evidence must preserve the native input node.'
