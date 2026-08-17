"""Compatibility page for bookmarks created before the inline handoff.

The authoritative Smartsheet workflow now renders on the root page so mobile
Streamlit navigation cannot discard the quote or generated PDF.  This page is
deliberately non-submitting and contains no duplicate PO controls.

NOT DEAD CODE, and nothing imports it. Streamlit discovers pages/ by FILENAME,
so no import edge to this file exists anywhere and a reference search finds
nothing. Deleting it turns a stale bookmark into a 404 instead of a redirect.

It must stay EMPTY of PO controls. This is not tidiness: a duplicate widget here
would write the same session_state keys the root page owns, and
tests/test_expense_draft_state.py records that entering shared state through this
page is what defeated an earlier draft-preservation fix -- the completion marker
worked on the root page and broke via this one. Anything stateful added here has
to be checked against BOTH entry paths.

tests/test_no_legacy_webhook.py and test_smartsheet_handoff_entrypoint.py pin
that the submitting/email routes live nowhere but the root page.
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
