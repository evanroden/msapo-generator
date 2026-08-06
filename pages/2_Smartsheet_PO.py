"""Compatibility page for bookmarks created before the inline handoff.

The authoritative Smartsheet workflow now renders on the root page so mobile
Streamlit navigation cannot discard the quote or generated PDF.  This page is
deliberately non-submitting and contains no duplicate PO controls.
"""

import streamlit as st


st.set_page_config(
    page_title="Smartsheet PO handoff moved",
    page_icon="📋",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.title("Smartsheet PO handoff")
st.info(
    "The PO handoff now opens inline on the main Purchase Order Process Control "
    "page so your quote, reviewed fields, and two supporting files stay together."
)
st.page_link(
    "run_web.py",
    label="← Return to Purchase Order Process Control",
    icon="📋",
)
