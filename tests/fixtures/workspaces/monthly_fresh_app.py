"""Ordinary Monthly entry with marked disposable storage and no outgoing services.

Only scripts/qa_water_fresh_page_journey.py launches this CI fixture. The app's
normal site/design/month/upload/review actions remain authoritative. No report,
profile, widget, callback or business result is seeded by this wrapper.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import streamlit as st
from scripts.workspace_browser_observations import require_synthetic_root

base = Path(os.environ.get("EPC_DATA_DIR", "")).resolve()
require_synthetic_root(base)
if os.environ.get("EPC_MONTHLY_FRESH_TASK") != "1":
    raise ValueError("The fresh ordinary task requires its explicit disposable-server flag.")
if st.query_params.get("workflow") != "monthly" or "monthly_qa" in st.query_params:
    raise ValueError("This disposable fixture serves only the ordinary Monthly route.")

from app.memory import _data_dir
from app.monthly_report_testing import scope
if scope() is not None or _data_dir().resolve() != base:
    raise ValueError("The ordinary task must use exactly its disposable storage root.")

if not getattr(sys, "_monthly_fresh_guard_installed", False):
    sys._monthly_fresh_attempts = []

    def reject(name):
        def denied(*_args, **_kwargs):
            sys._monthly_fresh_attempts.append(name)
            raise AssertionError("Fresh synthetic Monthly blocked " + name)
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
        sys._monthly_fresh_attempts.append(event + ":non-loopback")
        raise AssertionError("Fresh synthetic Monthly blocked external network")

    sys.addaudithook(audit)
    from app import monthly_report_ai, ocr, smartsheet
    monthly_report_ai.request_json = reject("external monthly reader/writer")
    ocr._ocr_request = reject("external OCR")
    smartsheet.submit_po = reject("Smartsheet submission")
    sys._monthly_fresh_guard_installed = True

st.warning("ISOLATED SYNTHETIC TESTING — not a client report. "
           "No live report, contact, capacity, logo or design records are accessible here.")
from app.web_ui import main
main()
st.caption("Fresh Monthly blocked external attempts: " + str(len(sys._monthly_fresh_attempts)))
