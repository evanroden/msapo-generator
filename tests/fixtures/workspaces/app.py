"""Synthetic real Streamlit DOM fixture. No reading, saves or business exports."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import streamlit as st
from app.workspace_layout import workspace, workspace_section, workspace_columns
from app.monthly_report_preview_view import render_view

st.set_page_config(layout="wide")
st.markdown('<style>.block-container{max-width:1000px !important;padding-top:1rem}header{visibility:hidden}</style>',unsafe_allow_html=True)
st.title('Synthetic adaptive workspace')
with workspace('monthly', 'synthetic-report-a', navigation_key='monthly_report_navigation'):
    with st.container(key='monthly_report_navigation'):
        st.markdown('[Activity](#activity) · [Scorecards](#scorecards) · [Short](#short)')
    st.markdown('<style>.st-key-monthly_report_navigation{position:sticky;top:0;z-index:10;background:white}</style>',unsafe_allow_html=True)
    for section in ('activity','scorecards','short'):
        with workspace_section('monthly_'+section,section.title()):
            st.subheader(section.title(),anchor=section)
            editor, preview = workspace_columns('monthly_'+section)
            with editor:
                st.text_area('Work summary '+section, key='text_'+section, value='Synthetic '+section, height=120)
                for index in range(12 if section != 'short' else 1):
                    st.text_input(f'{section} detail {index}',key=section+str(index))
            with preview:
                st.caption('Actual synthetic preview surface')
                render_view(key='preview_'+section,generation='synthetic-v1',title=section.title(),on_change=lambda:None)
