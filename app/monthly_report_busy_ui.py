"""Recoverable admission feedback without accepting an unverified source."""
from functools import wraps

import streamlit as st

from app.monthly_report_render_jobs import RenderBusy


def show_busy_retry():
    from app.monthly_report_ui import preserve_report_draft_state
    preserve_report_draft_state()
    st.info("Another report is being prepared. Your edits are still here. Retry shortly.")
    st.button("Retry", key="report_capacity_retry")


def recover_render_busy(function):
    @wraps(function)
    def recover(*args, **kwargs):
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            from app.monthly_report_source_handoff import source_review_handoff
            context = get_script_run_ctx(suppress_warning=True)
            checkpoint = st.empty()
            with source_review_handoff(context.session_id if context else None, checkpoint.empty):
                # Includes saved-source reloads before section setup. This is
                # only a same-session handoff, never global admission/proof.
                return function(*args, **kwargs)
        except RenderBusy:
            show_busy_retry()
    return recover
