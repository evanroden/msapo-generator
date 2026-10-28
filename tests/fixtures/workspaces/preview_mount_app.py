"""Synthetic late-mount viewer, using the real workspace and preview surface.

The viewer HTML or the layout adapter and its CSS can arrive late. Native
widgets, rendering and callbacks use production code. No report or saved data.
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import fitz
import streamlit as st

from app import monthly_report_preview_view as preview_view
from app import workspace_layout
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


@lru_cache(maxsize=2)
def delayed_adapter(runtime):
    assets = Path(workspace_layout.__file__).parent
    source = '\n'.join((assets / name).read_text() for name in
                       ('workspace_geometry.js', 'monthly_report_source_navigation.js',
                        'workspace_navigation.js', 'workspace_layout.js'))
    source = source.replace('export default function(component)',
                            'function renderWorkspace(component)', 1)
    source += '''
export default async function(component) {
    if (component.data.syntheticDelayAdapter) {
        window.__workspaceMountWaiting = true;
        await (window.__workspaceMountGate ||= new Promise(resolve => {
            window.__releaseWorkspaceMount = resolve;
        }));
    }
    if (!document.querySelector('#synthetic-workspace-style')) {
        const style = document.createElement('style');
        style.id = 'synthetic-workspace-style';
        style.textContent = ''' + json.dumps((assets / 'workspace_layout.css').read_text()) + ''';
        document.head.appendChild(style);
    }
    const cleanup = renderWorkspace(component);
    window.__workspaceMountReleased = true;
    return cleanup;
}
'''
    return st.components.v2.component('synthetic_late_workspace', js=source,
                                      isolate_styles=False)


def fixture_adapter(runtime):
    registered = delayed_adapter(runtime)

    def render(*, data, **kwargs):
        # Carry the selected ordering per browser session. Do not leave a
        # process-global variant behind for the next browser's preview case.
        return registered(data={**data, 'syntheticDelayAdapter':
                                st.query_params.get('delay_adapter') == '1'}, **kwargs)

    return render


workspace_layout._adapter = fixture_adapter


@st.cache_data
def synthetic_pdf():
    with fitz.open() as document:
        document.new_page().insert_text((48, 72), 'SYNTHETIC PREVIEW MOUNT')
        return document.tobytes()


st.set_page_config(layout='wide')
st.title('Synthetic preview arrival')
with workspace('monthly', 'synthetic-preview-mount', navigation_key='monthly_report_navigation'):
    with st.container(key='monthly_report_navigation'):
        st.markdown('<span class="epc-section-navigation"><label for="monthly-section-choice">Section</label>'
                    '<select id="monthly-section-choice" class="epc-section-selector" aria-label="Jump to section" disabled>'
                    '<option>Loading sections…</option></select>'
                    '<button type="button" class="epc-review-shortcut" disabled>Review</button></span>', unsafe_allow_html=True)
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

# The reported adapter race also moved a native action below the workspace.
st.button('Render synthetic outputs', key='render_outputs',
          on_click=lambda: st.session_state.update(
              rendered=st.session_state.get('rendered', 0) + 1))
st.write(f'Output renders: {st.session_state.get("rendered", 0)}')
