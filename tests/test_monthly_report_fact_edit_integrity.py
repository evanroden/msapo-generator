"""Source/page approvals and linked wording preserve independent accepted work.

The UI cases use AppTest and completed synthetic futures, never a paid reader.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest


CONTEXT = '''
import streamlit as st
from dataclasses import replace
from concurrent.futures import Future
from app import monthly_report_ai as ai, monthly_report_ai_ui as ui
from app.monthly_report_model import ReportSource, ReportDraft, ReportPeriod, default_sections, synthetic_profiles
from app.monthly_report_sources import SourceContent
from app.monthly_report_ui import _field, preserve_report_draft_state
P, M = synthetic_profiles()[0], ReportPeriod(2026, 9)
'''


def healthy(app):
    assert not app.exception
    assert not app.error
    return app


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


LINKED = CONTEXT + '''
if 'draft' not in st.session_state:
    src = ReportSource('linked-source', 'synthetic-service.txt', '4'*64, '.txt',
                       page_texts=('Replaced inlet filter and checked the seal.',))
    facts = ai.normalize_facts({'facts':[{'page':1, 'kind':'action',
        'text':'Replaced inlet filter', 'quote':'Replaced inlet filter'}]}, src, (1,), P, M)
    src = replace(src, facts=facts)
    block = ai.normalize_draft({'paragraphs':[{'text':'Replaced inlet filter',
        'fact_ids':[facts[0].id]}]}, 'activity_summary', facts, (src,))
    block = replace(block, text=MANUAL + ('\\n' if MANUAL else '') + block.text)
    st.session_state['draft'] = ReportDraft(P, M, 'Synthetic Reviewer', default_sections(), (block,), sources=(src,))
draft = st.session_state['draft']
src = draft.sources[0]
blocks = {block.key:block for block in draft.blocks}
if st.button('Replace selected wording'):
    suggestion = ai.normalize_draft({'paragraphs':[{'text':'Replaced inlet filter and checked the seal.',
        'fact_ids':[src.facts[0].id]}]}, 'activity_summary', src.facts, (src,))
    blocks['activity_summary'] = ai.apply_suggestion(blocks['activity_summary'], suggestion, (src,), append=False)
blocks = ui.edit_linked_paragraphs(draft, blocks, 'linked_integrity', _field)
st.session_state['draft'] = replace(draft, blocks=tuple(blocks.values()))
preserve_report_draft_state()
'''


@pytest.mark.parametrize('manual', [
    '- Replaced inlet filter; a different isolation problem remains open.',
    'First manual line.\n\nSecond manual line.',
    '- Verified independent filter inventory.',
])
def test_linked_manual_text_is_exact_and_reruns_do_not_change_review(manual):
    app = healthy(AppTest.from_string('MANUAL = ' + repr(manual) + '\n' + LINKED).run())
    expected = manual + '\n- Replaced inlet filter'
    assert app.session_state['draft'].blocks[0].text == expected
    widget(app, 'checkbox', 'I checked this wording against the displayed current evidence').check().run()
    healthy(app)
    assert app.session_state['draft'].blocks[0].reviewed
    previous = app.session_state['draft'].blocks[0]
    ids = [item.proto.id for item in app.text_area]
    for _ in range(2):
        healthy(app.run())
        assert app.session_state['draft'].blocks[0] == previous
        assert [item.proto.id for item in app.text_area] == ids


def test_linked_explicit_clear_stays_empty_and_replace_updates_same_fact_editor():
    app = healthy(AppTest.from_string("MANUAL = ''\n" + LINKED).run())
    widget(app, 'text_area', 'Your other notes').set_value('Temporary retained access note.').run()
    healthy(app)
    widget(app, 'text_area', 'Your other notes').set_value('').run()
    healthy(app.run())
    assert widget(app, 'text_area', 'Your other notes').value == ''
    assert 'Temporary retained access note.' not in app.session_state['draft'].blocks[0].text
    widget(app, 'text_area', 'Report paragraph 1').set_value('Replaced inlet filter; earlier editorial wording').run()
    healthy(app.run())
    prior_id = widget(app, 'text_area', 'Report paragraph 1').proto.id
    widget(app, 'button', 'Replace selected wording').click().run()
    healthy(app)
    assert widget(app, 'text_area', 'Report paragraph 1').value == 'Replaced inlet filter and checked the seal.'
    assert widget(app, 'text_area', 'Report paragraph 1').proto.id == prior_id
    assert 'earlier editorial wording' not in app.session_state['draft'].blocks[0].text


def test_linked_same_event_edits_persist_and_reopen_from_saved_revision(monkeypatch, tmp_path):
    from app import monthly_report_library as library
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = healthy(AppTest.from_string("MANUAL = ''\n" + LINKED).run())
    manual = 'Human note one.\n\nHuman note two; completion remains unconfirmed.'
    paragraph = 'Replaced inlet filter and checked the seal.'
    widget(app, 'text_area', 'Your other notes').set_value(manual)
    widget(app, 'text_area', 'Report paragraph 1').set_value(paragraph).run()
    healthy(app.run())
    current = app.session_state['draft']
    assert current.blocks[0].text == manual + '\n- ' + paragraph
    saved = library.save_snapshot(current, expected_revision=0,
                                  entered_editor=current.prepared_by)
    reopened = library.load_snapshot(current.profile.contract, current.profile.key, current.period)
    assert reopened.revision == saved.revision and reopened.draft == current
    resumed = AppTest.from_string("MANUAL = ''\n" + LINKED)
    resumed.session_state['draft'] = reopened.draft
    healthy(resumed.run())
    assert resumed.session_state['draft'] == current
    assert widget(resumed, 'text_area', 'Your other notes').value == manual
    assert widget(resumed, 'text_area', 'Report paragraph 1').value == paragraph


FACTS = CONTEXT + '''
from app.monthly_report_content_policy import page_fingerprint
if 'facts_integrity_evidence' not in st.session_state:
    text = ('Inspected intake screen.', 'Verified alarm relay.', 'Recorded discharge pressure.', 'Adjusted fan controls.')
    src = ReportSource('chunk-source', 'synthetic-multipage.pdf', '5'*64, '.pdf', page_texts=text)
    facts = ai.normalize_facts({'facts':[{'page':n, 'kind':'action', 'text':text[n-1], 'quote':text[n-1]}
                               for n in (1, 4)]}, src, (1, 4), P, M)
    src = replace(src, facts=facts, client_page_reviews=tuple((n, page_fingerprint(src,n)) for n in (1, 4)))
    other = ReportSource('separate-source', 'synthetic-independent.txt', '6'*64, '.txt', page_texts=('Checked roof drain.',))
    other = replace(other, facts=ai.normalize_facts({'facts':[{'page':1, 'kind':'action', 'text':'Checked roof drain.',
          'quote':'Checked roof drain.'}]}, other, (1,), P, M))
    st.session_state['facts_integrity_evidence'] = (SourceContent(src), SourceContent(other))
contents = st.session_state['facts_integrity_evidence']
src = contents[0].source
draft = ReportDraft(P, M, 'Synthetic Reviewer', default_sections(), (), sources=tuple(c.source for c in contents))
if st.button('Accept next source page'):
    proposed = ai.normalize_facts({'facts':[{'page':2, 'kind':'action', 'text':'Verified alarm relay.',
        'quote':'Verified alarm relay.'}]}, src, (2,), P, M)
    st.session_state['facts_integrity_ai_facts'] = (src.id, src.fingerprint, proposed)
    receipt = ui._fact_approval(draft, 'facts_integrity', src, proposed)
    ui._queue_fact_approval('facts_integrity', 'invalid' if STALE else receipt)
ui._apply_pending_fact_approval(draft, 'facts_integrity')
'''


@pytest.mark.parametrize('stale', [False, True])
def test_fact_chunk_acceptance_keeps_other_pages_sources_and_receipt_guards(stale):
    app = healthy(AppTest.from_string('STALE = ' + repr(stale) + '\n' + FACTS).run())
    before = app.session_state['facts_integrity_evidence']
    widget(app, 'button', 'Accept next source page').click().run()
    healthy(app)
    after = app.session_state['facts_integrity_evidence']
    if stale:
        assert after == before
        assert app.warning
    else:
        assert {fact.page for fact in after[0].source.facts} == {1, 2, 4}
        assert after[0].source.client_page_reviews == before[0].source.client_page_reviews
        assert after[1] == before[1]
        widget(app, 'button', 'Accept next source page').click().run()
        healthy(app)
        assert app.session_state['facts_integrity_evidence'] == after


def test_same_page_new_fact_preserves_an_earlier_accepted_fact():
    from app import monthly_report_ai as ai
    from app.monthly_report_model import synthetic_profiles, ReportPeriod
    app = healthy(AppTest.from_string('STALE = False\n' + FACTS).run())
    contents = app.session_state['facts_integrity_evidence']
    src = contents[0].source
    pages = list(src.page_texts)
    pages[1] = 'Verified alarm relay. Replaced indicator lamp.'
    src = replace(src, page_texts=tuple(pages))
    earlier = ai.normalize_facts({'facts':[{'page':2, 'kind':'action',
        'text':'Replaced indicator lamp.', 'quote':'Replaced indicator lamp.'}]},
        src, (2,), synthetic_profiles()[0], ReportPeriod(2026, 9))
    src = replace(src, facts=(*src.facts, *earlier))
    app.session_state['facts_integrity_evidence'] = (replace(contents[0], source=src), contents[1])
    healthy(app.run())
    widget(app, 'button', 'Accept next source page').click().run()
    healthy(app)
    accepted = app.session_state['facts_integrity_evidence'][0].source.facts
    assert set(src.facts) <= set(accepted)
    assert {fact.text for fact in accepted if fact.page == 2} == {
        'Verified alarm relay.', 'Replaced indicator lamp.'}


OCR = FACTS.replace("if st.button('Accept next source page'):", "if False:") + '''
if st.button('Finish page two recognition'):
    future = Future(); future.set_result(OCR_TEXT)
    st.session_state['facts_integrity_ai_job'] = {'kind':'ocr', 'source_id':src.id,
        'source_fingerprint':'invalid' if STALE else src.fingerprint,
        'page':2, 'scope':'synthetic-ocr', 'key':'7'*64, 'future':future}
ui._finish_job(draft, 'facts_integrity')
'''


@pytest.mark.parametrize('stale', [False, True])
def test_ocr_changed_page_keeps_unchanged_page_facts_and_approvals(stale, monkeypatch):
    from app import monthly_report_image_review
    monkeypatch.setattr(monthly_report_image_review, 'complete_review', lambda *a: None)
    app = healthy(AppTest.from_string('STALE = ' + repr(stale) + '\nOCR_TEXT = "Verified alarm relay; reset remains pending."\n' + OCR).run())
    before = app.session_state['facts_integrity_evidence']
    widget(app, 'button', 'Finish page two recognition').click().run()
    healthy(app)
    after = app.session_state['facts_integrity_evidence']
    assert after[1] == before[1]
    if stale:
        assert after == before
        assert app.warning
    else:
        assert after[0].source.facts == before[0].source.facts
        assert after[0].source.client_page_reviews == before[0].source.client_page_reviews
        assert after[0].source.page_texts[1] == 'Verified alarm relay; reset remains pending.'


@pytest.mark.parametrize('changed', [True, False])
def test_ocr_invalidates_only_the_actually_changed_target_page(changed, monkeypatch):
    from app import monthly_report_ai as ai, monthly_report_image_review
    from app.monthly_report_content_policy import page_fingerprint
    from app.monthly_report_model import synthetic_profiles, ReportPeriod
    monkeypatch.setattr(monthly_report_image_review, 'complete_review', lambda *a: None)
    result = 'Verified alarm relay; reset remains pending.' if changed else 'Verified alarm relay.'
    app = healthy(AppTest.from_string('STALE = False\nOCR_TEXT = ' + repr(result) + '\n' + OCR).run())
    contents = app.session_state['facts_integrity_evidence']
    src = contents[0].source
    target_fact = ai.normalize_facts({'facts':[{'page':2, 'kind':'action',
        'text':src.page_texts[1], 'quote':src.page_texts[1]}]}, src, (2,),
        synthetic_profiles()[0], ReportPeriod(2026, 9))
    src = replace(src, facts=(*src.facts, *target_fact),
                  client_page_reviews=(*src.client_page_reviews, (2, page_fingerprint(src, 2))))
    app.session_state['facts_integrity_evidence'] = (replace(contents[0], source=src), contents[1])
    healthy(app.run())
    widget(app, 'button', 'Finish page two recognition').click().run()
    healthy(app)
    revised = app.session_state['facts_integrity_evidence'][0].source
    assert revised.facts == tuple(fact for fact in src.facts if not changed or fact.page != 2)
    assert revised.client_page_reviews == tuple(
        review for review in src.client_page_reviews if not changed or review[0] != 2)
    if not changed:
        assert revised == src
