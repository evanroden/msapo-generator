"""Local-only synthetic application fixture; no live storage or external actions."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import fitz
import requests
import streamlit as st

from app import web_ui, memory, smartsheet, receipt_jobs, expense_ui, config, document_generator, pdf_converter, reference_preview
from app.document_generator import build_msapo_pdf as production_build_msapo_pdf
from app.monthly_report_preview_view import render_view as original_render_view

root = Path(os.environ.get("EPC_DATA_DIR", ""))
if not root.is_absolute() or not root.name.startswith("po-adaptive-synthetic-") or not root.is_dir():
    raise RuntimeError("This fixture requires its disposable local PO test directory")
if memory._data_dir().resolve() != root.resolve():
    raise RuntimeError("PO test storage was not isolated")

# The production PO renderer predates EPC_DATA_DIR. Confine its unchanged
# intermediate-file/cleanup behavior to this fixture's disposable directory.
render_dir = root / "renderer"
render_dir.mkdir(exist_ok=True)
for module in (config, document_generator, pdf_converter):
    module.OUTPUT_DIR = render_dir
pdf_converter.PDF_BACKEND = "libreoffice"
st.session_state["synthetic_full_app_runs"] = st.session_state.get("synthetic_full_app_runs", 0) + 1


def observed_render_view(**kwargs):
    """Acknowledge the actual fragment's received request, without business data."""
    from html import escape
    key = kwargs["key"]
    counts = st.session_state.setdefault("_fixture_preview_renders", {})
    counts[key] = counts.get(key, 0) + 1
    result = original_render_view(**kwargs)
    value = st.session_state.get(key, {})
    request = (value.get("viewport") or {}) if isinstance(value, dict) else {}
    pages = ",".join(str(page) for page in request.get("pages", ()))
    st.html(f'<span hidden data-qa-preview-ack="{escape(key)}" data-count="{counts[key]}" data-request-pages="{escape(pages)}"></span>')
    return result


reference_preview.render_view = observed_render_view


def forbidden(*args, **kwargs):
    raise RuntimeError("External reading, submission and sharing are disabled in this synthetic fixture")


def document(title, count):
    with fitz.open() as doc:
        for number in range(count):
            page = doc.new_page()
            page.insert_text((45, 55), f"{title} — page {number + 1}")
            for line in range(20):
                page.insert_text((45, 95 + line * 25), f"Invented review evidence line {line + 1}. No client data.")
        return doc.tobytes()


web_ui.analyze_quote = forbidden
web_ui.extract_text = forbidden
web_ui.ensure_device_cookie = lambda **kwargs: None
smartsheet.submit_po = forbidden
receipt_jobs.start_receipt = forbidden
expense_ui._render_ios_mail_share = forbidden
requests.sessions.Session.request = forbidden


def generated(**kwargs):
    st.session_state["synthetic_generation_count"] = st.session_state.get("synthetic_generation_count", 0) + 1
    # Call the SAME builder/template/converter as the production button. The
    # wrapper counts calls and records evidence; it never substitutes output.
    payload = production_build_msapo_pdf(**kwargs)
    with fitz.open(stream=payload, filetype="pdf") as result:
        text = "\n".join(page.get_text() for page in result)
        page_count = len(result)
    marker = kwargs["scope"].splitlines()[0]
    if "MSAPO" not in text or marker not in text:
        raise RuntimeError("The actual MSAPO PDF lost its template or reviewed synthetic scope")
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()
    (evidence / (digest + ".pdf")).write_bytes(payload)
    (evidence / (digest + ".json")).write_text(json.dumps({
        "synthetic_only": True, "builder": "app.document_generator.build_msapo_pdf",
        "template_sha256": hashlib.sha256(config.TEMPLATE_PATH.read_bytes()).hexdigest(),
        "output_sha256": digest, "pages": page_count, "reviewed_scope_present": marker in text,
        "master_text_present": "MSAPO" in text, "backend": pdf_converter.PDF_BACKEND,
    }, indent=2))
    return payload


web_ui.build_msapo_pdf = generated
if not st.session_state.get("synthetic_browser_fixture_loaded"):
    web_ui._load_test_into_state()
    raw = document("Synthetic original quote", 3)
    st.session_state["uploaded_file_bytes"] = raw
    st.session_state["uploaded_file_name"] = "Synthetic_Original_Quote.pdf"
    st.session_state["extract_hash"] = hashlib.sha256(raw).hexdigest()
    st.session_state["po_upload_available"] = True
    st.session_state["synthetic_browser_fixture_loaded"] = True
web_ui.main()
st.caption("Synthetic generation count: " + str(st.session_state.get("synthetic_generation_count", 0)))

st.caption("Synthetic full-app run count: " + str(st.session_state["synthetic_full_app_runs"]))
