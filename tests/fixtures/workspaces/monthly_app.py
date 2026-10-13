"""Actual Monthly guided workflow in disposable synthetic QA storage only.

Run only through scripts/qa_monthly_adaptive.py. The known-value button uses
monthly_report_qa_fixture.prepare unchanged; all editing, preview jobs, native
DOCX/PDF conversion and storage namespaces are the production implementation.
No preview/output function is replaced. Browser geometry is injected by the
harness and is never described as physical-device evidence.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import streamlit as st

st.set_page_config(page_title="Synthetic actual Monthly workspace QA", layout="wide")
base = Path(os.environ.get("EPC_DATA_DIR", "")).resolve()
marker = base / "monthly-dom-synthetic-only.marker"
if (os.environ.get("EPC_MONTHLY_DOM_FIXTURE") != "1" or not marker.is_file()
        or marker.read_text(encoding="ascii") != "synthetic-monthly-dom-v1"):
    st.error("This synthetic fixture requires the disposable harness storage root.")
    st.stop()

# This fixture has its own server process. Install one process-wide outgoing
# network guard, including worker threads, without blocking localhost Streamlit
# traffic or the real LibreOffice subprocess used by production conversion.
if not getattr(sys, "_monthly_dom_guard_installed", False):
    attempts: list[str] = []
    sys._monthly_dom_attempts = attempts

    def reject(name):
        def denied(*_args, **_kwargs):
            attempts.append(name)
            raise AssertionError("Synthetic Monthly DOM fixture blocked " + name)
        return denied

    def audit(event, args):
        if event not in {"socket.connect", "socket.getaddrinfo"}:
            return
        address = args[1] if event == "socket.connect" else args[0]
        host = address[0] if isinstance(address, tuple) else address
        if host in {"localhost", "127.0.0.1", "::1", None}:
            return
        try:
            if ipaddress.ip_address(str(host)).is_loopback:
                return
        except ValueError:
            pass
        attempts.append(event + ":non-loopback")
        raise AssertionError("Synthetic Monthly DOM fixture blocked external network")

    sys.addaudithook(audit)
    from app import monthly_report_ai, ocr, smartsheet
    monthly_report_ai.request_json = reject("external monthly reader/writer")
    ocr._ocr_request = reject("external OCR")
    smartsheet.submit_po = reject("Smartsheet submission")
    sys._monthly_dom_guard_installed = True

from app.device_identity import device_token
from app.monthly_report_testing import isolated, scope
from app.monthly_report_testing_ui import render
from app.monthly_report_ui import _field, _move

token = device_token(st.context.cookies)
# AppTest cannot provide HTTP request cookies. This explicit local-only seam is
# confined to this disposable fixture; the browser path must use the real cookie.
if not token and os.environ.get("EPC_MONTHLY_DOM_APPTEST") == "1":
    token = st.session_state.get("_monthly_dom_app_test_token", "")
if not token:
    st.error("A fresh synthetic browser cookie is required; no shared fallback exists.")
    st.stop()

from scripts.workspace_browser_observations import install_synthetic_observations, emit_snapshot
install_synthetic_observations(base)

st.title("Synthetic actual Monthly workspace QA")
with isolated(token):
    render(token, "America/New_York", _field, _move, base)
    emit_snapshot()
    st.caption("Monthly DOM isolated scope: " + str(scope()))
    st.caption("Monthly DOM blocked external attempts: " + str(len(sys._monthly_dom_attempts)))
