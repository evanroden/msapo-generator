"""Actual native callback delivery and phased routing, using synthetic pages."""
from dataclasses import replace
from streamlit.testing.v1 import AppTest
from app.monthly_report_model import ReportDraft, ReportPeriod, default_sections
from app.monthly_report_content_policy import page_allowed
from test_monthly_report_page_manager import _prepared

SCRIPT = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_correction_targets import picture_target
from app.monthly_report_page_controls import apply_page_request
from app.monthly_report_page_navigation import queue_navigation, finish_navigation, consume_navigation
from app.monthly_report_upload_ui import _included_page_controls
prefix='nav';local=prefix+'_evidence_section_water_reports';scope='incarnation'
def field(key,value):
    if key not in st.session_state: st.session_state[key]=value
    return key
if 'fixture' in st.session_state:
    draft,contents=st.session_state.fixture
    consume_navigation(st.session_state,prefix,draft,contents,scope)
    st.session_state.pop(prefix+'_page_navigation_origin',None)
    request=st.session_state.pop(local+'_page_edit',None)
    if request:
        contents,changes=apply_page_request(contents,{b.key:b for b in draft.blocks},request)
        draft=replace(draft,blocks=tuple(changes.get(b.key,b) for b in draft.blocks),
                      sources=tuple(c.source for c in contents))
        st.session_state['caption_commits']=st.session_state.get('caption_commits',0)+1
    source_id=st.selectbox('File to review',[c.source.id for c in contents],
        key=field(local+'_selected',contents[0].source.id))
    content=next(c for c in contents if c.source.id==source_id)
    next_page=st.session_state.pop(local+'_'+content.source.id+'_next_page',None)
    if next_page is not None:st.session_state['native_page']=next_page
    page=st.selectbox('Page to review',list(range(1,len(content.source.page_texts)+1)),key=field('native_page',1))
    blocks={b.key:b for b in draft.blocks}
    source,handled=_included_page_controls(content.source,page,local,field,blocks,True,contents,
        scope=scope,navigation_prefix=prefix)
    contents=tuple(replace(c,source=source) if c.source.id==source.id else c for c in contents)
    draft=replace(draft,blocks=tuple(blocks.values()),sources=tuple(c.source for c in contents))
    st.session_state.fixture=(draft,contents)
    # Model the recovery outcome independently of navigation. No navigation
    # helper reads/writes a saved marker or claims this was durably saved.
    if st.session_state.get('fail_recovery'):
        st.error('Automatic recovery could not keep these edits. Current text is not saved for a refresh.')
    else:
        st.session_state['recovered_fixture']=(draft,contents)
    target_page=st.session_state.get('target_page',2)
    from app.monthly_report_page_controls import page_asset_index
    target_source=next(c.source for c in contents if c.source.id==st.session_state.get('target_source',source.id))
    target_index=page_asset_index(draft.blocks[0],target_source.id,target_page)
    target=picture_target(draft,draft.blocks[0],target_index,source=target_source,page=target_page)
    st.button('Open exact correction',on_click=queue_navigation,
        args=(st.session_state,prefix,draft,contents,target,scope))
    finish_navigation(st.session_state,prefix,draft,contents,scope)
    notice=st.session_state.pop(prefix+'_page_navigation_notice',None)
    if notice:st.warning(notice)
    if st.session_state.pop(prefix+'_period_editor_refresh',False):st.rerun()
'''


def editor(monkeypatch,tmp_path):
    profile,content,block=_prepared(monkeypatch,tmp_path)
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Synthetic Editor',default_sections(),
                      (block,),sources=(content.source,))
    app=AppTest.from_string(SCRIPT).run()
    app.session_state.fixture=(draft,(content,));app.run()
    assert not app.exception
    return app


def test_unblurred_caption_commits_once_before_other_page_and_repeated_render(monkeypatch,tmp_path):
    app=editor(monkeypatch,tmp_path)
    prior_selected=app.session_state.fixture[0].sources[0].selected_pages
    app.text_input[0].set_value('Unblurred old-page caption')
    next(b for b in app.button if b.label=='Open exact correction').click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label=='Page to review').value==2
    draft,_=app.session_state.fixture
    assert draft.blocks[0].asset_captions[0]=='Unblurred old-page caption'
    assert draft.sources[0].selected_pages==prior_selected
    assert not page_allowed(draft.sources[0],1)
    assert app.session_state.caption_commits==1
    assert app.session_state.recovered_fixture==app.session_state.fixture
    for _ in range(2):app.run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label=='Page to review').value==2 and app.session_state.caption_commits==1


def test_same_page_and_failed_recovery_preserve_work_without_saved_claim(monkeypatch,tmp_path):
    app=editor(monkeypatch,tmp_path)
    saved=app.session_state.recovered_fixture
    app.session_state.target_page=1;app.session_state.fail_recovery=True
    app.run()
    app.text_input[0].set_value('Still only in working memory')
    next(b for b in app.button if b.label=='Open exact correction').click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label=='Page to review').value==1
    assert app.text_input[0].value=='Still only in working memory'
    assert app.session_state.caption_commits==1
    assert app.session_state.recovered_fixture==saved
    assert any('not saved for a refresh' in e.value for e in app.error)
    assert 'nav_page_navigation_ready' not in app.session_state.filtered_state
    app.session_state.fail_recovery=False;app.run()
    assert app.session_state.recovered_fixture==app.session_state.fixture
    assert app.session_state.caption_commits==1


def test_native_source_switch_keeps_unblurred_caption_with_identical_files(monkeypatch,tmp_path):
    from test_monthly_report_page_navigation import two_sources
    draft,contents=two_sources(monkeypatch,tmp_path)
    app=AppTest.from_string(SCRIPT).run()
    app.session_state.fixture=(draft,contents)
    app.session_state.target_page=1
    app.session_state.target_source=contents[1].source.id
    app.run()
    assert not app.exception
    app.text_input[0].set_value('Old source caption delivered with correction')
    next(b for b in app.button if b.label=='Open exact correction').click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label=='File to review').value==contents[1].source.id
    current,_=app.session_state.fixture
    assert current.blocks[0].asset_captions==('Old source caption delivered with correction','Second occurrence')
    assert current.sources[1]==contents[1].source
    assert app.session_state.caption_commits==1
