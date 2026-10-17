"""One marked, isolated native Training reference with no workspace/viewer."""
from dataclasses import replace
from html import escape
import os

import streamlit as st

from app.monthly_report_testing import scope
from scripts.workspace_browser_observations import require_synthetic_root


# Original87 native INPUT content widths, not the wider trigger/dropdown widths.
# The locked Multiselect input adds 4px padding on each side and has no border.
OBSERVED_INPUT_CONTENT_WIDTH = {"chromium": 358.765625, "playwright-webkit": 355.59375}
NATIVE_INPUT_HORIZONTAL_PADDING = 8
REFERENCE_FORM_READY = """input=>{
  const details=input?.closest('details');
  if(!input?.isConnected||!details?.open||typeof details.getAnimations!=='function')return false;
  const content=details.querySelector('[data-testid="stExpanderDetails"]');
  return !!content&&!content.hasAttribute('inert')&&!details.style.height&&!details.style.overflow&&
    details.scrollTop===0&&details.clientHeight>=details.scrollHeight-1&&
    details.getAnimations().every(animation=>animation.playState==='finished'||animation.playState==='idle');
}"""
REFERENCE_COLUMNS_CSS = '''<style>
  .st-key-native_training_reference_columns [data-testid="stHorizontalBlock"] {
    display:grid;grid-template-columns:minmax(0,1.12fr) minmax(0,1fr);column-gap:12px;
  }
  .st-key-native_training_reference_columns [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    width:auto;min-width:0;
  }
</style>'''


def render_reference(base, field):
    require_synthetic_root(base)
    if os.environ.get("EPC_MONTHLY_TRAINING_TASK") != "1" or scope() is None:
        raise ValueError("Native Training reference requires its isolated synthetic task.")
    from app import monthly_report_qa_fixture as fixture
    from app.monthly_report_training_ui import render_training

    key = "_native_training_reference_draft"
    if key not in st.session_state:
        # The same known-value fixture is installed only in this new cookie's
        # physical QA namespace. It is not source extraction or live history.
        st.session_state[key] = fixture.prepare("prefill")
    draft = st.session_state[key]
    st.title("Synthetic native Training reference")
    st.info("ISOLATED SYNTHETIC TESTING — not a client report. No live report, contact, capacity, logo or design records are accessible here.")
    st.caption("Diagnostic reference: the production Training editor and matrix, without a workspace or report preview. This is not report acceptance.")
    st.sidebar.caption("Synthetic native Training reference only. No client records are available.")
    # Match the observed desktop editor width using the ordinary two-column
    # ratio and 12px gutter. This fixed fixture CSS has no layout observers.
    st.html(REFERENCE_COLUMNS_CSS)
    with st.container(key="native_training_reference_columns"):
        editor, unused = st.columns([1.12, 1], gap=None)
        with editor:
            st.subheader("Training Summary")
            blocks = render_training(draft, {block.key: block for block in draft.blocks},
                                     "native_training_reference", field)
            if tuple(blocks.values()) != draft.blocks:
                st.session_state[key] = replace(draft, blocks=tuple(blocks.values()))
    st.html('<span hidden data-enfra-training-native-reference="native-editor-only" '
            'data-reference-scope="' + escape(scope(), quote=True) + '"></span>')
