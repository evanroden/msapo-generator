"""Opt-in, bounded page preview for an original monthly Scorecard PDF.

The whole-PDF action remains one click. Viewing a page never changes source
review receipts, selections, saved report pages, or the immutable original.
"""
import hashlib

import streamlit as st

from app import monthly_report_sources as sources
from app.monthly_report_source_preview import source_thumbnail_uri


def render_scorecard_pdf_preview(profile, content, *, period, key):
    source = content.source
    st.caption(
        f"Scorecard source: {source.filename} · "
        f"Source date: {source.service_date or 'not established'} · "
        f"Target report: {period.label}"
    )
    # Never carry a preview choice from an earlier report month, site group,
    # or different original. The preview is local to this UI, not a page review.
    scope = hashlib.sha256(repr((
        profile.contract, profile.key, period.key, source.sha256
    )).encode()).hexdigest()[:20]
    prefix = key + "_scorecard_preview_" + scope
    open_key = prefix + "_shown"
    if st.button("Preview a Scorecard PDF page", key=prefix + "_button"):
        st.session_state[open_key] = not st.session_state.get(open_key, False)
    if not st.session_state.get(open_key):
        return
    numbers = tuple(range(1, len(source.page_texts) + 1))
    if not numbers:
        st.warning("This PDF has no readable page inventory. Its pages were not selected.")
        return
    number = st.selectbox(
        "Scorecard PDF page", numbers, key=prefix + "_page",
        format_func=lambda page: f"Page {page} of {len(numbers)}",
    )
    try:
        image = sources.page_image(profile, content, number, preview=True)
        st.image(source_thumbnail_uri(image), width=650)
    except (OSError, ValueError) as exc:
        st.warning("This page preview could not be shown: " + str(exc))
        st.caption("Use the original PDF download or Review individual pages to inspect it.")
