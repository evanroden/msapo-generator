"""An unreviewed page's displayed default must not mutate a reopened draft."""
from dataclasses import replace
import pytest
from streamlit.testing.v1 import AppTest
from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles, ReportDraft, ReportPeriod
from app.monthly_report_content_policy import page_fingerprint
from scripts.workspace_financial_pages import make_source

APP = """
import streamlit as st
from app.monthly_report_upload_ui import _render_section_page_review
from app.monthly_report_model import ReportPeriod, synthetic_profiles
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
content = st.session_state['content']
updated = _render_section_page_review(synthetic_profiles()[0], content, 'visit', field, {},
                                      period=ReportPeriod(2026,9))
st.session_state['content'] = updated
"""

@pytest.mark.parametrize('action', ['visit','edit','clear','keep','omit'])
def test_first_visit_is_not_caption_edit_but_explicit_decisions_bind_caption(tmp_path,monkeypatch,action):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'data'))
    p=synthetic_profiles()[0];path=make_source(tmp_path)
    c,_=sources.ingest(p,path.name,path.read_bytes())
    app=AppTest.from_string(APP,default_timeout=30)
    app.session_state['content']=c
    app.run();assert not app.exception
    original=ReportDraft(p,ReportPeriod(2026,9),'Synthetic',(),(),sources=(c.source,))
    after=replace(original,sources=(app.session_state['content'].source,))
    assert after.fingerprint==original.fingerprint
    caption=next(w for w in app.text_input if w.label=='Page caption')
    shown=caption.value
    if action in ('edit','clear'):
        value='Human caption' if action=='edit' else ''
        caption.set_value(value).run()
        assert dict(app.session_state['content'].source.captions)[1]==value
    elif action in ('keep','omit'):
        next(w for w in app.button if w.label==('Include page' if action=='keep' else 'Exclude page')).click().run()
        updated=app.session_state['content'].source
        assert dict(updated.captions)[1]==shown
        receipts=dict(updated.client_page_reviews if action=='keep' else updated.client_page_exclusions)
        assert receipts[1]==page_fingerprint(updated,1)
    else:
        app.run()
        assert app.session_state['content'].source==c.source
    assert not app.exception
