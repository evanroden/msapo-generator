"""Disposable source-upload fixtures and read-only production storage receipts."""
from dataclasses import replace
from hashlib import sha256
from html import escape
from io import BytesIO
import json
from pathlib import Path
from scripts.workspace_history_observations import namespace

FIRST = 'Inspected the synthetic air handler.'
SECOND = 'Repaired the synthetic second pump.'
OLD = 'July 2026: Old synthetic pump repair.'
EDITED = FIRST + '\n\n' + SECOND + '\n\nBrowser-reviewed correction.'


def make_source(directory, scenario, suffix=''):
    from docx import Document
    from app.monthly_report_model import synthetic_profiles
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    north,south=synthetic_profiles()[1].facilities
    doc=Document();doc.add_heading(north.title,0)
    doc.add_paragraph('Monthly Report '+('July 2026' if scenario=='stale' else 'September 2026'))
    if scenario=='scope':
        doc.add_page_break();doc.add_paragraph('Reference only: '+south.title+' is outside this report. '+suffix)
    doc.add_heading('2 Monthly Activity Summary',1)
    if scenario=='stale':doc.add_paragraph(OLD)
    for text in (FIRST,SECOND):doc.add_paragraph(text if scenario=='stale' else 'September 2026 '+text)
    path=directory/(scenario+suffix+'.docx');doc.save(path);return path


def render(base, token, field):
    import streamlit as st
    from app import monthly_report_testing as testing, monthly_report_library as library
    from app.monthly_report_model import synthetic_profiles, ReportPeriod
    from app.monthly_report_section_ui import render_section_setup
    testing.data_dir(base);_,identity,generation=namespace(base,token)
    selected=synthetic_profiles()[0]; period=ReportPeriod(2026,9)
    reference=replace(synthetic_profiles()[1],key='synthetic-reference-sites',title='Monthly Report')
    st.title('Synthetic import retention acceptance')
    if not any(p.key==reference.key for p in library.list_profiles(selected.contract)):
        if st.button('Prepare disposable site catalog'):
            library.save_profile(reference,expected_revision=0,actor='Synthetic Editor',confirmed=True);st.rerun()
        return
    saved=library.load_imported_draft(selected.contract,selected.key) if any(p.key==selected.key for p in library.list_profiles(selected.contract)) else None
    if saved is None:render_section_setup(selected.contract,period,'Synthetic Editor',field,identity=selected)
    else:st.success('Synthetic import saved')
    saved=library.load_imported_draft(selected.contract,selected.key) if any(p.key==selected.key for p in library.list_profiles(selected.contract)) else None
    # Observe only the currently effective epoch, not abandoned review state.
    current=st.session_state.get('monthly_source_membership_render_scope')
    epoch=current[1] if current else ''
    plans=next((v for k,v in st.session_state.items() if k.endswith('_section_plans') and epoch in k),{})
    record={'scope':identity,'generation':generation,'saved':saved is not None,
            'confirmed_source':bool(st.session_state.get('monthly_source_membership_confirmation')),
            'staged_sha256':next((v[2].sha256 for k,v in st.session_state.items() if k.endswith('_stage') and isinstance(v,tuple) and len(v)==3),''),
            'staged_texts':[t for p in plans.values() for t in p.get('texts',{}).values()]}
    if saved:
        original=library.imported_original(selected.contract,selected.key)
        record.update(saved_texts=[b.text for b in saved.blocks],sites=[f.key for f in saved.profile.facilities],
                      source_sha256=sha256(original.read_bytes()).hexdigest(),source_bytes=original.stat().st_size)
    st.html('<span hidden data-import-retention="'+escape(json.dumps(record),quote=True)+'"></span>')
