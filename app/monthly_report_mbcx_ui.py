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
    status_scope = hashlib.sha256(repr((scope, status.references)).encode()).hexdigest()[:20]
    if status.source == "Omit" and (status.text.strip() or status.ai_paragraphs):
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
    else:
        key = field(prefix + "_mbcx_status_" + status_scope, status.text)
        choice_key = prefix + "_mbcx_sentence_chosen_" + status_scope
        current_text = st.session_state.get(key, status.text)
        if not current_text.strip():
            for column, (label, sentence) in zip(st.columns(len(STATUS_STARTERS)), STATUS_STARTERS):
                column.button(label, key=prefix + "_mbcx_starter_" + status_scope + "_" + str(STATUS_STARTERS.index((label, sentence))),
                              on_click=_choose_sentence, args=(key, sentence, choice_key))
        from app.monthly_report_native_loading import reserve_text_area
        reserve_text_area(key, 120)
        text = st.text_area("Status or findings", key=key, value=status.text, height=120,
                            help="This is the exact wording that will print when included. Leave it empty if your attached pages need no introduction.")
        chose_sentence = st.session_state.pop(choice_key, False)
        if text != status.text or chose_sentence:
            status = replace(status, source="Omit" if status.source == "Omit" else "This month",
                             text=text, reviewed_fingerprint="", client_reviewed_fingerprint="")
            if chose_sentence:
                status = replace(status, ai_written=False, ai_paragraphs=(), ai_evidence_fingerprint="", references=())
        # Bind the action to the native text just delivered in this run. A
        # button drawn before the field would retain its previous fingerprint
        # after an edit and the next click would miss the current action ID.
        status = _include_update(status, prefix, scope)
        if status.ai_written:
            if status.reviewed:
                st.caption("This wording has been checked. Its review is retained until the wording or sources change.")
            else:
                st.caption("Check this suggested wording against its sources, then use the update. Your choice is saved with this wording.")
                if st.button("Use this update", key=prefix + "_mbcx_update_review_" + status_scope + "_" + status.fingerprint,
                             disabled=status.source == "Omit"):
                    status = replace(status, reviewed_fingerprint=status.fingerprint)
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
