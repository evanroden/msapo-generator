"""A financial page warning must not advertise ordinary priced-page Review."""
from dataclasses import replace
from streamlit.testing.v1 import AppTest
from app.monthly_report_model import ReportDraft,ReportPeriod,default_sections
from app.monthly_report_correction_targets import picture_target
from test_monthly_report_page_manager import _prepared

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
