"""Shared template references, independent of report runs and active masters."""
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app.monthly_report_shared_templates import (
    MAX_TEMPLATE_BYTES, MAX_TEMPLATE_MIB, SharedReportTemplates,
)

_PREFIX = "_shared_template_"
_PENDING = "_shared_fixture_pending"


def _queue_upload(upload_key):
    if not st.session_state.get(_PENDING):
        st.session_state[_PENDING] = {
            "action": "template", "id": uuid4().hex, "upload_key": upload_key,
        }


def save_pending(live_storage_root, upload_key):
    upload = st.session_state.get(upload_key)
    if upload is None:
        raise ValueError("Choose a Word report template.")
    if upload.size > MAX_TEMPLATE_BYTES:
        raise ValueError(f"The report template exceeds the {MAX_TEMPLATE_MIB} MiB upload limit.")
    receipt = SharedReportTemplates(Path(live_storage_root)).upload(upload.getvalue(), upload.name)
    st.session_state[_PREFIX + "selection"] = receipt.bundle_id
    st.session_state[_PREFIX + "saved"] = True
    # Remount the uploader after success so a large upload is not retained
    # throughout later editor activity. Failed uploads remain available to retry.
    st.session_state[_PREFIX + "generation"] = st.session_state.get(_PREFIX + "generation", 0) + 1
    st.session_state.pop(upload_key, None)
    st.session_state.pop(_PREFIX + "prepared", None)


def render(live_storage_root):
    with st.expander("Shared report templates for agents"):
        st.caption(f"Store original Word templates up to {MAX_TEMPLATE_MIB} MiB for other agents to download. Templates stay unchanged and do not update the company master or any report.")
        if st.session_state.pop(_PREFIX + "saved", False):
            st.success("Report template saved. Other agents can download the unchanged original here.")
        generation = st.session_state.get(_PREFIX + "generation", 0)
        upload_key = _PREFIX + "file_" + str(generation)
        st.file_uploader("Word report template", type=["docx"],
                         max_upload_size=MAX_TEMPLATE_MIB, key=upload_key)
        st.button("Save shared report template", key=_PREFIX + "save",
                  on_click=_queue_upload, args=(upload_key,))
        shelf = SharedReportTemplates(Path(live_storage_root))
        try:
            saved = shelf.list()
        except (ValueError, OSError):
            st.error("Shared template storage needs recovery. Existing originals were retained.")
            return
        if not saved:
            st.info("No shared report template is stored yet.")
            return
        entries = {item.bundle_id: item for item in saved}
        if st.session_state.get(_PREFIX + "selection") not in entries:
            st.session_state[_PREFIX + "selection"] = next(iter(entries))
        chosen = st.selectbox(
            "Stored report template", tuple(entries), key=_PREFIX + "selection",
            format_func=lambda identity: "Report template · " + identity[:12] + " · " + entries[identity].source_files[0].filename,
        )
        receipt = entries[chosen]
        filename = receipt.source_files[0].filename
        st.caption(f"Word template · {receipt.archive_size:,} DOCX bytes · SHA-256: {receipt.archive_sha256}")
        action_scope = receipt.bundle_id + "_" + receipt.archive_sha256[:16]
        if st.button("Prepare verified template download", key=_PREFIX + "prepare_" + action_scope):
            try:
                shelf.download(receipt.bundle_id)
            except (ValueError, OSError):
                st.session_state.pop(_PREFIX + "prepared", None)
                st.error("Template verification failed; download is unavailable.")
            else:
                st.session_state[_PREFIX + "prepared"] = action_scope
        if st.session_state.get(_PREFIX + "prepared") == action_scope:
            def verified_template_bytes():
                return shelf.download(receipt.bundle_id)
            st.download_button(
                "Download unchanged report template", verified_template_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=_PREFIX + "download_" + action_scope, on_click="ignore",
            )
            st.caption("The original is verified again on download. Resetting a test preserves shared templates.")
