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
    parts = ['Vendor service report', 'Report ID: SYN-123',
             'Report date: 2026-10-16', 'Header: Page 1', *fields,
             'Footer: Page 1']
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
    assert not c.source.actions  # Unsupported contact prose stays pending, never inferred away.
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
    if change=='changed_text': s=replace(s,page_texts=(s.page_texts[0].replace('Inspected','Not done!',1),))
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
    assert c.source.actions == ('Actions: Inspected the pump.' if boundary.startswith('Page ') else '')
    assert boundary not in native_update((c,),'activity_summary').text


def test_blank_separates_unrelated_paragraph(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump.\n\nUnrelated operational planning note goes here.'])
    assert not c.source.actions  # Unknown remainder is not inferred unrelated.
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


def test_ambiguous_vendor_classification_never_escapes_full_qualifier(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Quotation reference only.', 'Actions: Replaced the pump but it\nwas not completed.'])
    assert c.source.classification == 'Reference only'
    assert not c.source.actions
    assert not sources.action_evidence(c.source)[0]
    assert not native_update((c,),'activity_summary').text
    assert any('review' in n.lower() for n in c.source.notices)


def test_reclassification_cannot_restore_physical_line_certification(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump\nand confirmed normal operation.'])
    s=replace(c.source,classification='Reference only',actions='Actions: Inspected the pump')
    assert not sources.native_action_lines(s)
    assert sources.action_evidence(s) == ((), ('Actions: Inspected the pump',))
    assert not native_update((replace(c,source=s),),'activity_summary').text


def test_unlabeled_other_source_types_keep_existing_behavior():
    s=ReportSource('id','water.pdf','digest','.pdf',classification='Water treatment',
        page_texts=('Inspected the sample pump.',),selected_pages=(1,))
    assert sources.native_action_lines(s)==(('Inspected the sample pump.',(1,)),)


def test_version_one_cache_rechecks_ambiguous_classification(monkeypatch,tmp_path):
    c,raw=fixture(monkeypatch,tmp_path,['Quotation reference only.', 'Actions: Replaced the pump but it\nwas not completed.'])
    path=sources._path(synthetic_profiles()[0],c.source.sha256,'.json')
    data=json.loads(path.read_text()); data['vendor_passage_policy']=1
    data['source']['actions']='Actions: Replaced the pump but it'
    path.write_text(json.dumps(data))
    upgraded,_=sources.ingest(synthetic_profiles()[0],c.source.filename,raw)
    assert not upgraded.source.actions
    assert upgraded.source.classification=='Reference only'
    assert any('not auto-imported' in n for n in upgraded.source.notices)
    assert json.loads(path.read_text())['vendor_passage_policy']==7


@pytest.mark.parametrize('heading', ["Technician's note", 'Technician’s note', 'Phase 2 result', 'Note (internal)', 'Note #2'])
def test_punctuated_unknown_heading_does_not_complete_action(monkeypatch,tmp_path,heading):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump\n'+heading+': Access approved.'])
    assert not c.source.actions
    assert not native_update((c,),'activity_summary').text
    assert any('review' in n.lower() for n in c.source.notices)


def test_labeled_page_preserves_unlabeled_page_findings(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path)
    source=replace(c.source,page_texts=(*c.source.page_texts,'Observed leakage at the seal.\nFollow-up scheduled for tomorrow.'),selected_pages=(1,2))
    result=sources.suggest_facts(source,synthetic_profiles()[0])
    assert 'Observed leakage at the seal.' in result.findings
    assert 'Follow-up scheduled for tomorrow.' in result.follow_ups
    assert 'comparison label reads BLUE.' in result.findings


def test_span_validation_is_linear_per_suggestion_request(monkeypatch):
    from app import monthly_report_vendor_passages as passages
    text='Vendor service report\nActions: Inspected the pump.'
    digest=sha256(text.encode()).hexdigest()
    s=ReportSource('id','service.pdf','digest','.pdf',page_texts=(text,)*100,selected_pages=tuple(range(1,101)),
        pdf_text_blocks=tuple((n,0,len(text),digest) for n in range(1,101)))
    visits=[]
    class CountedSpans(tuple):
        def __iter__(self):
            for item in super().__iter__():
                visits.append(1)
                yield item
    s=replace(s,pdf_text_blocks=CountedSpans(s.pdf_text_blocks))
    original=passages.sha256; calls=[]
    def counted(value):
        calls.append(1); return original(value)
    monkeypatch.setattr(passages,'sha256',counted)
    result=sources.suggest_facts(s,synthetic_profiles()[0])
    assert result.actions == 'Actions: Inspected the pump.'
    assert len(calls)<=100
    assert len(visits)<=100


def test_request_local_index_is_not_reused_after_source_change(monkeypatch,tmp_path):
    from app.monthly_report_vendor_passages import read_vendor_document
    c,_=fixture(monkeypatch,tmp_path)
    first=read_vendor_document(c.source)
    assert first[1][0] and not first[1][1]
    changed=replace(c.source,page_texts=(c.source.page_texts[0].replace('Inspected','Not done'),))
    second=read_vendor_document(changed)
    assert not second[1][0] and second[1][1]
    assert read_vendor_document(c.source)==first


def test_version_two_cache_rechecks_unknown_heading_boundary(monkeypatch,tmp_path):
    c,raw=fixture(monkeypatch,tmp_path,["Actions: Inspected the pump\nTechnician's note: Access approved."])
    path=sources._path(synthetic_profiles()[0],c.source.sha256,'.json')
    data=json.loads(path.read_text()); data['vendor_passage_policy']=2
    data['source']['actions']="Actions: Inspected the pump Technician's note: Access approved."
    path.write_text(json.dumps(data))
    upgraded,_=sources.ingest(synthetic_profiles()[0],c.source.filename,raw)
    assert not upgraded.source.actions
    assert json.loads(path.read_text())['vendor_passage_policy']==7


@pytest.mark.parametrize('heading', ['Supervisor ID:42.', 'Finding #2:12.'])
def test_two_digit_heading_value_is_not_mistaken_for_time(monkeypatch,tmp_path,heading):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump\n'+heading])
    assert not c.source.actions
    assert not native_update((c,),'activity_summary').text
    assert any('review' in n.lower() for n in c.source.notices)


def test_negative_status_field_cannot_be_dropped_from_activity(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Replaced the pump.\nStatus: Not completed.'])
    assert not c.source.actions
    assert not sources.action_evidence(c.source)[0]
    assert not native_update((c,),'activity_summary').text
    assert any('review' in n.lower() for n in c.source.notices)


def test_span_metadata_omits_unrelated_blocks(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path)
    assert len(c.source.pdf_text_blocks)==3
    assert all(c.source.page_texts[n-1][start:end].startswith(('Actions:','Findings:','Follow-up:'))
               for n,start,end,digest in c.source.pdf_text_blocks)


@pytest.mark.parametrize('status', ['Status: Not completed.', 'Completion status: Pending.', 'Work status: Not started.'])
def test_separate_status_block_cannot_lose_action_qualification(monkeypatch,tmp_path,status):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Replaced the pump.',status])
    assert not c.source.actions and not native_update((c,),'activity_summary').text
    assert status in c.source.page_texts[0]


def test_span_budget_failure_retains_original_and_requires_review(monkeypatch,tmp_path):
    from app import monthly_report_vendor_passages as passages
    monkeypatch.setattr(passages,'MAX_VENDOR_BLOCK_SPANS',2)
    c,raw=fixture(monkeypatch,tmp_path)
    assert not c.source.pdf_text_blocks
    assert not c.source.actions and not native_update((c,),'activity_summary').text
    assert sources.source_bytes(synthetic_profiles()[0],c.source)==raw
    assert 'completion date is asserted.' in c.source.page_texts[0]
    assert any('review' in n.lower() for n in c.source.notices)


def test_only_exact_passage_notice_uses_current_page_review(monkeypatch,tmp_path):
    from app.monthly_report_source_readiness import unresolved_reading_notices
    from app.monthly_report_content_policy import page_fingerprint
    c,_=fixture(monkeypatch,tmp_path,['Actions: Replaced the pump.\nStatus: Not completed.'])
    s=c.source
    assert unresolved_reading_notices(s)
    reviewed=replace(s,client_page_reviews=((1,page_fingerprint(s,1)),))
    assert not unresolved_reading_notices(reviewed)
    assert not reviewed.actions and not native_update((replace(c,source=reviewed),),'activity_summary').text
    assert reviewed.notices==s.notices and 'not auto-imported' in reviewed.notices[0]
    for changed in (replace(reviewed,sha256='other-source'),replace(reviewed,captions=((1,'Changed caption'),)),
                    replace(reviewed,page_texts=(s.page_texts[0]+' Changed.',))):
        assert unresolved_reading_notices(changed)
    assert unresolved_reading_notices(replace(s,classification='Vendor service'))
    assert unresolved_reading_notices(replace(s,actions='Human edited facts'))
    assert unresolved_reading_notices(replace(reviewed,notices=(*s.notices,'Unknown native content needs review.')))==('Unknown native content needs review.',)


def test_exclusion_requires_exact_explicit_receipt(monkeypatch,tmp_path):
    from app.monthly_report_source_readiness import unresolved_reading_notices
    from app.monthly_report_content_policy import page_fingerprint
    c,_=fixture(monkeypatch,tmp_path,['Actions: Inspected the pump but it'])
    s=replace(c.source,selected_pages=())
    assert unresolved_reading_notices(s)
    excluded=replace(s,client_page_exclusions=((1,page_fingerprint(s,1)),))
    assert not unresolved_reading_notices(excluded)
    assert unresolved_reading_notices(replace(excluded,selected_pages=(1,)))


def test_mixed_page_notices_need_their_own_receipts(monkeypatch,tmp_path):
    from app.monthly_report_source_readiness import unresolved_reading_notices
    from app.monthly_report_content_policy import page_fingerprint
    from app.monthly_report_vendor_passages import passage_notice
    c,_=fixture(monkeypatch,tmp_path)
    s=replace(c.source,page_texts=(c.source.page_texts[0],c.source.page_texts[0]),selected_pages=(1,2),
        notices=(passage_notice(1),passage_notice(2)))
    reviewed=replace(s,client_page_reviews=((1,page_fingerprint(s,1)),))
    assert unresolved_reading_notices(reviewed)==(passage_notice(2),)
    wrong_page=replace(reviewed,client_page_reviews=((1,page_fingerprint(s,1)),(2,page_fingerprint(s,1))))
    assert unresolved_reading_notices(wrong_page)==(passage_notice(2),)
    all_reviewed=replace(reviewed,client_page_reviews=((1,page_fingerprint(s,1)),(2,page_fingerprint(s,2))))
    assert not unresolved_reading_notices(all_reviewed)
    for invalid in (passage_notice(3),passage_notice(1)+' Extra unknown warning.'):
        assert unresolved_reading_notices(replace(all_reviewed,notices=(invalid,)))==(invalid,)


def test_water_labeled_negative_qualifier_never_certifies_first_line(monkeypatch,tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    doc=fitz.open(); p=doc.new_page()
    p.insert_text((35,35),'Water treatment\nActions: Replaced the pump but it\nwas not completed.',fontsize=10)
    raw=doc.tobytes(); doc.close()
    c,_=sources.ingest(synthetic_profiles()[0],'synthetic-water.pdf',raw)
    assert c.source.classification=='Water treatment'
    assert not c.source.actions and not sources.native_action_lines(c.source)
    assert not sources.action_evidence(c.source)[0]
    assert not native_update((c,),'activity_summary').text


@pytest.mark.parametrize('field',['  Actions: Inspected the sample pump.', 'Actions: Inspected the sample pump.  '])
def test_native_block_edge_whitespace_keeps_exact_span(monkeypatch,tmp_path,field):
    c,_=fixture(monkeypatch,tmp_path,[field])
    assert c.source.actions=='Actions: Inspected the sample pump.'
    assert sources.action_evidence(c.source)[0]==((c.source.actions,(1,)),)


@pytest.mark.parametrize('prefix,suffix',[('Actions: hidden ',''),('',' hidden')])
def test_span_whitespace_rule_rejects_nonwhitespace_edges(prefix,suffix):
    from app.monthly_report_vendor_passages import validated_block_index
    value='Actions: Inspected the sample pump.'
    text=prefix+value+suffix
    s=ReportSource('id','test.pdf','digest','.pdf',classification='Vendor service',page_texts=(text,),
        selected_pages=(1,),pdf_text_blocks=((1,len(prefix),len(prefix)+len(value),sha256(value.encode()).hexdigest()),))
    assert validated_block_index(s) is None
    assert not sources.native_action_lines(s)


@pytest.mark.parametrize('same_block',[True,False])
def test_ignored_negative_note_cannot_certify_completed_action(monkeypatch,tmp_path,same_block):
    fields=['Actions: Replaced the pump.', "Technician's note: Repair was not completed."]
    c,_=fixture(monkeypatch,tmp_path,['\n'.join(fields)] if same_block else fields)
    assert not c.source.actions and not sources.action_evidence(c.source)[0]
    assert not native_update((c,),'activity_summary').text


@pytest.mark.parametrize('label', ['Actions: Inspected', 'Findings: Observed', 'Follow-up: Recommended'])
def test_aggregate_oversized_field_never_enters_native_activity(label):
    values=tuple('Vendor service report\n'+label+' '+('sample pump ' * 50)+'.' for _ in range(12))
    spans=tuple((n,0,len(v),sha256(v.encode()).hexdigest()) for n,v in enumerate(values,1))
    s=ReportSource('id','synthetic-service.pdf','digest','.pdf',classification='Vendor service',
                  page_texts=values,selected_pages=tuple(range(1,13)),pdf_text_blocks=spans)
    s=sources.suggest_facts(s,synthetic_profiles()[0])
    assert s.classification=='Vendor service'
    assert not s.actions and not s.findings and not s.follow_ups
    assert len(s.notices)==12 and all('exceeds the suggestion limit' in n for n in s.notices)
    assert not sources.native_action_lines(s)
    from app.monthly_report_sources import SourceContent
    assert not native_update((SourceContent(s),),'activity_summary').text


@pytest.mark.parametrize('note', ["Technician's note: Access approved.",
    'Footer: Repair was not completed.', 'Header: Work is pending.',
    'Footer: Summary\nRepair was not completed.'])
def test_unsupported_substantive_note_and_work_metadata_stay_pending(monkeypatch,tmp_path,note):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Replaced the pump.',note])
    assert not c.source.actions and not native_update((c,),'activity_summary').text
    assert any('not auto-imported' in n for n in c.source.notices)


@pytest.mark.parametrize('note',['Footer: Not done.','Header: No work carried out.',
                                 'Footer: Cancelled.','Billing contact: Not operational.',
                                 'Vendor: Repair was not completed.'])
def test_free_prose_metadata_never_certifies_action(monkeypatch,tmp_path,note):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Replaced the pump.',note])
    assert not c.source.actions and not sources.native_action_lines(c.source)
    assert not native_update((c,),'activity_summary').text


def test_mixed_labeled_unlabeled_aggregate_limit_cannot_restore_activity():
    from app.monthly_report_sources import SourceContent
    label='Vendor service report\nActions: Inspected '+('sample pump ' * 480)+'.'
    other='Inspected '+('sample pump ' * 30)+'.'
    s=ReportSource('id','synthetic-service.pdf','digest','.pdf',classification='Vendor service',
        page_texts=(label,other),selected_pages=(1,2),
        pdf_text_blocks=((1,0,len(label),sha256(label.encode()).hexdigest()),))
    s=sources.suggest_facts(s,synthetic_profiles()[0])
    assert not s.actions and len(s.notices)==2
    assert not sources.native_action_lines(s)
    assert not native_update((SourceContent(s),),'activity_summary').text


def test_unlabeled_separate_negative_block_cannot_be_dropped(monkeypatch,tmp_path):
    c,_=fixture(monkeypatch,tmp_path,['Actions: Replaced the pump.','It was not completed.'])
    assert not c.source.actions and not sources.native_action_lines(c.source)
    assert not native_update((c,),'activity_summary').text
    assert any('not auto-imported' in n for n in c.source.notices)


def test_metadata_follower_scan_does_not_copy_suffixes():
    from app.monthly_report_vendor_passages import unsupported_fields
    class NoSuffixCopies(list):
        def __getitem__(self,key):
            assert not isinstance(key,slice),'quadratic suffix copy'
            return super().__getitem__(key)
    class DenseText(str):
        def splitlines(self,*a,**k):
            return NoSuffixCopies(super().splitlines(*a,**k))
    text=DenseText('\n'.join(['Page: 1'] * 20000))
    assert not unsupported_fields(text)


@pytest.mark.parametrize('remainder',['It was not completed.', 'Not done.',
    'Vendor service report not completed.', 'Short annotation', 'Cancelled'])
@pytest.mark.parametrize('before',[True,False])
def test_unknown_page_remainder_before_or_after_action_is_pending(monkeypatch,tmp_path,remainder,before):
    fields=[remainder,'Actions: Replaced the pump.'] if before else ['Actions: Replaced the pump.',remainder]
    c,_=fixture(monkeypatch,tmp_path,fields)
    assert not c.source.actions and not sources.action_evidence(c.source)[0]
    assert not native_update((c,),'activity_summary').text
    assert any('not auto-imported' in n for n in c.source.notices)
