"""Authoritative linked-wording evidence fields retain missing saved IDs."""
from dataclasses import replace
from streamlit.testing.v1 import AppTest
from test_monthly_report_ai_correction_targets import fixture

SCRIPT='''
import streamlit as st
from dataclasses import replace
from app.monthly_report_ai_ui import edit_linked_paragraphs
from app.monthly_report_ui import _field,preserve_report_draft_state,restore_report_draft_state
restore_report_draft_state()
draft=st.session_state.draft
blocks=edit_linked_paragraphs(draft,{b.key:b for b in draft.blocks},'ai_warning',_field)
st.session_state.draft=replace(draft,blocks=tuple(blocks.values()))
preserve_report_draft_state()
'''


def test_missing_saved_fact_id_remains_selected_until_explicit_removal():
    draft=fixture();missing=draft.blocks[0].ai_paragraphs[0].fact_ids[0]
    draft=replace(draft,sources=())
    app=AppTest.from_string(SCRIPT)
    app.session_state.draft=draft
    app.run()
    assert not app.exception
    assert app.session_state.draft.blocks[0].ai_paragraphs[0].fact_ids==(missing,)
    assert app.multiselect[0].value==[missing]
    assert any('Unavailable saved fact' in option for option in app.multiselect[0].options)
    app.run()
    assert app.session_state.draft.blocks[0].ai_paragraphs[0].fact_ids==(missing,)
    app.multiselect[0].set_value([]).run()
    assert not app.exception
    assert app.session_state.draft.blocks[0].ai_paragraphs[0].fact_ids==()
    assert not app.session_state.draft.blocks[0].reviewed

NAV_SCRIPT='''
import streamlit as st
from dataclasses import replace
from app.monthly_report_ai_ui import edit_linked_paragraphs
from app.monthly_report_ai_correction_ui import consume_navigation,finish_navigation,render_links,NOTICE
from app.monthly_report_checks import preflight
from app.monthly_report_guided import _rich_text_scope,_refresh_period_editors_after_commit
from app.monthly_report_ui import _field,preserve_report_draft_state,restore_report_draft_state
restore_report_draft_state()
prefix='ai_warning'
draft=st.session_state.ai_warning_draft
consume_navigation(prefix,draft,_rich_text_scope(prefix))
blocks=edit_linked_paragraphs(draft,{b.key:b for b in draft.blocks},prefix,_field)
draft=replace(draft,blocks=tuple(blocks.values()))
st.session_state.ai_warning_draft=draft
for check in preflight(draft): render_links(check,draft,prefix)
finish_navigation(prefix,draft,_rich_text_scope(prefix))
if st.session_state.pop(prefix+'_ai_correction_open',None) is not None:
    st.session_state[prefix+'_ai_correction_notice']=NOTICE
notice=st.session_state.pop(prefix+'_ai_correction_notice',None)
if notice: st.warning(notice)
preserve_report_draft_state()
_refresh_period_editors_after_commit(prefix)
'''


def workspace():
    draft=fixture();block=draft.blocks[0]
    bad=replace(block.ai_paragraphs[0],text='Replaced 99 seals.',flags=('Unsupported number: edit this paragraph against its evidence',))
    block=replace(block,ai_paragraphs=(*block.ai_paragraphs,bad))
    app=AppTest.from_string(NAV_SCRIPT,default_timeout=20)
    app.session_state.ai_warning_draft=replace(draft,blocks=(block,))
    app.run()
    assert not app.exception
    return app


def action(app):
    return next(b for b in app.button if b.label=='Edit paragraph 2')


def test_unblurred_other_paragraph_is_committed_before_exact_warning_focus():
    app=workspace()
    before=app.session_state.ai_warning_draft
    next(w for w in app.text_area if w.label=='Report paragraph 1').set_value('Replaced 2 seals after inspection.')
    action(app).click().run()
    assert not app.exception
    after=app.session_state.ai_warning_draft
    assert after.blocks[0].ai_paragraphs[0].text=='Replaced 2 seals after inspection.'
    assert after.blocks[0].ai_paragraphs[1]==before.blocks[0].ai_paragraphs[1]
    assert not after.blocks[0].reviewed and after.sources==before.sources
    marker='\n'.join(m.value for m in app.markdown)
    assert 'enfra-page-correction-request' in marker
    exact=next(w for w in app.text_area if w.label=='Report paragraph 2')
    assert 'data-field-key="'+exact.key+'"' in marker
    assert len(app.text_area)==3
    app.run()
    assert app.session_state.ai_warning_draft==after
    assert 'enfra-page-correction-request' not in '\n'.join(m.value for m in app.markdown)


def test_pending_explicit_evidence_removal_survives_other_paragraph_warning():
    app=workspace()
    next(w for w in app.multiselect if w.label=='Evidence for paragraph 1').set_value([])
    action(app).click().run()
    assert not app.exception
    assert app.session_state.ai_warning_draft.blocks[0].ai_paragraphs[0].fact_ids==()
    assert app.session_state.ai_warning_draft.blocks[0].ai_paragraphs[1].fact_ids
    assert not app.session_state.ai_warning_draft.blocks[0].reviewed
    assert 'enfra-page-correction-request' in '\n'.join(m.value for m in app.markdown)


def test_target_changed_during_warning_keeps_wording_but_rejects_old_destination():
    app=workspace()
    next(w for w in app.text_area if w.label=='Report paragraph 2').set_value('Replaced 100 seals.')
    action(app).click().run()
    assert not app.exception
    assert app.session_state.ai_warning_draft.blocks[0].ai_paragraphs[1].text=='Replaced 100 seals.'
    assert 'enfra-page-correction-request' not in '\n'.join(m.value for m in app.markdown)
    assert any('wording or evidence changed' in w.value for w in app.warning)
