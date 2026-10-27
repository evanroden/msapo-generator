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

if (os.environ.get("EPC_MONTHLY_TRAINING_TASK") == "1"
        and st.query_params.get("training_reference") == "native"):
    from scripts.workspace_training_reference import render_reference
    with isolated(token):
        render_reference(base, _field)
    st.stop()

if os.environ.get("EPC_MONTHLY_COVER_FALLBACK_TASK") == "1":
    from scripts.workspace_cover_template_fallback import render as render_fallback
    with isolated(token):
        render_fallback(base, token, _field)
    st.stop()

if os.environ.get("EPC_MONTHLY_COVER_FIRST_TASK") == "1":
    from scripts.workspace_cover_first_display import render as render_cover_first
    with isolated(token):
        render_cover_first(base, token, _field, _move)
    st.stop()

if os.environ.get("EPC_MONTHLY_CONTACT_TASK") == "1":
    from scripts.workspace_contact_observations import render as render_contacts
    with isolated(token):
        render_contacts(base, token, _field, _move)
    st.stop()

if os.environ.get("EPC_MONTHLY_LOGO_REFRESH_TASK") == "1":
    from scripts.workspace_logo_refresh_observations import render as render_logo_refresh
    with isolated(token):
        render_logo_refresh(base, token, _field, _move)
    st.stop()

if os.environ.get("EPC_MONTHLY_LOGO_ADMIN_TASK") == "1":
    if (st.query_params.get("monthly_qa") != "logo-recovery"
            or st.query_params.get("monthly_admin") != "logos"):
        st.error("This synthetic task requires the isolated logo administration route.")
        st.stop()
    from app.monthly_report_logo_recovery_sample import sample_scope, check_sample
    from app.monthly_report_admin_ui import render_administration
    from app import monthly_report_branding as branding
    with sample_scope(token):
        render_administration("logos", _field, mode="logo-recovery")
        current = branding.load_branding()
        if current:
            _, checks = check_sample()
            st.caption("QA shared-logo revision: " + str(current.revision))
            from app.monthly_report_editor import _signature
            inspected = st.session_state.get("report_branding_preview_", "")
            st.caption("QA inspected logo: " + inspected)
            st.caption("QA logo editor: " + st.session_state.get("report_branding_actor", ""))
            st.caption("QA selected history: " + str(st.session_state.get("report_branding_history", "")))
            note_key = "report_single_logo_" + _signature((inspected, current.revision)) + "_note"
            st.caption("QA source note: " + st.session_state.get(note_key, ""))
            from scripts.workspace_logo_upload_observations import upload_observation
            import json
            st.caption("QA upload receipt: " + json.dumps(
                upload_observation(st.session_state, inspected, current.revision), sort_keys=True))
            st.caption("QA selected logo asset: " + current.logos[0].asset)
            st.caption("QA healthy logo unchanged: " + str(checks["Healthy logo and mapping unchanged"]).lower())
            unchanged = checks["Original readable history unchanged"] and checks["Damaged collection history unchanged"]
            st.caption("QA original histories unchanged: " + str(unchanged).lower())
            import json
            st.caption("QA catalog receipt: " + json.dumps({"revision": current.revision,
                "asset": current.logos[0].asset,
                "healthy": checks["Healthy logo and mapping unchanged"], "history": unchanged}, sort_keys=True))
    st.stop()

from scripts.workspace_browser_observations import install_synthetic_observations, emit_snapshot
from scripts.workspace_text_observations import emit_text_snapshot
from scripts.workspace_water_observations import emit_water_snapshot
from scripts.workspace_training_observations import emit_training_snapshot
install_synthetic_observations(base)

st.title("Synthetic actual Monthly workspace QA")
with isolated(token):
    render(token, "America/New_York", _field, _move, base)
    emit_snapshot()
    emit_text_snapshot(base, token)
    if os.environ.get("EPC_MONTHLY_TRAINING_TASK") == "1":
        emit_training_snapshot(base, token)
    if os.environ.get("EPC_MONTHLY_WATER_TASK") == "1":
        emit_water_snapshot(base, token)
    if os.environ.get("EPC_MONTHLY_HISTORY_TASK") == "1":
        from scripts.workspace_history_observations import emit_history_snapshot
        emit_history_snapshot(base, token)
    if os.environ.get("EPC_MONTHLY_PROGRESS_TASK") == "1":
        from scripts.workspace_progress_observations import emit_progress_snapshot
        emit_progress_snapshot(base, token)
    if os.environ.get("EPC_MONTHLY_ROW_TASK") == "1":
        from scripts.workspace_row_observations import emit_row_snapshot
        emit_row_snapshot(base, token)
    st.caption("Monthly DOM isolated scope: " + str(scope()))
    st.caption("Monthly DOM blocked external attempts: " + str(len(sys._monthly_dom_attempts)))
