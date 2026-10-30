"""Explicit synthetic historical reports in the existing isolated full editor.

Only fixture installation and read-only observations are test controls. Current
warnings are unresolved; production fields, review, saving and outputs own all
corrections. No customer files, network reader, hidden browser-state injection
or alternate report editor.
"""
from dataclasses import asdict,replace
from datetime import date
from hashlib import sha256
from html import escape
import json
from pathlib import Path

SCENARIOS=('source','shared','ai','financial')
MISSING_FACT='synthetic-unavailable-historical-fact'
BAD_DATE_FACT='synthetic-historical-unsupported-date'
CAPTIONS=('Independent synthetic improvement caption.','Independent synthetic vendor caption.')
PENDING='Synthetic pending note retained through exact warning navigation.'


def _pdf(text,*,financial=False):
    import fitz
    doc=fitz.open();page=doc.new_page()
    page.insert_text((40,60),'SYNTHETIC HISTORICAL SOURCE - NO CLIENT DATA\n'+text)
    page.draw_rect(fitz.Rect(40,180,120,230),color=(1,0,1) if financial else (0,0,1),fill=(1,0,1) if financial else (0,0,1))
    raw=doc.tobytes();doc.close();return raw


def prepare_scenario(name):
    from app import monthly_report_qa_fixture as fixture,monthly_report_testing as testing
    from app import monthly_report_sources as sources,monthly_report_library as library
    from app.monthly_report_source_details import correct_source_details
    from app.monthly_report_checks import preflight
    if testing.scope() is None or name not in SCENARIOS:
        raise ValueError('Warning fixture requires an authorized isolated synthetic scenario.')
    draft=fixture.prepare('prefill');profile=draft.profile;blocks={b.key:b for b in draft.blocks}
    def ingest(filename,raw,classification='Vendor service'):
        content,_=sources.ingest(profile,filename,raw)
        source=correct_source_details(replace(content.source,classification=classification),profile,date(2026,9,3),'qa-north')
        return replace(content,source=source)
    old=ingest('synthetic-old-warning-owner.pdf',_pdf('Demo North\n2026-09-03\nInspected the old synthetic pump.'),
               'MBCx' if name=='financial' else 'Vendor service')
    if name=='source':
        target=ingest('synthetic-details-warning.pdf',_pdf('Demo North\nService date: 2026-09-03\nSynthetic inspection record. Saved historical metadata was not filled.'))
        target=replace(target,source=replace(target.source,facility='',service_date='',scope_review=''))
    elif name=='shared':
        from app.monthly_report_content_policy import page_fingerprint
        from app.monthly_report_asset_review import approve_asset
        target=ingest('synthetic-shared-warning.pdf',_pdf('Demo North\n2026-09-03\nInspected shared synthetic equipment.'))
        source=replace(target.source,client_page_reviews=((1,page_fingerprint(target.source,1)),))
        target=replace(target,source=source)
        page,=sources.prepare_pages(profile,(target,),((source.id,'vendor_reports'),))
        # Historical captions were independently reviewed before this explicit
        # synthetic metadata revision invalidated the current source review.
        for key,caption in zip(('improvements','vendor_reports'),CAPTIONS):
            blocks[key]=approve_asset(replace(page,key=key,asset_captions=(caption,)),0)
        source=replace(source,captions=((1,'Synthetic current source caption, independent of report captions.'),))
        target=replace(target,source=source)
    elif name=='ai':
        from app import monthly_report_ai as ai
        from app.monthly_report_model import EvidenceFact,DraftParagraph
        target=ingest('synthetic-ai-warning.txt',b'Demo North\n2026-09-03\nInspected the synthetic pump. Replaced 2 seals.')
        source=target.source
        facts=(EvidenceFact('synthetic-inspection',source.id,1,'action','Inspected the synthetic pump.','Inspected the synthetic pump.','2026-09-03'),
               EvidenceFact('synthetic-seals',source.id,1,'action','Replaced 2 seals.','Replaced 2 seals.','2026-09-03'))
        bad=replace(facts[1],id=BAD_DATE_FACT,text='Historical seal replacement date.',date='2026-09-25')
        source=correct_source_details(replace(source,facts=(*facts,bad)),profile,date(2026,9,3),'qa-north')
        target=replace(target,source=source)
        ref=sources.source_reference(source,1)
        paragraphs=(DraftParagraph('Inspected the synthetic pump.',(facts[0].id,),(ref,)),
            DraftParagraph('Replaced 99 seals.',(facts[1].id,bad.id,MISSING_FACT),(ref,),('Unsupported number: 99',)))
        blocks['activity_summary']=replace(blocks['activity_summary'],ai_written=True,ai_paragraphs=paragraphs,
            text='\n'.join('- '+p.text for p in paragraphs),references=(ref,),ai_evidence_fingerprint='',reviewed_fingerprint='')
    else:
        from app.monthly_report_mbcx_financial_pages import review_pages,page_review_fingerprint,SEMANTICS
        target=ingest('synthetic-financial-warning.pdf',_pdf('Demo North\n2026-09-03\nENFRA client commissioning report.\nVerified annual savings: $125.',financial=True),'MBCx')
        historical=review_pages(profile,target,(1,),source_confirmed=True,
            visual_fingerprints=((1,page_review_fingerprint(target.source,1)),),financial_semantics=SEMANTICS)
        page,=sources.prepare_pages(profile,(historical,),((historical.source.id,'mbcx_report'),))
        blocks[page.key]=page
        # A saved historical receipt is deliberately incomplete now. The
        # current production financial gate denies it until explicit review.
        target=replace(historical,source=replace(historical.source,financial_source_review=None))
    draft=replace(draft,blocks=tuple(blocks.values()),sources=(old.source,target.source))
    saved=library.load_snapshot(profile.contract,profile.key,draft.period)
    library.save_snapshot(draft,expected_revision=saved.revision,entered_editor=fixture.ACTOR)
    expected={'source':{'source_facility','source_date_unknown'},'shared':{'client_source_page'},
              'ai':{'ai_evidence','ai_date'},'financial':{'financial_page'}}[name]
    codes={c.code for c in preflight(draft)}
    if not expected<=codes:raise ValueError('Synthetic fixture did not retain its intended unresolved warnings: '+repr(codes))
    return draft


def _snapshot(draft):
    from app.monthly_report_checks import preflight
    from app.monthly_report_content_policy import page_allowed
    return {'fingerprint':draft.fingerprint,'sources':[asdict(s) for s in draft.sources],
        'blocks':{b.key:asdict(b) for b in draft.blocks},
        'checks':[{'code':c.code,'blocking':c.blocking,'block':c.block_key,'targets':[getattr(t,'token','') for t in c.targets]} for c in preflight(draft)],
        'financial_allowed':{s.id:[n for n in s.selected_pages if page_allowed(s,n,profile=draft.profile,destination='mbcx_report')] for s in draft.sources}}


def render(base,token,field,move):
    import streamlit as st
    from app import monthly_report_library as library,monthly_report_qa_fixture as fixture,monthly_report_testing as testing
    from app.monthly_report_testing_ui import _select_fixture,_working_report
    from app.monthly_report_ui import preserve_report_draft_state,restore_report_draft_state
    from app.monthly_report_guided import render_guided_workflow
    from app.monthly_report_editor import _signature
    from app.monthly_report_active_work import load
    from scripts.workspace_browser_observations import require_synthetic_root
    from scripts.workspace_history_observations import namespace
    require_synthetic_root(base)
    if testing.scope() is None:raise ValueError('Warning QA must remain isolated.')
    testing.data_dir(base)
    target,identity,generation=namespace(base,token)
    st.title('Synthetic exact-warning acceptance')
    scenario=st.selectbox('Synthetic historical scenario',SCENARIOS,key='warning_scenario')
    saved=library.load_snapshot(fixture.CONTRACT,fixture.profile().key,fixture.PERIOD)
    if st.button('Load synthetic historical report with unresolved warnings',disabled=saved is not None):
        historical=prepare_scenario(scenario)
        from app.monthly_report_sources import source_bytes
        from app.monthly_report_visuals import org_page,org_groups
        inputs=target/'warning-input';inputs.mkdir()
        (inputs/'source-original').write_bytes(source_bytes(historical.profile,historical.sources[1]))
        chart=next(b for b in historical.blocks if b.key=='org_chart')
        for n in range(len(org_groups(chart.org_nodes))):
            (inputs/f'baseline-org-{n}.png').write_bytes(org_page(chart.org_nodes,n))
        (target/'warning-scenario.json').write_text(json.dumps({'scenario':scenario,'synthetic_only':True}))
        _select_fixture();st.rerun()
    if saved is None:
        st.caption('No report or approval exists until the explicit synthetic fixture action.');return
    installed=json.loads((target/'warning-scenario.json').read_text())['scenario']
    if st.session_state.get('report_contract')!=fixture.CONTRACT:_select_fixture()
    st.session_state['_monthly_qa_generation']=generation
    # Same existing field-mirror entry protocol as web_ui + monthly_report_ui.
    preserve_report_draft_state();restore_report_draft_state()
    render_guided_workflow(token,'America/New_York',field,move)
    preserve_report_draft_state(finalize=True)
    working=_working_report(saved)
    active=load(token,fixture.CONTRACT,fixture.profile().key,fixture.PERIOD)
    shared=library.load_snapshot(fixture.CONTRACT,fixture.profile().key,fixture.PERIOD)
    prefix='report_guided_'+_signature((fixture.CONTRACT,fixture.profile().key,fixture.PERIOD.key))
    package=st.session_state.get(prefix+'_package');output={}
    if package is not None and package.fingerprint==working.fingerprint and package.pdf:
        directory=target/'warning-output';directory.mkdir(exist_ok=True)
        for name,raw in (('report.docx',package.docx),('report.pdf',package.pdf)):
            (directory/name).write_bytes(raw)
            output[name]={'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}
    sequence=st.session_state.get('warning_sequence',0)+1;st.session_state.warning_sequence=sequence
    from app.monthly_report_sources import source_bytes
    originals={s.id:sha256(source_bytes(working.profile,s)).hexdigest() for s in working.sources}
    selected={k:v for k,v in st.session_state.items() if k.startswith(prefix) and
              (k.endswith('_pages') or '_ai_read_pages_' in k or k.endswith('_ai_source') or k.endswith('_selected')) and isinstance(v,(str,list,tuple))}
    record={'scenario':installed,'sequence':sequence,'editor_prefix':prefix,'scope':identity,'generation':generation,
        'working':_snapshot(working),'durable':_snapshot(active.draft) if active else None,
        'shared':_snapshot(shared.draft) if shared else None,'originals':originals,'selected':selected,'output':output,
        'blocked_external_attempts':len(getattr(__import__('sys'),'_monthly_dom_attempts',()))}
    st.html('<span hidden data-warning-routes="'+escape(json.dumps(record,sort_keys=True),quote=True)+'"></span>')
