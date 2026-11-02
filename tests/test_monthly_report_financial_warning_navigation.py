"""Exact financial warning routing never grants or includes a page."""
from dataclasses import replace
from types import SimpleNamespace
import pytest
from app import monthly_report_financial_correction_ui as ui
from app import monthly_report_guided as guided
from app.monthly_report_model import ReportDraft,ReportPeriod,SectionSpec,BlockSpec
from app.monthly_report_correction_targets import picture_target
from app.monthly_report_checks import preflight
from test_monthly_report_mbcx_financial_pages import setup,reviewed,sources

P='financial_warning'


def fixture(monkeypatch,tmp_path):
    profile,content,_=setup(monkeypatch,tmp_path)
    content=reviewed(profile,content)
    block,=sources.prepare_pages(profile,(content,),((content.source.id,'mbcx_report'),))
    # Preserve a prior financial receipt, but remove classification authority.
    content=replace(content,source=replace(content.source,financial_source_review=None))
    section=SectionSpec('mbcx','4','MBCx Reports',(BlockSpec('mbcx_report','pdf_pages'),))
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Synthetic Editor',(section,),(block,),sources=(content.source,))
    target=picture_target(draft,block,0,source=content.source,page=1)
    return draft,content,target


def test_preflight_attaches_exact_financial_identity_and_disclosure_alone_changes_no_content(monkeypatch,tmp_path):
    draft,content,target=fixture(monkeypatch,tmp_path)
    check=next(c for c in preflight(draft) if c.code=='financial_page')
    assert check.targets==(target,)
    local=P+'_evidence_section_mbcx_report';key=local+'_financial_'+content.source.id
    state={P+'_draft':draft,P+'_evidence':(content,),local+'_selected':'old-source',key+'_pages':[2],key+'_source_sentinel':False,key+'_visual_sentinel':False}
    monkeypatch.setattr(ui,'st',SimpleNamespace(session_state=state))
    monkeypatch.setattr(guided,'_rich_text_scope',lambda prefix:'scope')
    ui.queue_navigation(P,target,'scope')
    assert state[local+'_selected']=='old-source' and key+'_open' not in state
    ui.finish_navigation(P,draft,'scope')
    assert state[local+'_selected']=='old-source'
    ui.consume_navigation(P,draft,'scope')
    assert state[local+'_selected']==content.source.id and state[key+'_open'] is True
    assert state[key+'_pages']==[2] and not state[key+'_source_sentinel'] and not state[key+'_visual_sentinel']
    assert state[P+'_draft']==draft and state[P+'_evidence']==(content,)
    snapshot=dict(state);ui.consume_navigation(P,draft,'scope');ui.finish_navigation(P,draft,'scope')
    assert snapshot==state


@pytest.mark.parametrize('phase',['queued','ready'])
@pytest.mark.parametrize('change',['scope','source','fact_scope','missing','omitted','duplicate_block','duplicate_source','missing_original','duplicate_original'])
def test_stale_financial_target_never_opens_or_selects_sibling(monkeypatch,tmp_path,phase,change):
    draft,content,target=fixture(monkeypatch,tmp_path)
    local=P+'_evidence_section_mbcx_report';key=local+'_financial_'+content.source.id
    state={P+'_draft':draft,P+'_evidence':(content,),local+'_selected':'old',key+'_pages':[]}
    monkeypatch.setattr(ui,'st',SimpleNamespace(session_state=state))
    monkeypatch.setattr(guided,'_rich_text_scope',lambda prefix:'scope')
    ui.queue_navigation(P,target,'scope')
    if phase=='ready':ui.finish_navigation(P,draft,'scope')
    scope='scope'
    if change=='scope':scope='new'
    elif change=='missing':draft=replace(draft,blocks=())
    elif change=='omitted':draft=replace(draft,blocks=(replace(draft.blocks[0],source='Omit'),))
    elif change=='duplicate_block':draft=replace(draft,blocks=(*draft.blocks,*draft.blocks))
    elif change=='duplicate_source':draft=replace(draft,sources=(*draft.sources,*draft.sources))
    elif change=='missing_original':state[P+'_evidence']=()
    elif change=='duplicate_original':state[P+'_evidence']=(content,content)
    else:
        content=replace(content,source=replace(content.source,**({'sha256':'changed'} if change=='source' else {'facility':'Other site'})))
        draft=replace(draft,sources=(content.source,));state[P+'_evidence']=(content,)
    (ui.finish_navigation if phase=='queued' else ui.consume_navigation)(P,draft,scope)
    assert state[local+'_selected']=='old' and key+'_open' not in state
    assert state[key+'_pages']==[] and P+'_financial_correction_open' not in state
    assert 'changed' in state[P+'_financial_correction_notice']


SCRIPT='''
import streamlit as st
from app.monthly_report_financial_correction_ui import consume_navigation,finish_navigation,render_links
from app.monthly_report_mbcx_financial_pages import render_reviewed_batch
from app.monthly_report_checks import preflight
from app.monthly_report_guided import _rich_text_scope,_refresh_period_editors_after_commit
from app.monthly_report_ui import restore_report_draft_state,preserve_report_draft_state
restore_report_draft_state()
prefix='financial_warning';draft=st.session_state[prefix+'_draft'];local=prefix+'_evidence_section_mbcx_report'
consume_navigation(prefix,draft,_rich_text_scope(prefix))
content=st.session_state[prefix+'_evidence'][0]
handled,revised,batch=render_reviewed_batch(draft.profile,content,{b.key:b for b in draft.blocks},{},local,
    period=draft.period,editor_scope=_rich_text_scope(prefix),sections=draft.sections)
assert not batch
for check in preflight(draft):render_links(check,draft,prefix)
finish_navigation(prefix,draft,_rich_text_scope(prefix))
preserve_report_draft_state()
_refresh_period_editors_after_commit(prefix)
'''


@pytest.mark.parametrize('selected',[False,True])
def test_actual_owner_disclosure_focus_is_not_classification_or_visual_attestation(monkeypatch,tmp_path,selected):
    from streamlit.testing.v1 import AppTest
    draft,content,target=fixture(monkeypatch,tmp_path)
    app=AppTest.from_string(SCRIPT,default_timeout=20)
    app.session_state[P+'_draft']=draft;app.session_state[P+'_evidence']=(content,)
    key=P+'_evidence_section_mbcx_report_financial_'+content.source.id
    app.session_state[key+'_pages']=[1] if selected else []
    app.run();assert not app.exception
    next(b for b in app.button if b.label=='Review financial source page 1').click().run()
    assert not app.exception
    assert next(c for c in app.checkbox if c.label=='Review client-facing ENFRA financial pages').value
    assert not next(c for c in app.checkbox if c.label=='This is an ENFRA report intended for the client').value
    assert not next(c for c in app.checkbox if c.label.startswith('I reviewed these pages:')).value
    assert next(b for b in app.button if b.label=='Include reviewed financial pages').disabled
    assert app.multiselect[0].value==([1] if selected else [])
    assert app.session_state[P+'_draft']==draft and app.session_state[P+'_evidence']==(content,)
    markup='\n'.join(m.value for m in app.markdown)
    field=(next(c.key for c in app.checkbox if c.label=='This is an ENFRA report intended for the client') if selected else app.multiselect[0].key)
    assert 'data-field-key="'+field+'"' in markup
    assert 'data-field-kind="'+('checkbox' if selected else 'combobox')+'"' in markup
    app.run();assert not app.exception
    assert not any('enfra-page-correction-request' in m.value for m in app.markdown)


@pytest.mark.parametrize('change',['scope','hash','content','caption','site','profile','period','destination'])
def test_explicit_pending_consents_do_not_restore_into_changed_owner(monkeypatch,tmp_path,change):
    from streamlit.testing.v1 import AppTest
    draft,content,target=fixture(monkeypatch,tmp_path)
    app=AppTest.from_string(SCRIPT,default_timeout=20)
    app.session_state[P+'_draft']=draft;app.session_state[P+'_evidence']=(content,)
    key=P+'_evidence_section_mbcx_report_financial_'+content.source.id
    app.session_state[key+'_pages']=[1]
    app.run()
    next(b for b in app.button if b.label=='Review financial source page 1').click().run()
    next(w for w in app.checkbox if w.label=='This is an ENFRA report intended for the client').check().run()
    next(w for w in app.checkbox if w.label.startswith('I reviewed these pages:')).check().run()
    assert not app.exception
    assert not app.session_state[P+'_draft'].sources[0].financial_source_review
    app.run()
    assert next(w for w in app.checkbox if w.label=='This is an ENFRA report intended for the client').value
    assert next(w for w in app.checkbox if w.label.startswith('I reviewed these pages:')).value
    if change=='scope':app.session_state[P+'_rich_text_epoch']='replacement'
    elif change=='profile':draft=replace(draft,profile=replace(draft.profile,key='different-profile'))
    elif change=='period':draft=replace(draft,period=ReportPeriod(2026,10))
    elif change=='destination':draft=replace(draft,sections=(replace(draft.sections[0],key='different-section'),))
    else:
        updates={'hash':{'sha256':'a'*64},'content':{'page_texts':('Changed saved reading $250.',)},
                 'caption':{'captions':((1,'Revised caption'),)},'site':{'facility':'Other site'}}[change]
        content=replace(content,source=replace(content.source,**updates));draft=replace(draft,sources=(content.source,))
    app.session_state[P+'_draft']=draft;app.session_state[P+'_evidence']=(content,)
    app.run();assert not app.exception
    assert not next(w for w in app.checkbox if w.label=='This is an ENFRA report intended for the client').value
    assert not next(w for w in app.checkbox if w.label.startswith('I reviewed these pages:')).value
    assert next(b for b in app.button if b.label=='Include reviewed financial pages').disabled
    assert app.session_state[P+'_draft']==draft
