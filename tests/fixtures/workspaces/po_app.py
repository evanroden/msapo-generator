"""Local-only synthetic application fixture; no live storage or external actions."""
import hashlib
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import fitz
import requests
import streamlit as st

from app import web_ui, memory, smartsheet, receipt_jobs, expense_ui

root = Path(os.environ.get("EPC_DATA_DIR", ""))
if not root.is_absolute() or not root.name.startswith("po-adaptive-synthetic-") or not root.is_dir():
    raise RuntimeError("This fixture requires its disposable local PO test directory")
if memory._data_dir().resolve() != root.resolve():
    raise RuntimeError("PO test storage was not isolated")


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
    return document("Synthetic generated MSAPO", 2)


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
