"""Ephemeral synthetic app exercising the ordinary guided Training section."""
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import streamlit as st

if os.environ.get("EPC_TRAINING_SOURCE_QA") != "1":
    st.error("This synthetic acceptance fixture must run in its isolated harness.")
    st.stop()

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_guided import _render_ordered_section
from app.monthly_report_model import (Facility, ReportProfile, ReportPeriod, ReportDraft,
    ResolvedBlock, SectionSpec, BlockSpec)
from app.monthly_report_source_scope import correct_scope
from app.monthly_report_docx import generate_report

case = st.query_params.get("case", "chromium")
if case not in ("chromium", "webkit"):
    st.stop()
profile = ReportProfile("Synthetic Training Browser", case, "Synthetic North",
                        (Facility("north", "Synthetic North"),))
period = ReportPeriod(2026, 9)
if "draft" not in st.session_state:
    snapshot = library.load_snapshot(profile.contract, profile.key, period)
    if snapshot:
        st.session_state['draft'] = snapshot.draft
        st.session_state['revision'] = snapshot.revision
    else:
        raw = b"Topic,Date,Method,Participants,Hours,Status\nSynthetic drill,2026-09-12,Virtual,Alice,0,Completed\n"
        content, _ = sources.ingest(profile, "synthetic-training.csv", raw)
        source = correct_scope(content.source, profile, ("north",))
        section = SectionSpec("training", "12", "Training Summary", (BlockSpec("training_summary", "rich_text"),))
        st.session_state['draft'] = ReportDraft(profile, period, "Synthetic Editor", (section,),
            (ResolvedBlock("training_summary", "This month", text="Synthetic manual note"),), sources=(source,), synthetic=True)
        st.session_state['revision'] = 0


def field(key, value):
    st.session_state.setdefault(key, value)
    return key


draft = st.session_state['draft']
section = draft.sections[0]
draft, blocks = _render_ordered_section(draft, section, {b.key:b for b in draft.blocks},
    {s.key:s for s in section.blocks}, None, 'training-browser', {}, field)
draft = replace(draft, blocks=tuple(blocks.values()))
st.session_state['draft'] = draft
if st.button("Save synthetic shared version"):
    snapshot = library.save_snapshot(draft, expected_revision=st.session_state['revision'], entered_editor=draft.prepared_by)
    st.session_state['revision'] = snapshot.revision
    st.success("Synthetic version saved")
if st.button("Generate synthetic Training output"):
    result = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
    if result.pdf_error:
        st.error(result.pdf_error)
    st.session_state['output'] = result
result = st.session_state.get('output')
if result:
    st.download_button("Download synthetic Word", result.docx, file_name=result.docx_name)
    if result.pdf:
        st.download_button("Download synthetic PDF", result.pdf, file_name=result.pdf_name)
receipt = {"synthetic": True, "fingerprint": draft.fingerprint, "saved_revision": st.session_state['revision'],
    "reviews": len(draft.source_row_reviews), "notes": draft.blocks[0].text,
    "review_revision": sha256("\n".join(draft.source_row_reviews).encode()).hexdigest(),
    "tables": [{"reference": t.reference, "columns": t.columns, "rows": t.rows} for t in draft.blocks[0].extra_tables]}
st.caption("QA Training review receipt: " + json.dumps(receipt, sort_keys=True, separators=(",", ":")))
