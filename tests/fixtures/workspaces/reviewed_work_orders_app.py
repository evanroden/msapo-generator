"""Disposable synthetic host for the actual source manager/review/library/output."""
from dataclasses import replace
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import streamlit as st
from scripts.workspace_browser_observations import require_synthetic_root

base = Path(os.environ.get("EPC_DATA_DIR", "")).resolve()
require_synthetic_root(base)
if os.environ.get("EPC_REVIEWED_WORK_ORDER_FIXTURE") != "1" or st.query_params:
    raise ValueError("An isolated reviewed-row fixture flag and no query parameters are required.")
token = st.context.cookies.get("epc_device_id", "")
if not re.fullmatch(r"[0-9a-f]{32}", token):
    raise ValueError("Use a fresh isolated browser identity.")

# Any accidental paid/background network path fails, including worker threads.
if not getattr(sys, "_reviewed_rows_network_guard", False):
    def guard(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            address = args[1] if event == "socket.connect" else args[0]
            host = address[0] if isinstance(address, tuple) else address
            if host not in {"127.0.0.1", "localhost", "::1", None}:
                raise AssertionError("Synthetic reviewed rows blocked external network")
    sys.addaudithook(guard)
    sys._reviewed_rows_network_guard = True

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_source_manager_ui import render_guided_source_manager
from app.monthly_report_source_recovery import restore_sources
from app.monthly_report_guided import _apply_prepared, _keep_missing_sources, _refresh_period_editors_after_commit
from app.monthly_report_ui import _field
from scripts.qa_reviewed_work_orders import CSV, state, PREFIX, RECEIPT

st.set_page_config(page_title="Synthetic reviewed work-order QA", layout="wide")
if library._root().resolve() != (base / "monthly_reports").resolve():
    raise ValueError("The fixture cannot access a non-disposable report library.")
st.warning("ISOLATED SYNTHETIC TEST — invented source rows only.")
profile = replace(synthetic_profiles()[0], key="reviewed-" + token)
period = ReportPeriod(2026, 9)
loaded = library.load_snapshot(profile.contract, profile.key, period)
if "draft" not in st.session_state:
    st.session_state.draft = loaded.draft if loaded else ReportDraft(
        profile, period, "Synthetic Editor", tuple(s for s in default_sections() if s.key in {"activity", "maintenance"}),
        (ResolvedBlock("work_orders", "Omit"), ResolvedBlock("service_calls", "Omit"),
         ResolvedBlock("activity_summary", "This month", text="Keep this manually authored synthetic note.")), synthetic=True)
    st.session_state.saved_revision = loaded.revision if loaded else 0
    if loaded and loaded.draft.sources:
        contents, failed = restore_sources(profile, loaded.draft.sources)
        st.session_state[PREFIX + "_evidence"] = contents
        st.session_state[PREFIX + "_unavailable_sources"] = failed
        st.session_state[PREFIX + "_source_details_on_resume"] = True

draft = st.session_state.draft
st.session_state["_monthly_source_details_managed"] = True
draft, blocks = render_guided_source_manager(draft, {b.key: b for b in draft.blocks}, PREFIX,
    _field, _apply_prepared, _keep_missing_sources, assets={})
draft = replace(draft, blocks=tuple(blocks.values()))
st.session_state.draft = draft
if st.button("Save synthetic report"):
    saved = library.save_snapshot(draft, expected_revision=st.session_state.saved_revision)
    st.session_state.saved_revision = saved.revision
loaded = library.load_snapshot(profile.contract, profile.key, period)
receipt = {"working": state(draft), "saved": state(loaded.draft) if loaded else None,
    "revision": loaded.revision if loaded else 0,
    "originals_unchanged": all(sources.source_bytes(profile, source) == CSV for source in draft.sources)}
st.html('<span hidden ' + RECEIPT + '="' + escape(json.dumps(receipt), quote=True) + '"></span>')
if st.button("Generate synthetic Word and PDF"):
    from app import pdf_converter
    from app.monthly_report_docx import generate_report
    pdf_converter.OUTPUT_DIR = base
    pdf_converter.PDF_BACKEND = "libreoffice"
    st.session_state.package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
package = st.session_state.get("package")
if package and package.fingerprint == draft.fingerprint:
    st.download_button("Download synthetic Word", package.docx, "synthetic-reviewed.docx")
    if package.pdf:
        st.download_button("Download synthetic PDF", package.pdf, "synthetic-reviewed.pdf")
    elif package.pdf_error:
        st.error(package.pdf_error)
_refresh_period_editors_after_commit(PREFIX)
