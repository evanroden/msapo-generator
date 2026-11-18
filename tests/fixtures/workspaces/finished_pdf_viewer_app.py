"""Disposable actual-Streamlit fixture for the current-session finished-PDF viewer.

Only synthetic PDF bytes, localhost browser traffic and isolated session state.
Not a production route, historical viewer or report-generation substitute.
"""
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import streamlit as st

st.set_page_config(page_title="Synthetic finished PDF viewer acceptance", layout="wide")
root = Path(os.environ.get("EPC_VIEWER_QA_ROOT", "/")).resolve()
if (os.environ.get("EPC_FINISHED_PDF_VIEWER_QA") != "1"
        or not (root / "synthetic-finished-pdf-only.marker").is_file()):
    st.error("The disposable synthetic browser fixture is not enabled.")
    st.stop()

# The fixture has no live report data, repository uploads or external actions.
# Its process is localhost-bound. Production helpers remain unmodified.
import pymupdf as fitz
from docx import Document
from app import monthly_report_output_ui as output_ui
from app.reference_preview import _scope_key
from app.monthly_report_preview_store import STORE


def pdf(label: str) -> bytes:
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 92), "SYNTHETIC FINISHED PDF " + label, fontsize=24)
        return doc.tobytes(garbage=3, deflate=True)


def word(label: str) -> bytes:
    document = Document()
    document.add_paragraph("SYNTHETIC FINISHED PDF " + label)
    with BytesIO() as output:
        document.save(output)
        return output.getvalue()


prefix = "finished_pdf_synthetic"
scope = "browser-session-fixture"
initial_fingerprint = "fixed-synthetic-draft"
fingerprint = st.session_state.get(prefix + "_draft_fingerprint", initial_fingerprint)

st.title("Synthetic current-session PDF viewer")
left, middle, edit_col, right, final = st.columns(5)
with left:
    first = st.button("Create PDF A")
with middle:
    no_pdf = st.button("Replace with no PDF")
with edit_col:
    edit = st.button("Edit draft")
with right:
    second = st.button("Replace with PDF B")
with final:
    reset = st.button("Start over")

if first:
    output_ui.replace_current_session_pdf_package(
        prefix, scope, SimpleNamespace(pdf=pdf("ALPHA"), pdf_name="alpha.pdf",
                                       docx=word("ALPHA"), docx_name="alpha.docx",
                                       fingerprint=fingerprint))
if no_pdf:
    output_ui.replace_current_session_pdf_package(
        prefix, scope, SimpleNamespace(pdf=None, pdf_name="none.pdf",
                                       docx=word("NO PDF"), docx_name="none.docx",
                                       fingerprint=fingerprint))
if edit:
    st.session_state[prefix + "_draft_fingerprint"] = "edited-synthetic-draft"
    fingerprint = st.session_state[prefix + "_draft_fingerprint"]
if second:
    output_ui.replace_current_session_pdf_package(
        prefix, scope, SimpleNamespace(pdf=pdf("BRAVO"), pdf_name="bravo.pdf",
                                       docx=word("BRAVO"), docx_name="bravo.docx",
                                       fingerprint=fingerprint))
if reset:
    output_ui.discard_current_session_pdf_preview(prefix, scope)
    st.session_state.pop(prefix + "_package", None)
    st.session_state.pop(prefix + "_draft_fingerprint", None)
    fingerprint = initial_fingerprint

package = st.session_state.get(prefix + "_package")
draft = SimpleNamespace(fingerprint=fingerprint, period=SimpleNamespace(label="November 2026"))
if package and package.fingerprint != fingerprint:
    # Mirror the real guided editor's fail-closed retirement on edits.
    output_ui.discard_current_session_pdf_preview(prefix, scope)
    st.session_state.pop(prefix + "_package", None)
    package = None
output_ui.outdated_output_status(prefix, scope, draft)
if package and package.pdf:
    # The exact application viewer, paired byte hashes and native downloads.
    # No shared report version or persistent finished PDF is created in QA.
    output_ui.render_output_status(package, draft, None, prefix)
    st.download_button("Download DOCX", package.docx, file_name=package.docx_name,
                       key=prefix + "_word_download", on_click="ignore")
    st.download_button("Download PDF", package.pdf,
                       file_name=package.pdf_name, mime="application/pdf",
                       key=prefix + "_download", on_click="ignore")
    output_ui.render_current_session_pdf_preview(
        package, draft, prefix, session_scope=scope)

key = _scope_key(output_ui._final_pdf_scope(prefix, scope))
owner = st.session_state.get("_workspace_reference_owners", {}).get(key)
entries = list(owner["entries"].values()) if owner else []
tickets = [entry["ticket"] for entry in entries if entry.get("ticket")]
live = sum(bool(STORE.available(owner["owner"], ticket)) for ticket in tickets)
st.caption("QA owner entries: " + str(len(entries)))
st.caption("QA live preview tickets: " + str(live))
st.caption("QA current PDF: " + (
    "absent" if package is None else "none" if not package.pdf
    else "alpha" if package.pdf_name == "alpha.pdf" else "bravo"))
st.caption("QA current draft: " + ("edited" if fingerprint != initial_fingerprint else "original"))
st.caption("QA earlier output retired: " + str(bool(
    output_ui.st.session_state.get(prefix + "_last_created_output")
    and output_ui.st.session_state[prefix + "_last_created_output"] == (scope, initial_fingerprint)
    and fingerprint != initial_fingerprint)))
