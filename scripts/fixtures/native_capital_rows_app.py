"""Disposable, source-free Capital Renewal native editor browser fixture."""
from dataclasses import replace
from html import escape
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import streamlit as st
from scripts.workspace_browser_observations import require_synthetic_root

base = Path(os.environ.get("EPC_DATA_DIR", "")).resolve()
require_synthetic_root(base)
if os.environ.get("EPC_NATIVE_CAPITAL_FIXTURE") != "1" or st.query_params:
    raise ValueError("An isolated capital fixture flag and no query parameters are required.")
identity = st.context.cookies.get("epc_device_id", "")
if not re.fullmatch(r"[0-9a-f]{32}", identity):
    raise ValueError("A fresh synthetic browser identity is required.")
if not getattr(sys, "_native_capital_network_guard", False):
    def block_external(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            address = args[1] if event == "socket.connect" else args[0]
            host = address[0] if isinstance(address, tuple) else address
            if host not in {"127.0.0.1", "localhost", "::1", None}:
                raise AssertionError("Synthetic capital fixture blocks external network")
    sys.addaudithook(block_external)
    sys._native_capital_network_guard = True

from app import monthly_report_library as library
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ReportTable, ResolvedBlock, default_sections,
    synthetic_profiles,
)
from app.monthly_report_ui import _field
st.set_page_config(page_title="Isolated native Capital row editor", layout="wide")
if library._root().resolve() != (base / "monthly_reports").resolve():
    raise ValueError("Fixture cannot read a non-disposable report library")
st.warning("DISPOSABLE SYNTHETIC DATA — native Capital row-card test")
profile = replace(synthetic_profiles()[0], key="native-capital-" + identity)
period = ReportPeriod(2026, 9)
section = next(s for s in default_sections() if s.key == "capital")
specs = tuple(replace(s, columns=(*s.columns[:-1], replace(s.columns[-1], type="date")))
              if s.key == "end_of_life" else s for s in section.blocks)
section = replace(section, blocks=specs)
original = (
    ResolvedBlock("capital_renewal", "This month",
        rows=(("Synthetic North", "High", "Inspect pump"),),
        extra_tables=(ReportTable(("Asset", "Decision", "Decision", ""),
            (("CAP-001", "[Pump](https://example.invalid) **Review**", "Pending", "Unnamed value"),
             ("CAP-002", "Second decision", "Deferred", "Second unnamed")),
            "synthetic-capital-table"),),
        references=("synthetic-capital-reference",)),
    ResolvedBlock("end_of_life", "This month",
        rows=(("Synthetic South", "FAN-001", "2030"),),
        extra_tables=(ReportTable(("Asset", "Timing", "Timing", ""),
            (("FAN-002", "2031", "Unknown", "Replacement note"),),
            "synthetic-replacement-table"),),
        references=("synthetic-replacement-reference",)),
)
existing = library.load_snapshot(profile.contract, profile.key, period)
if "draft" not in st.session_state:
    st.session_state.draft = existing.draft if existing else ReportDraft(
        profile, period, "Synthetic Editor", (section,), original, synthetic=True)
    st.session_state.revision = existing.revision if existing else 0
draft = st.session_state.draft
blocks = []
for spec in specs:
    block = next(b for b in draft.blocks if b.key == spec.key)
    with st.container(key="native_" + spec.key):
        st.subheader("Synthetic " + spec.key.replace("_", " "))
        blocks.append(_edit_content(spec, block, SimpleNamespace(profile=draft.profile),
            "native_capital_" + spec.key, {}, _field, draft))
draft = replace(draft, blocks=tuple(blocks))
st.session_state.draft = draft
if st.button("Save synthetic report"):
    saved = library.save_snapshot(draft, expected_revision=st.session_state.revision)
    st.session_state.revision = saved.revision
stored = library.load_snapshot(profile.contract, profile.key, period)
def shape(value):
    if value is None: return None
    return {b.key: {"rows": b.rows, "extra": [
        {"columns": t.columns, "rows": t.rows, "reference": t.reference}
        for t in b.extra_tables], "references": b.references} for b in value.blocks}
receipt = {"working": shape(draft), "saved": shape(stored.draft if stored else None),
           "revision": stored.revision if stored else 0}
st.html('<span hidden data-native-capital-receipt="' +
        escape(json.dumps(receipt), quote=True) + '"></span>')
if st.button("Generate synthetic Word and PDF"):
    from app import pdf_converter
    from app.monthly_report_docx import generate_report
    pdf_converter.OUTPUT_DIR = base
    pdf_converter.PDF_BACKEND = "libreoffice"
    st.session_state.package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
package = st.session_state.get("package")
if package and package.fingerprint == draft.fingerprint:
    st.download_button("Download synthetic Word", package.docx, "native-capital.docx")
    if package.pdf:
        st.download_button("Download synthetic PDF", package.pdf, "native-capital.pdf")
    elif package.pdf_error:
        st.error(package.pdf_error)
