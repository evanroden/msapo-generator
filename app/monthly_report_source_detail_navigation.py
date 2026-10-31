"""Revision-bound entry to the existing native date/site owner, never Apply."""
from dataclasses import replace
from html import escape
from uuid import uuid4
import streamlit as st
from app.monthly_report_correction_targets import resolve_target,source_target

FIELDS={'source_facility':'site','source_period':'date','source_date_unknown':'date'}
NOTICE='This source changed or is unavailable. Your edits remain here; use its current warning.'


def current_source(draft,contents,target):
    if not any(s.key=='activity' for s in draft.sections):return None
    resolved=resolve_target(draft,target)
    if resolved is None or resolved[0] is not None or resolved[2] is None or target.page!=0:return None
    source=resolved[2]
    if len({s.id for s in draft.sources})!=len(draft.sources):return None
    matches=[c for c in contents if c.source.id==source.id]
    return source if len(matches)==1 and matches[0].source==source else None


def queue_navigation(prefix,target,code,scope):
    from app.monthly_report_guided import _rich_text_scope
    for suffix in ('pending','ready','open'):
        st.session_state.pop(prefix+'_source_detail_navigation_'+suffix,None)
    draft=st.session_state.get(prefix+'_draft');contents=st.session_state.get(prefix+'_evidence',())
    if (draft is None or code not in FIELDS or scope!=_rich_text_scope(prefix)
            or current_source(draft,contents,target) is None):
        st.session_state[prefix+'_source_detail_navigation_notice']=NOTICE;return
    st.session_state[prefix+'_source_detail_navigation_pending']={
        'target':target,'code':code,'scope':scope,'before':draft,'nonce':uuid4().hex}


def finish_navigation(prefix,draft,scope):
    request=st.session_state.pop(prefix+'_source_detail_navigation_pending',None)
    if request is None:return
    contents=st.session_state.get(prefix+'_evidence',())
    if not isinstance(request,dict) or request.get('scope')!=scope or request.get('code') not in FIELDS:
        st.session_state[prefix+'_source_detail_navigation_notice']=NOTICE;return
    target=request.get('target')
    if current_source(draft,contents,target) is None:
        before=request.get('before');original=resolve_target(before,target) if before is not None else None
        matches=[s for s in draft.sources if s.id==getattr(target,'source_id',None)]
        if original and original[2] is not None and len(matches)==1:
            old=original[2];new=matches[0]
            from app.monthly_report_correction_targets import report_identity
            if (report_identity(before)==report_identity(draft)
                    and old!=new and replace(old,captions=new.captions)==new
                    and st.session_state.get(prefix+'_source_native_changes',{}).get(old.id)==(old,new)):
                target=source_target(draft,new)
    if current_source(draft,contents,target) is None:
        st.session_state[prefix+'_source_detail_navigation_notice']=NOTICE;return
    st.session_state[prefix+'_source_detail_navigation_ready']={**request,'target':target}
    st.session_state[prefix+'_period_editor_refresh']=True


def consume_navigation(prefix,draft,scope):
    request=st.session_state.pop(prefix+'_source_detail_navigation_ready',None)
    if request is None:return
    if (not isinstance(request,dict) or request.get('scope')!=scope or request.get('code') not in FIELDS
            or not isinstance(request.get('nonce'),str) or not request['nonce']
            or current_source(draft,st.session_state.get(prefix+'_evidence',()),request.get('target')) is None):
        st.session_state[prefix+'_source_detail_navigation_notice']=NOTICE;return
    identity=request['target'].source_id
    st.session_state[prefix+'_batch_files_open']=True
    st.session_state[prefix+'_batch_files_open_open_request']=True
    st.session_state[prefix+'_evidence_selected']=identity
    st.session_state[prefix+'_source_active_selected']=identity
    st.session_state[prefix+'_source_review_context']=identity
    st.session_state[prefix+'_source_detail_navigation_open']=request


def render_marker(prefix,source,scope):
    request=st.session_state.get(prefix+'_source_detail_navigation_open')
    if not isinstance(request,dict):return
    target=request.get('target')
    if getattr(target,'source_id',None)!=source.id:return
    st.session_state.pop(prefix+'_source_detail_navigation_open',None)
    if (request.get('scope')!=scope or source.sha256!=target.source_hash
            or source.fingerprint!=target.source_revision or request.get('code') not in FIELDS):
        st.session_state[prefix+'_source_detail_navigation_notice']=NOTICE;return
    st.markdown('<span class="enfra-source-review-target" data-source-id="'+escape(source.id,quote=True)+
        '" data-field="'+FIELDS[request['code']]+'" data-token="'+escape(request['nonce'],quote=True)+'"></span>',unsafe_allow_html=True)


def render_link(check,draft,prefix):
    if check.code not in FIELDS:return
    from app.monthly_report_guided import _rich_text_scope
    for target in check.targets:
        if current_source(draft,st.session_state.get(prefix+'_evidence',()),target) is None:continue
        st.button('Correct site' if FIELDS[check.code]=='site' else 'Correct date',
            key=prefix+'_correct_source_'+target.source_id+'_'+check.code,
            on_click=queue_navigation,args=(prefix,target,check.code,_rich_text_scope(prefix)))
