"""Cookie-isolated synthetic acceptance. No seeded source/page approval.

Only empty report setup, explicit failure injection and read-only receipts are
fixture controls. Upload/review/merge uses the real ordered MBCx section.
"""
from dataclasses import asdict, replace
from hashlib import sha256
from html import escape
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def make_source(directory, vendor=False):
    import pymupdf as fitz
    from app.monthly_report_model import synthetic_profiles
    p=synthetic_profiles()[0]
    text=(f'{p.facilities[0].title}\nSeptember 2026\nENFRA MBCx commissioning report\n')
    doc=fitz.open()
    for index,tail in enumerate(('Verified equipment findings. Inspected the synthetic pump.',
                 'Client annual savings: $125.',
                 'Vendor invoice\nTotal: $450.' if vendor else 'Client annual savings: $250.')):
        page=doc.new_page();page.insert_text((40,60),text+tail)
        marker=((1,0,1),(0,1,0),(0,1,1))[index]
        page.draw_rect(fitz.Rect(40,160,90,210),fill=marker,color=marker)
    path=Path(directory)/('vendor-mixed.pdf' if vendor else 'client-mixed.pdf')
    path.parent.mkdir(parents=True,exist_ok=True);doc.save(path);doc.close();return path


def draft_component_hashes(draft):
    """Read-only synthetic diagnostics; never change the canonical digest."""
    def digest(value):
        return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    values=asdict(draft)
    result={name:digest(value) for name,value in values.items()}
    for group in ('sources','blocks'):
        for index,value in enumerate(values[group]):
            for name,field in value.items():
                result[f'{group}.{index}.{name}']=digest(field)
    return result


def render(base,token,field):
    import streamlit as st
    from app import monthly_report_library as library, monthly_report_sources as sources
    from app import monthly_report_testing as testing
    from app.monthly_report_model import synthetic_profiles,ReportDraft,ReportPeriod,SectionSpec,BlockSpec
    from app.monthly_report_guided import _render_ordered_section
    from app.monthly_report_source_recovery import restore_sources
    from scripts.workspace_history_observations import namespace
    testing.data_dir(base);target,identity,generation=namespace(base,token)
    p=synthetic_profiles()[0];period=ReportPeriod(2026,9);prefix='financial_native'
    section=SectionSpec('mbcx','4','MBCx Reports',(BlockSpec('mbcx_status','rich_text'),BlockSpec('mbcx_report','pdf_pages')))
    if 'financial_draft' not in st.session_state:
        saved=library.load_snapshot(p.contract,p.key,period)
        draft=saved.draft if saved else ReportDraft(p,period,'Synthetic Editor',(section,),())
        st.session_state.financial_draft=draft
        restored,missing=restore_sources(p,draft.sources)
        st.session_state[prefix+'_evidence']=restored
        st.session_state[prefix+'_unavailable_sources']=missing
    draft=st.session_state.financial_draft
    st.session_state.financial_render=st.session_state.get('financial_render',0)+1
    st.title('Synthetic financial-page acceptance')
    fault=st.selectbox('Synthetic failure injection',('None','Preview unavailable','Last page preparation fails'))
    real_page=sources.page_image
    def page_image(profile,content,number,**kwargs):
        if fault=='Preview unavailable' and kwargs.get('preview'):
            raise ValueError('Synthetic preview unavailable')
        if fault=='Last page preparation fails' and number==3 and not kwargs.get('preview'):
            raise ValueError('Synthetic last page preparation failure')
        return real_page(profile,content,number,**kwargs)
    # Faults only deny work; never authorize a source, page or financial amount.
    with patch.object(sources,'page_image',page_image):
        draft,blocks=_render_ordered_section(draft,draft.sections[0],{b.key:b for b in draft.blocks},
            {b.key:b for b in section.blocks},SimpleNamespace(profile=p),prefix,{},field)
    draft=replace(draft,blocks=tuple(blocks.values()));st.session_state.financial_draft=draft
    if st.button('Save synthetic draft'):
        previous=library.load_snapshot(p.contract,p.key,period)
        library.save_snapshot(draft,expected_revision=previous.revision if previous else 0)
        st.success('Synthetic draft saved')
    if st.button('Build synthetic preview and outputs'):
        from app.monthly_report_preview import section_preview_docx
        from app.monthly_report_docx import generate_report
        loader=lambda ref:library.read_asset(p.contract,p.key,ref)
        try:
            preview=section_preview_docx(draft,'mbcx',asset_loader=loader)
            package=generate_report(draft,acknowledged_fingerprint=draft.fingerprint,asset_loader=loader)
            if not package.pdf:raise ValueError(package.pdf_error or 'PDF missing')
            out=target/'financial-output';out.mkdir(exist_ok=True)
            for name,raw in (('preview.docx',preview),('report.docx',package.docx),('report.pdf',package.pdf)):
                (out/name).write_bytes(raw)
            st.session_state.financial_output={'preview':len(preview),'word':len(package.docx),'pdf':len(package.pdf),'draft':draft.fingerprint}
        except (ValueError,OSError) as exc:
            st.error(str(exc));st.session_state.financial_output={'error':str(exc)}
    from app.monthly_report_content_policy import page_allowed
    from app.monthly_report_checks import preflight
    block=blocks.get('mbcx_report')
    saved=library.load_snapshot(p.contract,p.key,period)
    record={'fault':fault,'render':st.session_state.financial_render,'scope':identity,'generation':generation,'fingerprint':draft.fingerprint,'components':draft_component_hashes(draft),
        'review_pages':next((list(v) for k,v in st.session_state.items() if k.startswith(prefix+'_evidence_section_mbcx_report_financial_') and k.endswith('_pages')),[]),
        'sources':[{'id':s.id,'sha256':s.sha256,'classification':s.classification,'facility':s.facility,'service_date':s.service_date,
            'financial_grants':[r.number for r in s.financial_page_reviews],
            'allowed':[n for n in s.selected_pages if page_allowed(s,n,profile=p,destination='mbcx_report')],
            'reviews':list(s.client_page_reviews)} for s in draft.sources],
        'assets':list(block.asset_hashes) if block else [],'occurrences':[i.key for i in block.asset_instances] if block else [],
        'captions':list(block.asset_captions) if block else [],
        'checks':[c.code for c in preflight(draft) if c.blocking],
        'saved':saved.draft.fingerprint if saved else None,
        'output':st.session_state.get('financial_output',{})}
    st.html('<span hidden data-financial-pages="'+escape(json.dumps(record),quote=True)+'"></span>')
