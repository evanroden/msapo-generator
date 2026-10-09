"""A section-specific update and report-pages workspace for commissioning."""

from dataclasses import replace
import hashlib

import streamlit as st


STATUS_STARTERS = (
    ("Reporting has not started", "Monitoring-based commissioning reporting has not started."),
    ("Waiting for this month's report", "The monitoring-based commissioning report for this month is pending."),
)


def _choose_sentence(text_key, sentence, choice_key):
    st.session_state[text_key] = sentence
    st.session_state[choice_key] = True


def render_mbcx(status, pages, prefix, field, edit_pages):
    """Return edited blocks; the caller supplies its shared page editor.

    The caller provides this section's file workflow before the page editor.
    """
    st.write("**System performance checks (MBCx)**")
    st.caption("Use this section for results from ongoing checks of building equipment, such as an ENFRA Connect report. Add the results you received or a short update about their availability.")
    st.write("**Update shown in the report**")
    if status.source == "Omit" and (status.text.strip() or status.ai_paragraphs):
        st.info("This saved update is currently left out.")
        if st.button("Include this update", key=prefix + "_mbcx_include_" + status.fingerprint):
            status = replace(status, source="This month", reviewed_fingerprint="", client_reviewed_fingerprint="")
    if status.ai_paragraphs:
        # The shared source editor owns the linked paragraphs and their review.
        # Editing a second text copy here would leave those paragraphs unchanged
        # and bring their old wording back when the shared editor next runs.
        if status.source == "Omit":
            st.caption("Include this update to edit and check its wording with its supporting evidence.")
        else:
            st.caption("Edit and check this update in the wording and sources box above, where its supporting evidence is shown.")
        st.text(status.text)
    else:
        stamp = hashlib.sha256(repr(status.references).encode()).hexdigest()[:12]
        key = field(prefix + "_mbcx_status_" + stamp, status.text)
        choice_key = prefix + "_mbcx_sentence_chosen"
        current_text = st.session_state.get(key, status.text)
        if not current_text.strip():
            st.caption("Write an update below, or choose a sentence only if it describes your sites. Nothing is assumed when this section is empty.")
            for column, (label, sentence) in zip(st.columns(len(STATUS_STARTERS)), STATUS_STARTERS):
                column.button(label, key=prefix + "_mbcx_starter_" + str(STATUS_STARTERS.index((label, sentence))),
                              on_click=_choose_sentence, args=(key, sentence, choice_key))
        else:
            st.caption("Keep this wording if it is still correct, or edit it here. Last month's report pages are stored separately from this update.")
        text = st.text_area("Update to include in the report", key=key, height=120,
                            help="This is the exact wording that will print when included. Leave it empty if your attached pages need no introduction.")
        chose_sentence = st.session_state.pop(choice_key, False)
        if text != status.text or chose_sentence:
            status = replace(status, source="This month", text=text, reviewed_fingerprint="", client_reviewed_fingerprint="")
            if chose_sentence:
                status = replace(status, ai_written=False, ai_paragraphs=(), ai_evidence_fingerprint="", references=())
        if status.ai_written:
            st.caption("This update contains suggested wording. Check it against its sources before using it.")
            approved = st.checkbox("I checked this update against its sources", value=status.reviewed,
                                   key=prefix + "_mbcx_update_review_" + status.fingerprint)
            status = replace(status, reviewed_fingerprint=status.fingerprint if approved else "")
    st.write("**Report pages for this month**")
    st.caption("Add a PDF or Word report using the files area in this section. Include the relevant results; previously reviewed pages stay ready.")
    if not pages.asset_hashes:
        st.caption("No report pages added. A confirmed status update can be used on its own.")
    if pages.text.strip():
        # A rare legacy conflict between included and omitted notes is left
        # untouched by normalization instead of silently reviving excluded text.
        st.warning("An earlier report has a separate update with a different inclusion choice. Check both updates in Advanced layout before changing them.")
        st.text(pages.text)
    return status, edit_pages(pages)
