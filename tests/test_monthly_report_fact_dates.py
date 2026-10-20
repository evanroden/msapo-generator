"""Actual G4-ai-10 date grounding, separate from the misnamed old redraft probe.

Real synthetic PDF text enters through the product importer. Reader results
are controlled local values; no external model or paid reading is performed.
"""
from concurrent.futures import Future
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

from docx import Document
import fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_ai as ai
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import BlockSpec, ReportDraft, ReportPeriod, SectionSpec, synthetic_profiles
from conftest import requires_libreoffice


PERIOD = ReportPeriod(2026, 9)
FACT_TEXT = 'Inspected expansion tank ET-51.'
QUOTE = 'Inspected expansion tank ET-51'
DATE_FLAG = 'Date was not verified on the cited page'


def source_document(monkeypatch, tmp_path, *page_dates):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    with fitz.open() as pdf:
        for event_date in page_dates:
            page = pdf.new_page(width=720, height=400)
            page.insert_textbox(fitz.Rect(30, 30, 690, 350), QUOTE + ' on ' + event_date + '.', fontsize=12)
        raw = pdf.tobytes()
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, 'synthetic-dated-service.pdf', raw)
    assert sources.source_bytes(profile, content.source) == raw
    assert content.source.sha256 == sha256(raw).hexdigest()
    return profile, content, raw


def normalize(profile, content, proposed='2026-09-17', *, page=1):
    return ai.normalize_facts({'facts': [{'page': page, 'kind': 'action',
        'text': FACT_TEXT, 'quote': QUOTE, 'date': proposed}]}, content.source,
        tuple(range(1, len(content.source.page_texts) + 1)), profile, PERIOD)[0]


@pytest.mark.parametrize('shown,proposed', [
    ('September 17, 2026', '2026-09-01'),
    ('September 17, 2025', '2026-09-17'),
    ('September 17', '2026-09-17'),
    ('09/17/20260', '2026-09-17'),
    ('109/17/2026', '2026-09-17'),
    ('2026-09-170', '2026-09-17'),
    ('September 17, 20260', '2026-09-17'),
])
def test_day_prefix_contradictory_year_missing_year_and_partial_tokens_are_unverified(
        monkeypatch, tmp_path, shown, proposed):
    profile, content, _ = source_document(monkeypatch, tmp_path, shown)
    fact = normalize(profile, content, proposed)
    assert fact.date == ''
    assert DATE_FLAG in fact.flags
    assert fact.text == FACT_TEXT and fact.quote == QUOTE
    assert fact.source_id == content.source.id and fact.page == 1


@pytest.mark.parametrize('shown', [
    'September 17, 2026', 'Sep 17, 2026', 'September 17 2026',
    '09/17/2026', '9/17/2026', '2026-09-17',
    '2026-09-17T08:30:00Z',
])
def test_complete_calendar_date_forms_keep_the_exact_supported_date(monkeypatch, tmp_path, shown):
    profile, content, _ = source_document(monkeypatch, tmp_path, shown)
    fact = normalize(profile, content)
    assert fact.date == '2026-09-17' and not fact.flags


def test_date_on_a_different_page_or_only_in_source_metadata_is_not_cited_evidence(monkeypatch, tmp_path):
    profile, content, _ = source_document(monkeypatch, tmp_path, 'September 18, 2026', 'September 17, 2026')
    content = replace(content, source=replace(content.source, service_date='2026-09-17'))
    first, second = normalize(profile, content, page=1), normalize(profile, content, page=2)
    assert first.date == '' and DATE_FLAG in first.flags
    assert second.date == '2026-09-17' and not second.flags


def test_known_prior_period_date_stays_known_and_unknown_date_stays_unknown(monkeypatch, tmp_path):
    profile, content, _ = source_document(monkeypatch, tmp_path, 'August 17, 2026')
    prior = normalize(profile, content, '2026-08-17')
    assert prior.date == '2026-08-17'
    assert prior.flags == ('Outside the reporting month',)
    unknown = normalize(profile, content, '')
    assert unknown.date == '' and not unknown.flags


SCRIPT = '''
import streamlit as st
from app.monthly_report_ai_ui import render_drafting
from app.monthly_report_ui import _field
draft = st.session_state['date_draft']
draft, blocks = render_drafting(draft, {block.key:block for block in draft.blocks},
    'date_proof', _field, allowed_keys={'activity_summary'})
st.session_state['date_draft'] = draft
'''


@pytest.mark.parametrize('shown,expected', [('September 17', ''), ('September 17, 2026', '2026-09-17')])
def test_visible_fact_review_and_saved_evidence_keep_verified_date_state(monkeypatch, tmp_path, shown, expected):
    from app import monthly_report_ai_ui as ui
    profile, content, _ = source_document(monkeypatch, tmp_path, shown)
    section = SectionSpec('activity', '2', 'Monthly Activity Summary', (BlockSpec('activity_summary', 'rich_text'),))
    draft = ReportDraft(profile, PERIOD, 'Synthetic Reviewer', (section,), (), sources=(content.source,))
    requests, reservations = [], []
    monkeypatch.setattr(ai, 'cached', lambda *args, **kwargs: None)
    monkeypatch.setattr(ai, 'reserve_call', lambda *args: reservations.append(args))
    def controlled_reader(prepare, read):
        requests.append(prepare())
        future = Future()
        future.set_result({'facts': [{'page': 1, 'kind': 'action', 'text': FACT_TEXT,
            'quote': QUOTE, 'date': '2026-09-17'}]})
        return future
    monkeypatch.setattr(ui, 'start_receipt', controlled_reader)
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state['date_draft'] = draft
    app.session_state['date_proof_evidence'] = (content,)
    app.run()
    assert not app.exception and not requests and not reservations
    next(button for button in app.button if button.label == 'Find work, findings and follow-ups').click().run()
    assert not app.exception and len(requests) == len(reservations) == 1
    assert any(DATE_FLAG in message.value for message in app.warning) == (not expected)
    next(button for button in app.button if button.label == 'Use these facts').click().run()
    assert not app.exception
    accepted = app.session_state['date_draft']
    assert accepted.sources[0].facts[0].date == expected
    assert (DATE_FLAG in accepted.sources[0].facts[0].flags) == (not expected)
    saved = library.save_snapshot(accepted, expected_revision=0, entered_editor=accepted.prepared_by)
    restored = library.load_snapshot(profile.contract, profile.key, PERIOD)
    assert restored.revision == saved.revision and restored.draft.sources == accepted.sources
    _, payload, facts = ai.drafting_request('activity_summary', restored.draft.sources, PERIOD)
    sent = json.loads(payload[0]['text'].split('\n')[-1])
    assert sent['facts'][0]['date'] == expected and facts[0].date == expected
    assert (DATE_FLAG in sent['facts'][0]['flags']) == (not expected)


@requires_libreoffice
def test_supported_fact_date_reaches_actual_saved_word_and_pdf_once(monkeypatch, tmp_path):
    from app.monthly_report_docx import generate_report
    from app.monthly_report_source_details import correct_source_details
    profile, content, raw = source_document(monkeypatch, tmp_path, 'September 17, 2026')
    reviewed = correct_source_details(content.source, profile, None, profile.facilities[0].key)
    full = QUOTE + ' on September 17, 2026.'
    fact = ai.normalize_facts({'facts': [{'page': 1, 'kind': 'action', 'text': FACT_TEXT,
        'quote': full, 'date': '2026-09-17'}]}, reviewed, (1,), profile, PERIOD)[0]
    assert fact.date == '2026-09-17' and not fact.flags
    # Facts are part of the scope-bound source revision. The initial before
    # output run stopped at a stale site receipt after appending this fact;
    # establish this synthetic fixture's exact site on the final source so the
    # date/output assertion is actually reachable. No scope rule is bypassed.
    source = correct_source_details(replace(reviewed, facts=(fact,)),
        profile, None, profile.facilities[0].key)
    from app.monthly_report_source_scope import reviewed_scope
    assert reviewed_scope(source, profile) is not None
    block = ai.normalize_draft({'paragraphs': [{'text': full, 'fact_ids': [fact.id]}]},
        'activity_summary', (fact,), (source,))
    block = ai.reviewed_block(block, (source,))
    section = SectionSpec('activity', '2', 'Monthly Activity Summary', (BlockSpec('activity_summary', 'rich_text'),))
    draft = ReportDraft(profile, PERIOD, 'Synthetic Reviewer', (section,), (block,), sources=(source,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    restored = library.load_snapshot(profile.contract, profile.key, PERIOD)
    assert restored.draft == draft and restored.revision == saved.revision
    package = generate_report(restored.draft, acknowledged_fingerprint=restored.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    output = Path(os.environ.get('INDEPENDENT_OUTPUT', str(tmp_path))) / 'fact-dates'
    output.mkdir(exist_ok=True, parents=True)
    (output / 'verified_fact_date.docx').write_bytes(package.docx)
    (output / 'verified_fact_date.pdf').write_bytes(package.pdf)
    word_text = '\n'.join(paragraph.text for paragraph in Document(BytesIO(package.docx)).paragraphs)
    assert word_text.count(full) == 1
    with fitz.open(stream=package.pdf, filetype='pdf') as pdf:
        pdf_text = ' '.join(' '.join(page.get_text().split()) for page in pdf)
        for index, page in enumerate(pdf, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output / f'verified_fact_date_page_{index}.png')
        assert pdf_text.count(full) == 1
    (output / 'verified_fact_date.json').write_text(json.dumps({
        'tested_revision': os.environ.get('MSAPO_SHA', 'unrecorded'),
        'source_sha256': sha256(raw).hexdigest(), 'fact_date': fact.date,
        'saved_revision': saved.revision, 'draft_fingerprint': restored.draft.fingerprint,
        'docx_bytes': len(package.docx), 'docx_sha256': sha256(package.docx).hexdigest(),
        'pdf_bytes': len(package.pdf), 'pdf_sha256': sha256(package.pdf).hexdigest(),
    }, indent=2) + '\n')
