"""Navigation to the existing financial owner is never financial consent."""
from dataclasses import replace
from hashlib import sha256
from html import escape
from uuid import uuid4
import streamlit as st
from app.monthly_report_correction_targets import resolve_target,picture_target

NOTICE='This financial page changed or is unavailable. Your edits remain here; use its current warning.'


def financial_target(draft,contents,target):
    if len({b.key for b in draft.blocks})!=len(draft.blocks) or len({s.id for s in draft.sources})!=len(draft.sources):
        return None
    resolved=resolve_target(draft,target)
    if resolved is None:return None
    block,index,source=resolved
    if block is None or source is None or block.key!='mbcx_report' or source.suffix!='.pdf':return None
    from app.monthly_report_mbcx_financial_pages import _section_digest,has_financial_page_review
    try:_section_digest(draft.sections)
    except ValueError:return None
    matches=[c for c in contents if c.source.id==source.id]
    if len(matches)!=1 or matches[0].source!=source:return None
    from app.monthly_report_sources import image_numbers
    from app.monthly_report_section_uploads import included_pages
    from app.monthly_report_page_controls import page_asset_index
    if (target.page not in image_numbers(matches[0])
            or included_pages({b.key:b for b in draft.blocks}).get((source.id,target.page))!={'mbcx_report'}
            or page_asset_index(block,source.id,target.page)!=index
            or not has_financial_page_review(source,target.page)):
        return None
    return block,index,source


def queue_navigation(prefix,target,scope):
    from app.monthly_report_guided import _rich_text_scope
    for suffix in ('pending','ready','open'):
        st.session_state.pop(prefix+'_financial_correction_'+suffix,None)
    draft=st.session_state.get(prefix+'_draft');contents=st.session_state.get(prefix+'_evidence',())
    if draft is None or scope!=_rich_text_scope(prefix) or financial_target(draft,contents,target) is None:
        st.session_state[prefix+'_financial_correction_notice']=NOTICE;return
    st.session_state[prefix+'_financial_correction_pending']={
        'target':target,'before':draft,'scope':scope,'nonce':uuid4().hex}


def _caption_renewal(before,current,contents,target,changes):
    """Only exact same-render native caption capture may renew a target."""
    if before is None or resolve_target(before,target) is None:return None
    if [s.id for s in before.sources]!=[s.id for s in current.sources]:return None
    changed=False
    for old,new in zip(before.sources,current.sources):
        if old==new:continue
        if changes.get(old.id)!=(old,new) or replace(old,captions=new.captions)!=new:return None
        changed=True
    if not changed:return None
    from app.monthly_report_page_captions import synchronize_source_captions
    from app.monthly_report_asset_review import refresh_asset_source_context
    blocks,_=synchronize_source_captions({b.key:b for b in before.blocks},before.sources,current.sources)
    blocks={key:refresh_asset_source_context(b,current.sources) for key,b in blocks.items()}
    old,index,source=resolve_target(before,target)
    block=blocks.get(old.key);source=next((s for s in current.sources if s.id==source.id),None)
    if block is None or source is None or block.asset_hashes!=old.asset_hashes:return None
    expected=replace(before,blocks=tuple(blocks.values()),sources=current.sources)
    renewed=picture_target(expected,block,index,source=source,page=target.page)
    return renewed if financial_target(current,contents,renewed) is not None else None


def finish_navigation(prefix,draft,scope):
    request=st.session_state.pop(prefix+'_financial_correction_pending',None)
    if request is None:return
    contents=st.session_state.get(prefix+'_evidence',())
    if not isinstance(request,dict) or request.get('scope')!=scope:
        st.session_state[prefix+'_financial_correction_notice']=NOTICE;return
    target=request.get('target')
    if financial_target(draft,contents,target) is None:
        target=_caption_renewal(request.get('before'),draft,contents,target,st.session_state.get(prefix+'_source_native_changes',{}))
    if target is None or financial_target(draft,contents,target) is None:
        st.session_state[prefix+'_financial_correction_notice']=NOTICE;return
    st.session_state[prefix+'_financial_correction_ready']={**request,'target':target}
    st.session_state[prefix+'_period_editor_refresh']=True


def consume_navigation(prefix,draft,scope):
    request=st.session_state.pop(prefix+'_financial_correction_ready',None)
    if request is None:return
    contents=st.session_state.get(prefix+'_evidence',())
    if (not isinstance(request,dict) or request.get('scope')!=scope
            or not isinstance(request.get('nonce'),str) or not request['nonce']
            or financial_target(draft,contents,request.get('target')) is None):
        st.session_state[prefix+'_financial_correction_notice']=NOTICE;return
    target=request['target'];local=prefix+'_evidence_section_mbcx_report'
    st.session_state[local+'_selected']=target.source_id
    # Only disclosure. Never write _source_*, _visual_*, _pages or approval data.
    st.session_state[local+'_financial_'+target.source_id+'_open']=True
    st.session_state[prefix+'_financial_correction_open']=request


def render_owner_context(profile,content,blocks,local,*,period,editor_scope,sections,pages,field_key,kind):
    """Read-only exact context next to the authoritative native batch controls."""
    suffix='_evidence_section_mbcx_report'
    if not local.endswith(suffix):return
    prefix=local[:-len(suffix)]
    request=st.session_state.get(prefix+'_financial_correction_open')
    if not isinstance(request,dict):return
    target=request.get('target')
    if getattr(target,'source_id',None)!=content.source.id:return
    canonical=st.session_state.get(prefix+'_draft')
    if canonical is None:return
    draft=replace(canonical,profile=profile,period=period,sections=sections,
                  blocks=tuple(blocks.values()),sources=tuple(c.source for c in st.session_state.get(prefix+'_evidence',())))
    if request.get('scope')!=editor_scope or financial_target(draft,st.session_state.get(prefix+'_evidence',()),target) is None:
        st.session_state.pop(prefix+'_financial_correction_open',None)
        st.session_state[prefix+'_financial_correction_notice']=NOTICE;return
    st.caption(f'Warning for source page {target.page}. Your batch choices are unchanged; opening this review does not approve or include anything.')
    if target.page not in pages:
        field_key=local+'_financial_'+content.source.id+'_pages'
        kind='combobox'
        from app.monthly_report_page_context_ui import render_correction_page
        render_correction_page(profile,content,target.page)
        st.caption('This page is not selected in the batch. Choose it explicitly if you intend to review it.')
    identity=sha256(prefix.encode()).hexdigest()[:24]
    destination='report-correction-'+sha256((prefix+'\0'+editor_scope+'\0'+target.token).encode()).hexdigest()
    st.markdown('<span class="enfra-picture-correction" id="'+destination+'" data-report-identity="'+identity+
        '" data-field-kind="'+kind+'" data-field-key="'+escape(field_key,quote=True)+'" aria-hidden="true"></span>'+
        '<a class="enfra-page-correction-request" data-report-identity="'+identity+'" data-token="'+
        escape(request['nonce'],quote=True)+'" href="#'+destination+'" hidden></a>',unsafe_allow_html=True)
    st.session_state.pop(prefix+'_financial_correction_open',None)


def render_links(check,draft,prefix):
    if check.code!='financial_page':return
    from app.monthly_report_guided import _rich_text_scope
    for target in check.targets:
        if financial_target(draft,st.session_state.get(prefix+'_evidence',()),target) is not None:
            st.button(f'Review financial source page {target.page}',key=prefix+'_financial_correction_'+target.token,
                      on_click=queue_navigation,args=(prefix,target,_rich_text_scope(prefix)))
