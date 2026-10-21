"""Synthetic native PDF paragraphs, not a simulated external reader."""
from dataclasses import replace, asdict
from hashlib import sha256
import json
import fitz
import pytest
from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles, ReportSource
from app.monthly_report_structured_uploads import native_update, reader_update


def fixture(monkeypatch, tmp_path, fields=None):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    fields = fields or [
        'Actions: Inspected the QA-\nBATCH-V1 demonstration label on 2026-10-16.',
        'Findings: The fictional label reads AMBER; the fictional\ncomparison label reads BLUE.',
        'Follow-up: PENDING LABEL RECHECK. No\ncompletion date is asserted.',
    ]
    doc = fitz.open(); p = doc.new_page()
    parts = ['Synthetic vendor service report', 'Vendor: Synthetic Vendor',
             'Report date: 2026-10-16', 'Fixture header: Never an activity event.', *fields,
             'Footer: Synthetic test data, not a service event.']
    y = 30
    for part in parts:
        p.insert_text((35,y), part, fontsize=10)
        y += 15 * (len(part.splitlines()) + 1)
    raw = doc.tobytes(); doc.close()
    content, _ = sources.ingest(synthetic_profiles()[0], 'synthetic-service.pdf', raw)
    return content, raw


def test_complete_fields_and_activity_share_native_spans(monkeypatch,tmp_path):
    content, raw = fixture(monkeypatch,tmp_path)
    s = content.source
    assert 'BATCH-V1 demonstration label on 2026-10-16.' in s.actions
    assert 'comparison label reads BLUE.' in s.findings
    assert 'completion date is asserted.' in s.follow_ups
    accepted, pending = sources.action_evidence(s)
    assert accepted == ((s.actions,(1,)),) and not pending
    result = native_update((content,), 'activity_summary')
    assert s.actions in result.text and s.findings in result.text and s.follow_ups in result.text
    assert 'Fixture header' not in result.text and 'Footer:' not in result.text
    assert len(result.text.split('\n\n')) == 3
    assert native_update((content,), 'activity_summary', result) == result
    assert sources.source_bytes(synthetic_profiles()[0],s) == raw
    with fitz.open(stream=raw,filetype='pdf') as pdf:
        assert s.page_texts == tuple(p.get_text().strip() for p in pdf)


@pytest.mark.parametrize('tail', ['did not start.', 'was not completed.', 'awaiting approval.', 'cost $350.00.'])
def test_whole_qualifier_prevents_completed_action(monkeypatch,tmp_path,tail):
    content,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump but it\n'+tail])
    assert not content.source.actions
    assert not sources.action_evidence(content.source)[0]
    if '$' not in tail:
        assert tail in native_update((content,), 'activity_summary').text


def test_unknown_field_boundary_never_enters_action(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump.\nBilling contact: Private Person\nFindings: Observed normal operation.'])
    assert c.source.actions == 'Actions: Inspected the pump.'
    assert 'Private Person' not in native_update((c,), 'activity_summary').text


def test_incomplete_block_remains_pending_not_an_action(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump but it', 'unrelated following paragraph with several words.'])
    assert not c.source.actions
    assert 'unrelated following' not in native_update((c,), 'activity_summary').text
    assert any('review' in n.lower() and 'passage' in n.lower() for n in c.source.notices)


def test_legacy_source_without_block_evidence_is_not_promoted():
    s=ReportSource('id','service.pdf','digest','.pdf',classification='Vendor service',
                   page_texts=('Actions: Inspected the pump but it\ndid not start.',),selected_pages=(1,))
    assert not sources.native_action_lines(s)

@pytest.mark.parametrize('tail', ['at 08:00 with pressure 20 psi.', 'with serial QA-01:02 intact.'])
def test_technical_colons_are_continuations(monkeypatch,tmp_path,tail):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump\n'+tail])
    assert tail in c.source.actions


@pytest.mark.parametrize('change', ['bool','bounds','overlap','digest','changed_text','scalar','badpage'])
def test_bad_offsets_cannot_certify_passage(monkeypatch,tmp_path,change):
    c,_=fixture(monkeypatch,tmp_path)
    spans=list(c.source.pdf_text_blocks)
    if change=='scalar': spans[0]=42
    if change=='badpage': spans[0]=(0,*spans[0][1:])
    if change=='bool': spans[0]=(1,True,spans[0][2],spans[0][3])
    if change=='bounds': spans[0]=(1,0,999999,spans[0][3])
    if change=='overlap': spans.insert(1,spans[0])
    if change=='digest': spans[0]=(*spans[0][:3],'0'*64)
    s=replace(c.source,pdf_text_blocks=tuple(spans))
    if change=='changed_text': s=replace(s,page_texts=(s.page_texts[0].replace('Synthetic','Different',1),))
    assert not sources.native_action_lines(s)
    assert not native_update((replace(c,source=s),),'activity_summary').text


def test_legacy_fingerprints_and_serialization(monkeypatch,tmp_path):
    from app.monthly_report_library import source_from_dict
    c,_=fixture(monkeypatch,tmp_path)
    assert source_from_dict(json.loads(json.dumps(asdict(c.source)))) == c.source
    s=ReportSource('id','old.pdf','digest','.pdf')
    old=asdict(s); old.pop('pdf_text_blocks'); old.pop('scope_review')
    assert s.fingerprint == sha256(json.dumps(old,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    assert source_from_dict(old) == s


def test_cache_upgrade_never_mutates_existing_reviewed_source(monkeypatch,tmp_path):
    c,raw=fixture(monkeypatch,tmp_path)
    profile=synthetic_profiles()[0]
    reviewed=replace(c.source,actions='Human edited action',findings='Human finding')
    path=sources._path(profile,c.source.sha256,'.json')
    cache=json.loads(path.read_text()); cache.pop('vendor_passage_policy')
    cache['source'].pop('pdf_text_blocks'); cache['source']['actions']='Actions: Inspected the QA-'
    path.write_text(json.dumps(cache))
    restored,_=sources.ingest(profile,c.source.filename,raw)
    assert 'BATCH-V1 demonstration label' in restored.source.actions
    assert restored.source.page_texts == c.source.page_texts
    assert reviewed.actions=='Human edited action' and reviewed.findings=='Human finding'
    monkeypatch.setattr(sources.fitz,'open',lambda *a,**k: pytest.fail('new cache reparsed'))
    assert sources.ingest(profile,c.source.filename,raw)[0].source == restored.source


def test_reader_grounding_remains_exact_and_duplicate_safe(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path)
    block=native_update((c,),'activity_summary')
    read,_=reader_update((c,),'activity_summary',{'items':[{'source':c.source.id,'page':1,'text':c.source.actions,'row':[],'include_page':False}]},block)
    assert read.text==block.text
    with pytest.raises(ValueError,match='not present'):
        reader_update((c,),'activity_summary',{'items':[{'source':c.source.id,'page':1,'text':'Actions: Inspected a different pump.','row':[],'include_page':False}]},block)


def test_docx_and_unlabelled_nonvendor_paths_unchanged():
    from app.monthly_report_structured_uploads import _activity_lines
    text='The technician inspected the pump and found it\nlocked out.'
    assert _activity_lines(text,'.pdf') == ('The technician inspected the pump and found it locked out.',)
    s=ReportSource('id','report.docx','digest','.docx',classification='Vendor service',
                  page_texts=('Actions: Inspected the pump.',),selected_pages=(1,))
    assert sources.native_action_lines(s) == (('Actions: Inspected the pump.',(1,)),)


def test_no_cross_page_join(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump but it'])
    s=replace(c.source,page_texts=(*c.source.page_texts,'did not start.'),selected_pages=(1,2))
    assert not sources.native_action_lines(s)


def test_unlabeled_sentence_after_completed_line_is_ambiguous(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump.\nIt was not completed.'])
    assert not c.source.actions
    assert not native_update((c,),'activity_summary').text
    assert any('review' in n.lower() for n in c.source.notices)


def test_inline_fields_are_reviewed_not_blended(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump. Findings: Observed a leak.'])
    assert not c.source.actions
    assert not native_update((c,),'activity_summary').text
    assert any('passage' in n for n in c.source.notices)


@pytest.mark.parametrize('boundary', ['Footer: Do not add this to activity.', 'Confidential information for the service recipient.', 'Page 2 of 3'])
def test_footer_cannot_become_action_tail(monkeypatch,tmp_path,boundary):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump.\n'+boundary])
    assert c.source.actions == 'Actions: Inspected the pump.'
    assert boundary not in native_update((c,),'activity_summary').text


def test_blank_separates_unrelated_paragraph(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump.\n\nUnrelated operational planning note goes here.'])
    assert c.source.actions == 'Actions: Inspected the pump.'
    assert 'Unrelated' not in native_update((c,),'activity_summary').text


def test_block_span_matching_never_searches_ahead():
    from app.monthly_report_vendor_passages import block_spans
    pdf=fitz.open(); page=pdf.new_page(); page.insert_text((35,50),'Actions: Inspected.')
    assert not block_spans(page,'Unrelated\nActions: Inspected.',1)
    spans=block_spans(page,'Actions: Inspected.',1)
    assert spans == ((1,0,19,sha256(b'Actions: Inspected.').hexdigest()),)


def test_legacy_draft_fingerprint_and_saved_source_stay_unchanged(monkeypatch,tmp_path):
    from app.monthly_report_model import synthetic_draft
    from app.monthly_report_library import save_snapshot, load_snapshot
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    s=ReportSource('id','old.pdf','digest','.pdf',actions='Reviewed human action')
    from app.monthly_report_model import ReportPeriod
    draft=replace(synthetic_draft(synthetic_profiles()[0],ReportPeriod(2026,10)),sources=(s,))
    old=asdict(draft)
    for source in old['sources']:
        source.pop('pdf_text_blocks'); source.pop('scope_review')
    assert draft.fingerprint == sha256(json.dumps(old,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    saved=save_snapshot(draft,expected_revision=0,entered_editor=draft.prepared_by)
    before=load_snapshot(draft.profile.contract,draft.profile.key,draft.period)
    # Ingest is separate from the saved report/draft; no migration writes it.
    fixture(monkeypatch,tmp_path)
    after=load_snapshot(draft.profile.contract,draft.profile.key,draft.period)
    assert before == after and after.draft.sources == (s,)


def test_side_by_side_columns_are_not_one_complete_passage(monkeypatch,tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    pdf=fitz.open(); p=pdf.new_page()
    p.insert_text((35,30),'Vendor service report')
    p.insert_text((35,60),'Actions: Inspected the pump but it',fontsize=10)
    p.insert_text((350,60),'Other column unrelated text.',fontsize=10)
    c,_=sources.ingest(synthetic_profiles()[0],'columns.pdf',pdf.tobytes())
    assert not c.source.actions
    assert not native_update((c,),'activity_summary').text
    assert any('passage' in n for n in c.source.notices)


def test_repeated_identical_labels_keep_exact_offsets(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump.', 'Actions: Inspected the pump.'])
    from app.monthly_report_vendor_passages import vendor_passages
    passages,pending=vendor_passages(c.source,1)
    assert len(passages)==2 and not pending
    assert passages[0].end < passages[1].start
    assert c.source.page_texts[0][passages[0].start:passages[0].end] == passages[0].text
    assert c.source.page_texts[0][passages[1].start:passages[1].end] == passages[1].text


def test_long_label_is_not_silently_cut_into_a_completed_action():
    text='Vendor service report\nActions: Inspected '+('technical equipment ' * 350)+'.'
    s=ReportSource('id','service-report.pdf','digest','.pdf',page_texts=(text,),selected_pages=(1,),
                   pdf_text_blocks=((1,0,len(text),sha256(text.encode()).hexdigest()),))
    s=sources.suggest_facts(s,synthetic_profiles()[0])
    assert not s.actions
    assert any('exceeds the suggestion limit' in n for n in s.notices)
    assert s.page_texts==(text,)
