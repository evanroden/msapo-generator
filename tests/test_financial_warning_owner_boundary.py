"""A financial page warning must not advertise ordinary priced-page Review."""
from dataclasses import replace
from streamlit.testing.v1 import AppTest
from app.monthly_report_model import ReportDraft,ReportPeriod,default_sections
from app.monthly_report_correction_targets import picture_target
from test_monthly_report_page_manager import _prepared
import pytest

SCRIPT='''
import streamlit as st
from app.monthly_report_checks import ReportCheck
from app.monthly_report_correction_ui import render_source_page_links
render_source_page_links(ReportCheck(st.session_state.code,'Synthetic gate',True,'water_reports',
    (st.session_state.target,)),st.session_state.draft,'guard')
'''


def test_financial_page_has_no_generic_or_water_navigation_fallback(monkeypatch,tmp_path):
    profile,content,block=_prepared(monkeypatch,tmp_path)
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Synthetic Editor',default_sections(),(block,),sources=(content.source,))
    app=AppTest.from_string(SCRIPT)
    app.session_state.draft=draft
    app.session_state.target=picture_target(draft,block,0,source=content.source,page=1)
    app.session_state.guard_evidence=(content,)
    app.session_state.code='financial_page'
    app.run()
    assert not app.exception and len(app.button)==0
    app.session_state.code='client_source_page'
    app.run()
    assert not app.exception and len(app.button)==1
    assert app.button[0].label=='Review source page 1 · picture 1'


@pytest.mark.parametrize('destination', ['water_reports', 'vendor_reports'])
def test_only_exact_manager_page_route_declares_its_own_return_owner(monkeypatch,tmp_path,destination):
    profile,content,block=_prepared(monkeypatch,tmp_path)
    block=replace(block,key=destination)
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Synthetic Editor',default_sections(),(block,),sources=(content.source,))
    app=AppTest.from_string(SCRIPT)
    app.session_state.draft=draft
    app.session_state.target=picture_target(draft,block,0,source=content.source,page=1)
    app.session_state.guard_evidence=(content,)
    app.session_state.code='client_source_page'
    app.run()
    assert not app.exception and len(app.button)==1
    markup='\n'.join(node.value for node in app.markdown)
    assert ('data-navigation-owner="exact-manager-page"' in markup) is (destination=='vendor_reports')
    assert app.button[0].label==('Open' if destination=='vendor_reports' else 'Review')+' source page 1 · picture 1'
    assert app.session_state.draft==draft and app.session_state.guard_evidence==(content,)


CALLBACK_SCRIPT='''
import streamlit as st
from app.monthly_report_checks import ReportCheck
from app.monthly_report_correction_ui import render_source_page_links
from app.monthly_report_manager_page_navigation import consume_navigation,finish_navigation,page_markup
from app.monthly_report_guided import _rich_text_scope,_refresh_period_editors_after_commit
prefix='guard';draft=st.session_state[prefix+'_draft'];contents=st.session_state[prefix+'_evidence'];scope=_rich_text_scope(prefix)
consume_navigation(st.session_state,prefix,draft,contents,scope)
if contents:
    markup=page_markup(st.session_state,prefix,contents[0].source,1,'exact-native-page',scope,source_review=True)
    if markup: st.markdown(markup,unsafe_allow_html=True)
render_source_page_links(ReportCheck('client_source_page','Synthetic gate',True,'vendor_reports',
    (st.session_state.target,)),draft,prefix)
finish_navigation(st.session_state,prefix,draft,contents,scope)
_refresh_period_editors_after_commit(prefix)
'''


@pytest.mark.parametrize('rejection', [None,'changed-source','changed-scope','missing-original'])
def test_actual_manager_callback_only_emits_handoff_for_accepted_current_task(monkeypatch,tmp_path,rejection):
    profile,content,block=_prepared(monkeypatch,tmp_path)
    block=replace(block,key='vendor_reports')
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Synthetic Editor',default_sections(),(block,),sources=(content.source,))
    app=AppTest.from_string(CALLBACK_SCRIPT)
    app.session_state.guard_draft=draft
    app.session_state.guard_evidence=(content,)
    app.session_state.target=picture_target(draft,block,0,source=content.source,page=1)
    app.session_state.guard_evidence_selected='earlier-owner'
    app.run();assert not app.exception and len(app.button)==1
    action=app.button[0]
    if rejection=='changed-source':
        changed=replace(content.source,vendor='Changed since this warning rendered')
        app.session_state.guard_draft=replace(draft,sources=(changed,))
        app.session_state.guard_evidence=(replace(content,source=changed),)
    elif rejection=='changed-scope': app.session_state.guard_rich_text_epoch='replacement-incarnation'
    elif rejection=='missing-original': app.session_state.guard_evidence=()
    action.click().run();assert not app.exception
    markup='\n'.join(node.value for node in app.markdown)
    if rejection:
        assert 'enfra-page-correction-request' not in markup
        assert 'data-navigation-token=' not in markup
        assert app.session_state.guard_evidence_selected=='earlier-owner'
    else:
        assert 'enfra-page-correction-request' in markup
        assert 'data-navigation-token=' in markup
        assert app.session_state.guard_evidence_selected==content.source.id
    assert app.session_state.guard_draft.sources[0].client_page_reviews==draft.sources[0].client_page_reviews
