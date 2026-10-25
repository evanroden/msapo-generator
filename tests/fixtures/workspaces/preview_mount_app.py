"""Synthetic late-mount viewer, using the real workspace and preview surface.

Only the browser arrival of the viewer's HTML is gated. Native widgets, preview
rendering, layout, and callbacks use production code. No report or saved data.
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import fitz
import streamlit as st

from app import monthly_report_preview_view as preview_view
from app.reference_preview import render_reference
from app.workspace_layout import workspace, workspace_columns, workspace_section


@lru_cache(maxsize=2)
def delayed_component(runtime):
    source = preview_view.JS.replace('export default function(component)',
                                     'function renderPreview(component)', 1)
    source += '''
export default async function(component) {
    window.__previewMountWaiting = true;
    await (window.__previewMountGate ||= new Promise(resolve => {
        window.__releasePreviewMount = resolve;
    }));
    if (!component.parentElement.querySelector('.report-preview')) {
        // Keep the framework's stylesheet in this shadow root. Replacing the
        // whole root would test an unstyled viewer, not a delayed real one.
        const content = document.createElement('div');
        content.innerHTML = ''' + json.dumps(preview_view.HTML) + ''';
        component.parentElement.appendChild(content);
    }
    return renderPreview(component);
}
'''
    return st.components.v2.component('synthetic_late_preview', html='',
                                      css=preview_view.CSS, js=source)


preview_view._preview_component = delayed_component


@st.cache_data
def synthetic_pdf():
    with fitz.open() as document:
        document.new_page().insert_text((48, 72), 'SYNTHETIC PREVIEW MOUNT')
        return document.tobytes()


st.set_page_config(layout='wide')
st.title('Synthetic preview arrival')
with workspace('monthly', 'synthetic-preview-mount'):
    with workspace_section('monthly_cover', 'Cover'):
        st.subheader('Cover')
        editor, reference = workspace_columns('monthly_cover')
        with editor:
            st.text_input('Cover detail', key='cover_detail', value='Synthetic cover')
        with reference:
            st.caption('Synthetic source preview')
            render_reference(key='late_cover', owner_scope='synthetic-mount',
                             title='Cover', raw=synthetic_pdf(), filename='cover.pdf')
    with workspace_section('monthly_activity', 'Activity'):
        st.subheader('Activity')
        editor, reference = workspace_columns('monthly_activity')
        with editor:
            st.button('Clear Activity', key='clear_activity',
                      on_click=lambda: st.session_state.update(
                          cleared=st.session_state.get('cleared', 0) + 1))
            st.text_area('Activity notes', key='activity_notes', value='Synthetic activity')
            st.write(f'Activity clears: {st.session_state.get("cleared", 0)}')
            for index in range(8):
                st.text_input(f'Synthetic detail {index}', key=f'detail_{index}')
        with reference:
            st.caption('No document in this section')
