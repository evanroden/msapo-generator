"""Isolated native-browser A30 fixture. Synthetic sources only.

Uses the real guided source manager and native Streamlit forms, not injected
widget state. Never opens a client profile, reads remotely or writes production.
"""
from dataclasses import replace
from html import escape
import json
from pathlib import Path
import sys

# Streamlit puts this directory first on sys.path, where app.py is another
# fixture. Import the repository's app package, as the other fixtures do.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import pymupdf as fitz
import streamlit as st

from app.monthly_report_model import ReportDraft, ReportPeriod, SectionSpec, synthetic_profiles
from app.monthly_report_source_manager_ui import render_guided_source_manager
from app.monthly_report_sources import ingest

st.set_page_config(page_title="Synthetic A30 source mount", layout="wide")


def field(key, value):
    st.session_state.setdefault(key, value)
    return key


if "a30_fixture_report" not in st.session_state:
    profile = synthetic_profiles()[0]
    contents = []
    for index in range(50):
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((40, 80), "TEST ONLY: SYNTHETIC A30 FILE")
            page.insert_text((40, 120), "Demonstration North Facility")
            page.insert_text((40, 160), f"Synthetic one-page inspection {index:02d}")
            original = pdf.tobytes()
        content, _ = ingest(profile, f"synthetic-source-{index:02d}.pdf", original)
        contents.append(content)
    st.session_state["a30_fixture_report"] = ReportDraft(
        profile, ReportPeriod(2026, 9), "Synthetic editor",
        (SectionSpec("scorecards", "3", "Scorecards", ()),), (),
        sources=tuple(c.source for c in contents))
    st.session_state["a30_evidence"] = tuple(contents)

# Neutral fixture-only rerun exposes the old-source delivery/active-source
# handoff without reading, submitting or changing any report data.
st.button("Refresh synthetic source view", key="a30_fixture_refresh")
st.session_state["_monthly_source_detail_forms"] = {}
st.session_state["_monthly_source_details_managed"] = True
draft = st.session_state["a30_fixture_report"]
draft, blocks = render_guided_source_manager(
    draft, {block.key: block for block in draft.blocks}, "a30", field,
    lambda report, blocks, additions, specs, prefix: (report, blocks),
    lambda prefix, sources: sources,
)
draft = replace(draft, blocks=tuple(blocks.values()))
st.session_state["a30_fixture_report"] = draft
# Like the guided page, apply a manager close or source switch with the one
# post-commit refresh rerun (monthly_report_guided._refresh_period_editors_after_commit).
if st.session_state.pop("a30_period_editor_refresh", False):
    st.rerun()

# Browser-only observation; the UI never reads/writes this marker.
receipt = {
    "sources": len(draft.sources),
    "dates": {source.filename: source.service_date for source in draft.sources},
    "residents": len(st.session_state.get("a30_source_resident_forms", ())),
    "opened": bool(st.session_state.get("a30_batch_files_open", False)),
    "routes": len(st.session_state.get("a30_evidence_destination_route_values", {})),
}
st.markdown('<span data-a30-receipt="' + escape(json.dumps(receipt, sort_keys=True), quote=True) +
            '" hidden></span>', unsafe_allow_html=True)
