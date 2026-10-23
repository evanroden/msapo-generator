"""Marked disposable component fixture; production editor/journal/output unchanged."""
from dataclasses import replace
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import streamlit as st
from scripts.workspace_browser_observations import require_synthetic_root

base = Path(os.environ.get("EPC_DATA_DIR", "")).resolve()
require_synthetic_root(base)
if os.environ.get("EPC_WORK_ORDER_ROW_FIXTURE") != "1":
    raise ValueError("The work-order fixture requires its explicit disposable-server flag.")
# No inputs or endpoints can select a real report or external source.
if st.query_params:
    raise ValueError("The work-order fixture accepts no report query parameters.")

from app import monthly_report_active_work as active, monthly_report_library as library, pdf_converter
from app.monthly_report_guided import _edit_content, _refresh_period_editors_after_commit
from app.monthly_report_model import BlockSpec
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_ui import _field
from scripts.qa_work_order_rows import PREFIX, RECEIPT, row_state, scenario

st.set_page_config(page_title="Synthetic work-order row QA", layout="wide")
if library._root().resolve() != (base / "monthly_reports").resolve():
    raise ValueError("The work-order fixture cannot access a non-disposable library.")
st.warning("ISOLATED SYNTHETIC TESTING — all rows invented; no real reports accessible.")
token = st.context.cookies.get("epc_device_id", "")
if not active.enabled(token):
    raise ValueError("The synthetic row fixture requires its isolated browser token.")
source_path, initial = scenario(base)
source_hash = sha256(source_path.read_bytes()).hexdigest()
loaded = active.load(token, initial.profile.contract, initial.profile.key, initial.period)
if "draft" not in st.session_state:
    st.session_state.draft = loaded.draft if loaded else initial
    st.session_state.revision = loaded.revision if loaded else 0
    st.session_state.generation = loaded.generation if loaded else ""
before = st.session_state.draft
if st.checkbox("Show synthetic table", value=True):
    block = next(block for block in before.blocks if block.key == "work_orders")
    edited = _edit_content(BlockSpec("work_orders", "rich_text"), block, None,
                          PREFIX, {}, _field, draft=before, edit_text=False)
    st.session_state.draft = replace(before, blocks=tuple(
        edited if block.key == "work_orders" else block for block in before.blocks))
draft = st.session_state.draft
if loaded is None or draft != loaded.draft:
    saved = active.save(token, draft, expected_revision=st.session_state.revision,
                        expected_generation=st.session_state.generation,
                        base_snapshot_revision=0)
    st.session_state.revision = saved.revision
    st.session_state.generation = saved.generation
_refresh_period_editors_after_commit(PREFIX)
durable = active.load(token, draft.profile.contract, draft.profile.key, draft.period)
assert durable is not None
value = {"working": row_state(draft), "durable": row_state(durable.draft),
         "revision": durable.revision, "generation": durable.generation,
         "source_unchanged": source_hash == row_state(draft)["reference"].split(":")[1]}
st.html('<span hidden ' + RECEIPT + '="' + escape(json.dumps(value), quote=True) + '"></span>')
if st.button("Generate synthetic Word and PDF"):
    raw = build_native_docx(draft, source_path, section_key="activity")
    output = base / (token + ".docx")
    output.write_bytes(raw)
    pdf_converter.OUTPUT_DIR = base
    pdf_converter.PDF_BACKEND = "libreoffice"
    pdf_path = pdf_converter.convert_to_pdf(output)
    try:
        st.session_state.package = (raw, pdf_path.read_bytes(), draft.fingerprint)
    finally:
        pdf_path.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
if "package" in st.session_state:
    word, pdf, fingerprint = st.session_state.package
    if fingerprint == draft.fingerprint:
        st.download_button("Download synthetic Word", word, "synthetic-row-restoration.docx")
        st.download_button("Download synthetic PDF", pdf, "synthetic-row-restoration.pdf")
