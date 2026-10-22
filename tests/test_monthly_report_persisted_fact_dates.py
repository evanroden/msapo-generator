"""Additional G4 date coverage for a synthetic persisted pre-fix fact record.

The old date/review receipt is an explicit legacy fixture, not a newly accepted
reader result. Original bytes and saved evidence must remain intact while their
later consumption refuses an unverified date.
"""
from concurrent.futures import Future
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path

import fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_ai as ai
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_checks import preflight
from app.monthly_report_model import (
    BlockSpec, DraftParagraph, EvidenceFact, ReportDraft, ReportPeriod,
    ResolvedBlock, SectionSpec, synthetic_profiles,
)
from conftest import requires_libreoffice


def persisted_legacy(monkeypatch, tmp_path):
    from app.monthly_report_source_details import correct_source_details
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    quote = 'Inspected 1 expansion tank ET-51 on September 17, 2026.'
    with fitz.open() as pdf:
        page = pdf.new_page(width=720, height=400)
        page.insert_text((30, 40), quote)
        raw = pdf.tobytes()
    content, _ = sources.ingest(profile, 'synthetic-legacy-date.pdf', raw)
    source = correct_source_details(content.source, profile, None, profile.facilities[0].key)
    words = 'Inspected 1 expansion tank ET-51.'
    # Match the pre-fix deterministic fact identity; date was not an identity
    # field, so a deliberate re-read can repair this same accepted fact.
    identity = 'fact-' + ai.digest((source.sha256, 1, 'action', words, quote))[:20]
    fact = EvidenceFact(identity, source.id, 1, 'action', words, quote, date='2026-09-01')
    # The earlier output attempt hit a stale site-scope prerequisite because
    # facts change the source revision. Bind the explicit synthetic site to
    # this final legacy record before constructing its cited paragraph.
    source = correct_source_details(replace(source, facts=(fact,)),
        profile, None, profile.facilities[0].key)
    from app.monthly_report_source_scope import reviewed_scope
    assert reviewed_scope(source, profile) is not None
    reference = sources.source_reference(source, 1)
    old_words = 'Inspected 1 expansion tank ET-51 on September 1, 2026.'
    block = ResolvedBlock('activity_summary', 'This month', text='- ' + old_words,
        references=(reference,), ai_written=True,
        ai_paragraphs=(DraftParagraph(old_words, (fact.id,), (reference,)),),
        ai_evidence_fingerprint=ai.evidence_fingerprint((source,), (reference,)))
    block = replace(block, reviewed_fingerprint=block.fingerprint)
    section = SectionSpec('activity', '2', 'Monthly Activity Summary', (BlockSpec('activity_summary', 'rich_text'),))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Legacy Reviewer',
                        (section,), (block,), sources=(source,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    assert saved.revision == 1
    restored = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert restored.draft == draft and restored.draft.sources[0].facts[0].date == '2026-09-01'
    return restored.draft, raw, saved.revision


@pytest.mark.parametrize('consume', ['drafting request', 'review', 'refresh evidence'])
def test_saved_unverified_date_requires_explicit_source_recheck_at_consumption(monkeypatch, tmp_path, consume):
    draft, raw, revision = persisted_legacy(monkeypatch, tmp_path)
    source, block = draft.sources[0], draft.blocks[0]
    with pytest.raises(ValueError, match='synthetic-legacy-date.pdf.*page 1.*date'):
        if consume == 'drafting request':
            ai.drafting_request(block.key, draft.sources, draft.period)
        elif consume == 'review':
            ai.reviewed_block(block, draft.sources)
        else:
            ai.refresh_evidence(block, draft.sources)
    latest = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert latest.revision == revision and latest.draft == draft
    assert sources.source_bytes(draft.profile, source) == raw


@requires_libreoffice
def test_final_output_blocks_the_cited_saved_unverified_date_before_assembly(monkeypatch, tmp_path):
    from app.monthly_report_docx import generate_report
    draft, raw, revision = persisted_legacy(monkeypatch, tmp_path)
    checks = [check for check in preflight(draft) if check.code == 'ai_date' and check.blocking]
    output = Path(os.environ.get('INDEPENDENT_OUTPUT', str(tmp_path))) / 'persisted-fact-dates'
    output.mkdir(exist_ok=True, parents=True)
    if not checks:
        # Retain actual wrong output from the failing-before tree, before the
        # desired assertion fails. This contains synthetic data only.
        package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
        assert package.docx and package.pdf, package.pdf_error
        (output / 'legacy_unverified_date_before.docx').write_bytes(package.docx)
        (output / 'legacy_unverified_date_before.pdf').write_bytes(package.pdf)
        (output / 'legacy_unverified_date_before.json').write_text(json.dumps({
            'source_sha256': sha256(raw).hexdigest(), 'source_date': 'September 17, 2026',
            'unsupported_saved_date': '2026-09-01',
            'tested_revision': os.environ.get('MSAPO_SHA', 'unrecorded'),
            'docx_sha256': sha256(package.docx).hexdigest(),
            'pdf_sha256': sha256(package.pdf).hexdigest(),
        }, indent=2) + '\n')
    assert checks and all(check.block_key == 'activity_summary' for check in checks)
    assert 'synthetic-legacy-date.pdf' in checks[0].message and 'page 1' in checks[0].message
    with pytest.raises(ValueError):
        generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
    latest = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert latest.draft == draft and latest.revision == revision


def test_an_uncited_legacy_fact_cannot_block_a_supported_paragraph(monkeypatch, tmp_path):
    draft, _, _ = persisted_legacy(monkeypatch, tmp_path)
    old = draft.sources[0]
    supported = replace(old.facts[0], id='supported-date-fact', date='2026-09-17')
    source = replace(old, facts=(*old.facts, supported))
    block = ai.normalize_draft({'paragraphs': [{'text': supported.quote, 'fact_ids': [supported.id]}]},
                              'activity_summary', (supported,), (source,))
    reviewed = ai.reviewed_block(block, (source,))
    assert reviewed.reviewed
    current = replace(draft, sources=(source,), blocks=(reviewed,))
    assert not any(check.code == 'ai_date' for check in preflight(current))
    refreshed = ai.refresh_evidence(reviewed, (source,))
    assert not refreshed.reviewed and refreshed.ai_paragraphs[0].fact_ids == (supported.id,)


def test_saved_date_warning_has_a_deliberate_fact_and_wording_recovery(monkeypatch, tmp_path):
    """AppTest controls plus real versioned save; browser timing is separate."""
    from app import monthly_report_ai_ui as ui
    draft, raw, revision = persisted_legacy(monkeypatch, tmp_path)
    old_source, old_block = draft.sources[0], draft.blocks[0]
    fact = old_source.facts[0]
    requests, reservations = [], []
    monkeypatch.setattr(ai, 'cached', lambda *args, **kwargs: None)
    monkeypatch.setattr(ai, 'reserve_call', lambda *args: reservations.append(args))

    def controlled_reader(prepare, read):
        payload = prepare()
        requests.append(payload)
        future = Future()
        if payload[0]['text'].startswith(ai.DRAFT_PROMPT):
            future.set_result({'paragraphs': [{'text': old_block.ai_paragraphs[0].text,
                                              'fact_ids': [fact.id]}]})
        else:
            future.set_result({'facts': [{'page': 1, 'kind': 'action',
                'text': fact.text, 'quote': fact.quote, 'date': '2026-09-17'}]})
        return future

    monkeypatch.setattr(ui, 'start_receipt', controlled_reader)
    script = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_ai_ui import render_drafting
from app.monthly_report_ui import _field
draft = st.session_state['legacy_date_draft']
draft, blocks = render_drafting(draft, {block.key: block for block in draft.blocks},
    'legacy_date', _field, allowed_keys={'activity_summary'})
st.session_state['legacy_date_draft'] = replace(draft, blocks=tuple(blocks.values()))
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state['legacy_date_draft'] = draft
    app.session_state['legacy_date_evidence'] = (sources.SourceContent(old_source),)
    app.run()
    assert not app.exception
    next(button for button in app.button if button.label == 'Suggest wording / redraft').click().run()
    assert not app.exception and not requests and not reservations
    assert any('synthetic-legacy-date.pdf' in warning.value and 'page 1' in warning.value
               and 'date' in warning.value for warning in app.warning)
    assert app.session_state['legacy_date_draft'].sources == draft.sources
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft == draft

    next(button for button in app.button if button.label == 'Find work, findings and follow-ups').click().run()
    assert not app.exception and len(requests) == len(reservations) == 1
    assert app.session_state['legacy_date_draft'].sources[0].facts == (fact,)
    next(button for button in app.button if button.label == 'Use these facts').click().run()
    assert not app.exception
    accepted = app.session_state['legacy_date_draft']
    assert accepted.sources[0].facts[0].id == fact.id
    assert accepted.sources[0].facts[0].date == '2026-09-17'
    assert not accepted.blocks[0].reviewed
    assert accepted.blocks[0].ai_paragraphs[0].text == old_block.ai_paragraphs[0].text

    next(area for area in app.text_area if area.label == 'Report paragraph 1').set_value(fact.quote).run()
    next(box for box in app.checkbox if box.label == 'I checked this wording against the displayed current evidence').check().run()
    assert not app.exception
    repaired = app.session_state['legacy_date_draft']
    assert repaired.blocks[0].reviewed and repaired.blocks[0].ai_paragraphs[0].text == fact.quote
    assert not any(check.code in {'ai_date', 'ai_evidence', 'ai_number'} for check in preflight(repaired))
    before_save = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert before_save.revision == revision and before_save.draft == draft
    saved = library.save_snapshot(repaired, expected_revision=revision, entered_editor=repaired.prepared_by)
    latest = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert latest.revision == saved.revision == revision + 1 and latest.draft == repaired
    assert sources.source_bytes(draft.profile, old_source) == raw
