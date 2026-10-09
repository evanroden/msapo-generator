"""Infrequent design maintenance stays outside monthly content entry."""

from dataclasses import replace
from pathlib import Path
import tempfile

import streamlit as st

from app import monthly_report_designs as designs


def apply_master_design(draft, digest):
    """An explicit design switch adopts that version's order, keeping report data."""
    from app.monthly_report_guided import complete_guided_sections
    profile = designs.pin(replace(draft.profile, template=designs.MASTER_PREFIX + digest,
                                  section_order=()))
    return complete_guided_sections(replace(draft, profile=profile))


def render_design_settings(draft, prefix):
    st.markdown("**Master report design**")
    st.caption("Every new report starts with the ENFRA master, including reports started without an upload. Replace it here with a newer Word report to update future reports across contracts. Existing saved reports keep their design version.")
    current = designs.master_state()
    if current["revision"]:
        st.caption("Current master: version " + str(current["revision"]))
    source = st.file_uploader("New ENFRA master design", type=["docx"], max_upload_size=128,
                              key=prefix + "_native_design_upload")
    companion_pdf = st.file_uploader("Finished PDF for this design (optional)", type=["pdf"],
                                    max_upload_size=30, key=prefix + "_native_design_pdf")
    st.caption("Use the matching finished PDF as this design's layout reference.")
    if st.button("Update master report design", key=prefix + "_native_design_save",
                 disabled=source is None or not draft.prepared_by.strip()):
        try:
            with st.spinner("Saving the original ENFRA page design…"):
                with tempfile.TemporaryDirectory(prefix="enfra-design-") as directory:
                    path = Path(directory) / "reference.docx"
                    path.write_bytes(source.getvalue())
                    pdf_path = None
                    if companion_pdf is not None:
                        pdf_path = Path(directory) / "reference.pdf"
                        pdf_path.write_bytes(companion_pdf.getvalue())
                    digest = designs.install_master(path, actor=draft.prepared_by,
                                                    expected_revision=current["revision"],
                                                    companion_pdf=pdf_path)
                    updated = apply_master_design(draft, digest)
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
            st.session_state[prefix + "_draft"] = apply_master_design(draft, current["default"])
            st.session_state.pop(prefix + "_section_preview_cache", None)
            st.rerun()
