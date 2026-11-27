"""The commissioning (MBCx) section: its report pages, and only an evidence-linked update.

The owner removed the free-text status box (25 Nov 2026). A plain note saved
earlier has no editor here; normalize_mbcx leaves it out of the report while
keeping its text in the draft.
"""

from dataclasses import replace
import hashlib

import streamlit as st


def _include_update(status, prefix, scope):
    if status.source == "Omit" and (status.text.strip() or status.ai_paragraphs):
        identity = hashlib.sha256(repr((scope, status.references)).encode()).hexdigest()[:20]
        if st.button("Include this update", key=prefix + "_mbcx_include_" + identity + "_" + status.fingerprint):
            # The linked editor and inclusion copy must refresh only after the
            # caller has committed the complete canonical draft and recovery.
            st.session_state[prefix + "_period_editor_refresh"] = True
            return replace(status, source="This month", reviewed_fingerprint="", client_reviewed_fingerprint="")
    return status


def render_mbcx(status, pages, prefix, field, edit_pages):
    """Return edited blocks; the caller supplies its shared page editor.

    The caller provides this section's file workflow before the page editor.
    """
    from app.monthly_report_guided import _rich_text_scope
    scope = _rich_text_scope(prefix)
    if status.source == "Omit" and status.ai_paragraphs:
        st.info("This saved update is currently left out.")
    if status.ai_paragraphs:
        status = _include_update(status, prefix, scope)
        # The shared source editor owns the linked paragraphs and their review.
        # Editing a second text copy here would leave those paragraphs unchanged
        # and bring their old wording back when the shared editor next runs.
        if status.source == "Omit":
            st.caption("Include this update to edit and check its wording with its supporting evidence.")
        else:
            st.caption("Edit and check this update in the wording and sources box above, where its supporting evidence is shown.")
        # The source-linked editor above is authoritative when included.
        # Excluded legacy wording remains visible before the user chooses to
        # include it, without creating another competing text editor.
        if status.source == "Omit":
            st.text(status.text)
    # The single report uploader is already rendered above. A status-only
    # MBCx report is valid and requires no second page count or upload prompt.
    if pages.text.strip() or pages.ai_paragraphs:
        # A rare legacy conflict between included and omitted notes is left
        # untouched by normalization instead of silently reviving excluded text.
        if pages.source == "Omit":
            st.info("Retained page notes are left out of this report.")
            if pages.ai_paragraphs:
                st.caption("These source-linked notes remain below for reference. Use the separate update above to change the report.")
                st.text(pages.text)
            else:
                st.caption("Edit Retained page notes (left out) below. Editing keeps them left out; use the separate update above to change the report.")
        elif pages.ai_paragraphs:
            st.caption("Edit the included page notes in their wording and sources editor above.")
        else:
            st.caption("Edit Page notes included in this report below. The separate update above keeps its own inclusion choice.")
    return status, edit_pages(pages)
