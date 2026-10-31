"""Display-only AI warning routes through the existing linked/fact editors."""
from dataclasses import asdict,replace
from hashlib import sha256
from html import escape
from uuid import uuid4
import streamlit as st
from app.monthly_report_ai_correction_targets import paragraph_target,resolve_paragraph

NOTICE='This wording or evidence changed. Your edits remain here; use the current warning.'


def queue_navigation(prefix,target,scope,source_page=False):
    from app.monthly_report_guided import _rich_text_scope
    draft=st.session_state.get(prefix+'_draft')
    for suffix in ('pending','ready','open'):
        st.session_state.pop(prefix+'_ai_correction_'+suffix,None)
    if draft is None or scope!=_rich_text_scope(prefix) or resolve_paragraph(draft,target) is None:
        st.session_state[prefix+'_ai_correction_notice']=NOTICE
        return
    block,_=resolve_paragraph(draft,target)
    registration=st.session_state.get(prefix+'_ai_linked_controls',{}).get(block.key)
    delivered=None
    if isinstance(registration,dict) and registration.get('paragraphs')==block.ai_paragraphs:
        fields=registration.get('fields',())
        if len(fields)==len(block.ai_paragraphs):
            delivered={'manual':st.session_state.get(registration['manual']),
                'paragraphs':tuple((st.session_state.get(f['text']),st.session_state.get(f['evidence'])) for f in fields)}
    st.session_state[prefix+'_ai_correction_pending']={
        'target':target,'scope':scope,'before':draft,'delivered':delivered,
        'source_page':bool(source_page),'nonce':uuid4().hex}


def renew_unchanged_target(before,current,target,delivered):
    """Only delivered edits to OTHER paragraphs may renew a display receipt."""
    from app.monthly_report_ai import clean_text
    from app.monthly_report_ai_correction_targets import ParagraphTarget
    if not isinstance(target,ParagraphTarget):
        return None
    from app.monthly_report_correction_targets import report_identity
    if before is None or report_identity(before)!=report_identity(current) or before.sources!=current.sources:
        return None
    original=resolve_paragraph(before,target)
    matches=[b for b in current.blocks if b.key==target.block_key]
    if original is None or len(matches)!=1 or not isinstance(delivered,dict):
        return None
    old,paragraph=original;new=matches[0]
    if (len(new.ai_paragraphs)!=len(old.ai_paragraphs)
            or new.ai_paragraphs[target.ordinal]!=paragraph):
        return None
    left,right=asdict(old),asdict(new)
    for key in ('text','ai_paragraphs','references','ai_evidence_fingerprint',
                'reviewed_fingerprint','client_reviewed_fingerprint'):
        left.pop(key,None);right.pop(key,None)
    if left!=right or not isinstance(delivered.get('manual'),str):
        return None
    entries=delivered.get('paragraphs',())
    if len(entries)!=len(new.ai_paragraphs):
        return None
    for current_paragraph,entry in zip(new.ai_paragraphs,entries):
        if (not isinstance(entry,tuple) or len(entry)!=2 or not isinstance(entry[0],str)
                or not isinstance(entry[1],list) or current_paragraph.text!=clean_text(entry[0])
                or current_paragraph.fact_ids!=tuple(entry[1])):
            return None
    expected='\n'.join(t for t in (delivered['manual'],'\n'.join('- '+p.text for p in new.ai_paragraphs)) if t)
    if new.text!=expected:
        return None
    renewed=paragraph_target(current,new,target.ordinal,target.reason,
        fact_id=target.fact_id,source_id=target.source_id,page=target.page)
    return renewed if resolve_paragraph(current,renewed) is not None else None


def finish_navigation(prefix,draft,scope):
    request=st.session_state.pop(prefix+'_ai_correction_pending',None)
    if request is None:
        return
    if not isinstance(request,dict) or request.get('scope')!=scope:
        st.session_state[prefix+'_ai_correction_notice']=NOTICE
        return
    target=request.get('target')
    if resolve_paragraph(draft,target) is None:
        target=renew_unchanged_target(request.get('before'),draft,target,request.get('delivered'))
    if target is None or resolve_paragraph(draft,target) is None:
        st.session_state[prefix+'_ai_correction_notice']=NOTICE
        return
    st.session_state[prefix+'_ai_correction_ready']={**request,'target':target}
    st.session_state[prefix+'_period_editor_refresh']=True


def consume_navigation(prefix,draft,scope):
    request=st.session_state.pop(prefix+'_ai_correction_ready',None)
    if request is None:
        return
    if (not isinstance(request,dict) or request.get('scope')!=scope
            or not isinstance(request.get('nonce'),str) or not request['nonce']
            or resolve_paragraph(draft,request.get('target')) is None):
        st.session_state[prefix+'_ai_correction_notice']=NOTICE
        return
    target=request['target']
    if request.get('source_page'):
        contents=st.session_state.get(prefix+'_evidence',())
        matches=[c for c in contents if c.source.id==target.source_id]
        sources=[s for s in draft.sources if s.id==target.source_id]
        if len(matches)!=1 or len(sources)!=1 or matches[0].source!=sources[0]:
            st.session_state[prefix+'_ai_correction_notice']='The exact fact source is unavailable. Restore it before reading again; saved wording is unchanged.'
            return
        st.session_state[prefix+'_ai_source']=target.source_id
        # Existing Pages-to-read selections remain wholly untouched.
    st.session_state[prefix+'_ai_correction_open']=request


def _markup(prefix,request,field_key,kind):
    target=request['target'];identity=sha256(prefix.encode()).hexdigest()[:24]
    destination='report-correction-'+sha256((prefix+'\0'+request['scope']+'\0'+target.token).encode()).hexdigest()
    return ('<span class="enfra-picture-correction" id="'+destination+'" data-report-identity="'+identity+
        '" data-field-kind="'+kind+'" data-field-key="'+escape(field_key,quote=True)+'" aria-hidden="true"></span>'+
        '<a class="enfra-page-correction-request" data-report-identity="'+identity+'" data-token="'+
        escape(request['nonce'],quote=True)+'" href="#'+destination+'" hidden></a>')


def render_paragraph_marker(prefix,draft,block,fields):
    request=st.session_state.get(prefix+'_ai_correction_open')
    if not isinstance(request,dict) or request.get('source_page'):
        return
    target=request.get('target')
    if getattr(target,'block_key',None)!=block.key:
        return
    if resolve_paragraph(draft,target) is None or not 0<=target.ordinal<len(fields):
        st.session_state.pop(prefix+'_ai_correction_open',None)
        st.session_state[prefix+'_ai_correction_notice']=NOTICE
        return
    field=fields[target.ordinal]
    key,kind=(field['text'],'textarea') if target.reason=='number' else (field['evidence'],'combobox')
    st.markdown(_markup(prefix,request,key,kind),unsafe_allow_html=True)
    st.session_state.pop(prefix+'_ai_correction_open',None)


def render_fact_page_context(prefix,draft,source,content):
    request=st.session_state.get(prefix+'_ai_correction_open')
    if not isinstance(request,dict) or not request.get('source_page'):
        return
    target=request.get('target')
    if getattr(target,'source_id',None)!=source.id:
        return
    if resolve_paragraph(draft,target) is None:
        st.session_state.pop(prefix+'_ai_correction_open',None)
        st.session_state[prefix+'_ai_correction_notice']=NOTICE
        return
    from app.monthly_report_page_context_ui import render_correction_page
    st.caption(f'The saved fact cites page {target.page}. Your reading selections are unchanged; choose any reading or fact-acceptance action explicitly.')
    render_correction_page(draft.profile,content,target.page)
    st.markdown(_markup(prefix,request,prefix+'_ai_read_pages_'+source.id,'combobox'),unsafe_allow_html=True)
    st.session_state.pop(prefix+'_ai_correction_open',None)


def render_links(check,draft,prefix):
    from app.monthly_report_guided import _rich_text_scope
    for target in check.targets:
        if resolve_paragraph(draft,target) is None:
            continue
        label=('Edit paragraph ' if target.reason=='number' else 'Review evidence for paragraph ')+str(target.ordinal+1)
        st.button(label,key=prefix+'_ai_correction_'+target.token,
                  on_click=queue_navigation,args=(prefix,target,_rich_text_scope(prefix),False))
        if target.reason=='date':
            st.button(f'Open cited source page {target.page}',key=prefix+'_ai_correction_source_'+target.token,
                      on_click=queue_navigation,args=(prefix,target,_rich_text_scope(prefix),True))
