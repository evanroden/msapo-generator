"""Disposable synthetic A62 Review browser fixture; never mounts client data.

The real visibility component, preview UI and private ticket store run unchanged.
Only paid/native document conversion is substituted by a deterministic PDF
containing an unvisited last-section fact and the accepted editor text.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from dataclasses import replace

import pymupdf as fitz
import streamlit as st

from app import monthly_report_review_preview_ui as review
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_preview import ReportPreview
from app.monthly_report_source_view_runtime import preview_fingerprint

st.set_page_config(page_title="A62 disposable Review", layout="wide")
if "a62_draft" not in st.session_state:
    base = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    st.session_state["a62_draft"] = replace(base, blocks=tuple(
        replace(block, text="Synthetic unvisited last-section fact.")
        if block.key == "demo_training" else block for block in base.blocks))
    st.session_state["a62_note"] = "Synthetic unvisited last-section fact."


def accept():
    value = st.session_state["a62_note"]
    draft = st.session_state["a62_draft"]
    st.session_state["a62_draft"] = replace(draft, blocks=tuple(
        replace(block, text=value) if block.key == "demo_training" else block
        for block in draft.blocks))


def synthetic_renderer(draft, loader):
    if st.session_state.get("a62_fail"):
        raise ValueError("Synthetic Review conversion temporarily unavailable.")
    text = next((block.text for block in draft.blocks if block.key == "demo_training"), "")
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Synthetic Review cover")
        pdf.new_page().insert_text((72, 72), text)
        result = ReportPreview(pdf.tobytes(), len(pdf),
                               preview_fingerprint(draft), draft.period.label)
    st.session_state["a62_last_rendered_text"] = text
    return result


# Synthetic rendering replaces only the expensive native converter inside
# this isolated app process, not the production renderer or source decisions.
review.preview_report = synthetic_renderer

st.title("A62 synthetic Review visibility")
st.text_area("QA Activity note", key="a62_note", on_change=accept)
st.checkbox("QA fail next preview", key="a62_fail")
st.markdown('<div style="height:1200px" aria-hidden="true"></div>', unsafe_allow_html=True)
st.subheader("Review and download", anchor="report-review")
draft = st.session_state["a62_draft"]
review.render_review_preview(draft, {}, "a62_fixture")
state = st.session_state.get("a62_fixture_review_draft_preview")
st.caption("QA canonical revision: " + preview_fingerprint(draft))
st.caption("QA ticket revision: " + (state.get("fingerprint", "") if isinstance(state, dict) else "none"))
st.caption("QA rendered text: " + st.session_state.get("a62_last_rendered_text", "none"))
