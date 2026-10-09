"""Infrequent design maintenance stays outside monthly content entry."""

from dataclasses import replace
from pathlib import Path
import tempfile

import streamlit as st

from app import monthly_report_designs as designs


def render_design_settings(draft, prefix):
    st.markdown("**Master report design**")
    st.caption("Every new report starts with the ENFRA master, including reports started without an upload. Replace it here with a newer Word report to update future reports across contracts. Existing saved reports keep their design version.")
    current = designs.master_state()
    if current["revision"]:
        st.caption("Current master: version " + str(current["revision"]))
    source = st.file_uploader("New ENFRA master design", type=["docx"], max_upload_size=128,
                              key=prefix + "_native_design_upload")
    if st.button("Update master report design", key=prefix + "_native_design_save",
                 disabled=source is None or not draft.prepared_by.strip()):
        try:
            with st.spinner("Saving the original ENFRA page design…"):
                with tempfile.TemporaryDirectory(prefix="enfra-design-") as directory:
                    path = Path(directory) / "reference.docx"
                    path.write_bytes(source.getvalue())
                    digest = designs.install_master(path, actor=draft.prepared_by,
                                                    expected_revision=current["revision"])
                    profile = replace(draft.profile, template=designs.MASTER_PREFIX + digest)
                updated = replace(draft, profile=profile)
                st.session_state[prefix + "_draft"] = updated
                st.session_state.pop(prefix + "_section_preview_cache", None)
                st.session_state[prefix + "_design_saved"] = True
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    if st.session_state.pop(prefix + "_design_saved", False):
        st.success("ENFRA master design saved. New reports will use it automatically. Report content was not changed.")
    if current.get("default") and draft.profile.template != designs.MASTER_PREFIX + current["default"]:
        if st.button("Apply current master to this report", key=prefix + "_native_design_apply"):
            st.session_state[prefix + "_draft"] = replace(draft, profile=replace(draft.profile, template=designs.MASTER_PREFIX + current["default"]))
            st.session_state.pop(prefix + "_section_preview_cache", None)
            st.rerun()
