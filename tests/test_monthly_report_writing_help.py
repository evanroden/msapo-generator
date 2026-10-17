"""Optional wording help applies only exact reviewed source/report revisions."""

from dataclasses import replace
from concurrent.futures import Future

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_ai as ai, monthly_report_ai_ui as ui
from app.monthly_report_model import EvidenceFact, ReportPeriod, ReportSource, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_sources import SourceContent


APP = """
import streamlit as st
from dataclasses import replace
from app.monthly_report_ai_ui import render_drafting
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_ui import _field
draft = st.session_state.get('returned_draft', st.session_state['fixture_draft'])
block = st.session_state.setdefault('current_block', ResolvedBlock('activity_summary', 'This month', text='Manual current wording.'))
draft, blocks = render_drafting(draft, {'activity_summary': block}, 'writing', _field,
                               allowed_keys={'activity_summary'})
st.session_state['current_block'] = blocks['activity_summary']
st.session_state['returned_draft'] = draft
"""


def component(monkeypatch, tmp_path, *, native=False):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ui, "start_receipt", lambda *args: pytest.fail("No paid reading in UI tests"))
    source = ReportSource("synthetic-writing-source", "synthetic.txt", "a" * 64, ".txt",
                          page_texts=("Inspected the synthetic pump. Inspected the synthetic valve.",))
    facts = (EvidenceFact("fact-pump", source.id, 1, "action", "Inspected the synthetic pump.",
                          "Inspected the synthetic pump."),)
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    script = APP
    if native:
        script = APP.replace("st.session_state['current_block'] = blocks['activity_summary']", """
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec
blocks['activity_summary'] = _edit_content(
    BlockSpec('activity_summary', 'rich_text'), blocks['activity_summary'], None,
    'writing', {}, _field, draft)
st.session_state['current_block'] = blocks['activity_summary']
""")
    app = AppTest.from_string(script)
    app.session_state['fixture_draft'] = draft
    app.session_state['writing_evidence'] = (SourceContent(source),)
    app.session_state['writing_ai_facts'] = (source.id, source.fingerprint, facts)
    app.run()
    assert not app.exception
    return app, source, facts


def approve_action(app):
    # This same stale native event is exercised before and after consolidation.
    confirmation = next((item for item in app.checkbox
                         if item.label == 'Use these facts as evidence for suggestions'), None)
    if confirmation is not None:
        confirmation.check().run()
    return next(item for item in app.button if item.label in ('Keep these facts', 'Use these facts'))


@pytest.mark.parametrize('change', ['facts', 'source_context'])
def test_old_fact_action_cannot_approve_a_new_proposal(monkeypatch, tmp_path, change):
    app, source, facts = component(monkeypatch, tmp_path)
    old_action = approve_action(app)
    if change == 'source_context':
        source = replace(source, findings='New corrected source context.')
        app.session_state['writing_evidence'] = (SourceContent(source),)
        revised = facts
    else:
        revised = (replace(facts[0], id='fact-valve', text='Inspected the synthetic valve.',
                           quote='Inspected the synthetic valve.'),)
    app.session_state['writing_ai_facts'] = (source.id, source.fingerprint, revised)
    old_action.click().run()
    assert not app.exception
    assert app.session_state['writing_evidence'][0].source.facts == ()
    assert app.session_state['writing_ai_facts'][2] == revised


def checked_suggestion(app, source, facts):
    source = replace(source, facts=facts)
    app.session_state['writing_evidence'] = (SourceContent(source),)
    app.session_state['writing_ai_suggestion'] = ai.normalize_draft(
        {'paragraphs': [{'text': facts[0].text, 'fact_ids': [facts[0].id]}]},
        'activity_summary', facts, (source,))
    app.run()
    next(item for item in app.checkbox if item.label == 'I checked paragraph 1 against its source').check().run()
    assert not app.exception
    return source


def test_one_explicit_fact_action_keeps_flags_original_pages_and_current_wording(monkeypatch, tmp_path):
    app, source, facts = component(monkeypatch, tmp_path)
    assert all(item.label != 'Use these facts as evidence for suggestions' for item in app.checkbox)
    assert sum(item.label == 'Use these facts' for item in app.button) == 1
    for label in ('Help write this summary', 'Limits', 'Use Copilot'):
        assert not next(item for item in app.expander if item.label == label).proto.expanded
    assert any('external document reader' in item.value and 'paid requests' in item.value for item in app.caption)
    flagged = (replace(facts[0], flags=('Outside the reporting month',)),)
    app.session_state['writing_ai_facts'] = (source.id, source.fingerprint, flagged)
    app.run()
    next(item for item in app.button if item.label == 'Use these facts').click().run()
    assert not app.exception
    accepted = app.session_state['writing_evidence'][0].source
    assert accepted.facts == flagged and accepted.selected_pages == source.selected_pages
    assert app.session_state['current_block'].text == 'Manual current wording.'
    assert not any(item.label == 'Use these facts' for item in app.button)


def test_empty_proposal_cannot_clear_previously_accepted_facts(monkeypatch, tmp_path):
    app, source, facts = component(monkeypatch, tmp_path)
    source = replace(source, facts=facts)
    app.session_state['writing_evidence'] = (SourceContent(source),)
    app.session_state['writing_ai_facts'] = (source.id, source.fingerprint, ())
    app.run()
    action = next(item for item in app.button if item.label == 'Use these facts')
    assert action.disabled
    action.click().run()
    assert not app.exception and app.session_state['writing_evidence'][0].source.facts == facts


@pytest.mark.parametrize('change', ['reset_epoch', 'qa_generation', 'selected_source'])
def test_old_fact_action_cannot_cross_reset_or_source_selection(monkeypatch, tmp_path, change):
    app, source, facts = component(monkeypatch, tmp_path)
    old_action = approve_action(app)
    if change == 'reset_epoch':
        app.session_state['writing_rich_text_epoch'] = 'different-report-incarnation'
    elif change == 'qa_generation':
        app.session_state['_monthly_qa_generation'] = 'different-isolated-generation'
    else:
        other = replace(source, id='different-source', filename='other.txt', sha256='b' * 64)
        app.session_state['writing_evidence'] = (SourceContent(source), SourceContent(other))
        app.run()
        old_action = approve_action(app)
        next(item for item in app.selectbox if item.label == 'File to read for work performed').set_value(other.id)
    old_action.click().run()
    assert not app.exception
    assert all(not content.source.facts for content in app.session_state['writing_evidence'])


def test_late_draft_result_keeps_newer_manual_wording_until_explicit_add(monkeypatch, tmp_path):
    app, source, facts = component(monkeypatch, tmp_path)
    approve_action(app).click().run()
    source = app.session_state['writing_evidence'][0].source
    current = replace(app.session_state['current_block'], text='Newer manual report wording.')
    app.session_state['current_block'] = current
    future = Future()
    future.set_result({'paragraphs': [{'text': facts[0].text, 'fact_ids': [facts[0].id]}]})
    app.session_state['writing_ai_job'] = {
        'kind': 'draft', 'future': future, 'block': 'activity_summary', 'facts': facts,
        'key': 'd' * 64, 'source_fingerprints': (source.fingerprint,),
    }
    app.run()
    assert not app.exception and app.session_state['current_block'] == current
    next(item for item in app.checkbox if item.label == 'I checked paragraph 1 against its source').check().run()
    next(item for item in app.button if item.label == 'Use checked wording in this report').click().run()
    assert not app.exception
    assert app.session_state['current_block'].text.startswith(current.text)
    assert facts[0].text in app.session_state['current_block'].text


def test_old_replace_action_cannot_overwrite_a_newer_manual_block(monkeypatch, tmp_path):
    app, source, facts = component(monkeypatch, tmp_path)
    checked_suggestion(app, source, facts)
    next(item for item in app.radio if item.label == 'Use the checked suggestion').set_value('Replace existing wording').run()
    old_action = next(item for item in app.button if item.label == 'Use checked wording in this report')
    current = replace(app.session_state['current_block'], text='New manual edit after the prior comparison.')
    app.session_state['current_block'] = current
    old_action.click().run()
    assert not app.exception and app.session_state['current_block'] == current
    assert 'writing_ai_suggestion' in app.session_state
    # A new explicit click after the current wording is displayed may replace it.
    next(item for item in app.button if item.label == 'Use checked wording in this report').click().run()
    assert not app.exception and app.session_state['current_block'].text == '- ' + facts[0].text


def test_pending_native_manual_submission_wins_over_old_replace_action(monkeypatch, tmp_path):
    app, source, facts = component(monkeypatch, tmp_path, native=True)
    checked_suggestion(app, source, facts)
    next(item for item in app.radio if item.label == 'Use the checked suggestion').set_value('Replace existing wording').run()
    action = next(item for item in app.button if item.label == 'Use checked wording in this report')
    # Deliver the native text change and the prior action in the same request.
    # Production callback receipts arrive before drafting, whose UI precedes
    # the canonical Activity editor in the ordered workspace.
    next(item for item in app.text_area if item.label == 'Activity summary').set_value('Pending newer manual wording.')
    action.click().run()
    assert not app.exception
    assert app.session_state['current_block'].text == 'Pending newer manual wording.'
    assert next(item for item in app.text_area if item.label == 'Activity summary').value == 'Pending newer manual wording.'
    assert 'writing_ai_suggestion' in app.session_state
    assert any('Pending newer manual wording.' in item.value for item in app.text)
    # The current comparison/action stays usable after the normal commit;
    # there is no extra edit, synthetic blur, or other rescue gesture.
    fresh = next(item for item in app.button if item.label == 'Use checked wording in this report')
    assert not fresh.disabled
    fresh.click().run()
    assert not app.exception and app.session_state['current_block'].text == '- ' + facts[0].text
