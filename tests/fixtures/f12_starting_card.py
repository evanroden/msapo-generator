"""Invented display-only source card for ordinary sidebar geometry acceptance."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from types import SimpleNamespace
import streamlit as st
from app.monthly_report_start_file_card import render_loaded_file_card
from app.monthly_report_model import synthetic_profiles,ReportPeriod
st.set_page_config(page_title='Synthetic Starting Report card',layout='wide')
st.title('Synthetic Starting Report review')
st.session_state.setdefault('pending',True)
def clear(): st.session_state.pending=False
if st.session_state.pending:
    render_loaded_file_card((object(),None,SimpleNamespace(title_candidates=('Synthetic source',))),
        'invented-september-report.docx',SimpleNamespace(source_sites=synthetic_profiles()[0].facilities,source_period=(2026,9)),
        synthetic_profiles()[0],ReportPeriod(2026,11),remove_key='clear',on_remove=clear)
    st.button('Continue to reviewed updates')
else: st.info('Pending review cleared. Saved report remains unchanged.')
st.caption('Invented source only. No private reports, external reader or shared history.')
