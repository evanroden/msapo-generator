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


def design_summary(draft):
    """Read-only version detail; the current report stays on its own pin."""
    current = designs.master_state()
    pin = draft.profile.template
    if pin.startswith(designs.BUILTIN_PREFIX):
        identity = "Built-in report design"
    elif pin.startswith(designs.MASTER_PREFIX):
        identity = "ENFRA master · " + pin[len(designs.MASTER_PREFIX):][:12]
    elif pin.startswith(designs.PREFIX):
        identity = "Report-specific design · " + pin[len(designs.PREFIX):][:12]
    else:
        identity = "Legacy report design · " + pin[:40]
    return identity, current["revision"]


def render_design_status(draft):
    identity, latest = design_summary(draft)
    st.caption("This report uses: " + identity)
    st.caption("Available company master: version " + str(latest) +
               ". Other designs cannot silently change this report.")
    st.caption("Master installation is on the separate Administration page.")


def render_design_settings(actor, prefix):
    st.markdown("**Master report design**")
    st.caption("Every new report starts with the ENFRA master, including reports started without an upload. Replace it here with a newer Word report to update future reports across contracts. Existing saved reports keep their design version.")
    st.caption("Report copies use the final accepted text and omit Word comments. Uploaded originals remain unchanged.")
    current = designs.master_state()
    base_key = prefix + "_native_design_base_revision"
    base_revision = st.session_state.setdefault(base_key, current["revision"])
    if current["revision"]:
        st.caption("Current master: version " + str(current["revision"]))
    source = st.file_uploader("New ENFRA master design", type=["docx"], max_upload_size=128,
                              key=prefix + "_native_design_upload")
    companion_pdf = st.file_uploader("Finished PDF for this design (optional)", type=["pdf"],
                                    max_upload_size=30, key=prefix + "_native_design_pdf")
    st.caption("Use the matching finished PDF as this design's layout reference.")
    conflict = base_revision != current["revision"]
    if conflict:
        st.warning(f"The master changed from version {base_revision} to version {current['revision']} while this page was open. No file was installed.")
        history = current.get("history", ())
        comparison = []
        for label, revision in (("Opened", base_revision), ("Current", current["revision"])):
            entry = history[revision - 1] if 0 < revision <= len(history) else {}
            comparison.append({"Master": label, "Version": str(revision) if revision else "Not installed",
                               "Entered editor": entry.get("actor", "Not recorded"),
                               "Saved": entry.get("at", "Not recorded")})
        st.table(comparison)
        if source is not None or companion_pdf is not None:
            st.caption("Your selected files are retained. Continuing only updates the comparison base; Update master report design installs them afterward.")
        if st.button(f"Continue from master version {current['revision']}",
                     key=prefix + f"_native_design_accept_{base_revision}_{current['revision']}",
                     disabled=not actor.strip()):
            st.session_state[base_key] = current["revision"]
            st.rerun()
    can_install = source is not None and bool(actor.strip()) and not conflict
    install_requested = st.button("Update master report design", key=prefix + "_native_design_save",
                                  disabled=not can_install)
    if install_requested and can_install:
        try:
            with st.spinner("Saving the original ENFRA page design…"):
                with tempfile.TemporaryDirectory(prefix="enfra-design-") as directory:
                    path = Path(directory) / "reference.docx"
                    path.write_bytes(source.getvalue())
                    pdf_path = None
                    if companion_pdf is not None:
                        pdf_path = Path(directory) / "reference.pdf"
                        pdf_path.write_bytes(companion_pdf.getvalue())
                    digest = designs.install_master(path, actor=actor,
                                                    expected_revision=base_revision,
                                                    companion_pdf=pdf_path)
                st.session_state[prefix + "_design_saved"] = digest
                # This request completed. A fresh render establishes a new
                # displayed base; failed/conflicted requests keep the old one.
                st.session_state.pop(base_key, None)
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    if st.session_state.pop(prefix + "_design_saved", False):
        st.success("ENFRA master installed for new reports. Existing drafts and saved report versions keep their pinned design.")


def render_apply_master_design(draft, prefix):
    """An explicit report-local choice, separate from global installation."""
    current = designs.master_state()
    if current.get("default") and draft.profile.template != designs.MASTER_PREFIX + current["default"]:
        st.caption("Apply the current master layout and section order to this draft. Monthly content and saved versions are retained; the shared master is unchanged.")
        if st.button("Apply current master to this report", key=prefix + "_native_design_apply"):
            st.session_state[prefix + "_draft"] = apply_master_design(draft, current["default"])
            st.session_state.pop(prefix + "_section_preview_cache", None)
            st.rerun()
