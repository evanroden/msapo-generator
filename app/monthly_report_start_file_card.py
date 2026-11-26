"""One truthful, display-only Starting Report card.

Source identity is read from the current inspection/explicit correction, never
inferred from the uploaded filename. Nothing here approves a site, period,
artwork object, or the contents of a report.
"""

import streamlit as st

from app.monthly_report_ui_text import literal


def render_loaded_file_card(staged, filename, analysis, target, period, *, remove_key, on_remove,
                            source_month_unconfirmed=False):
    """Display exactly the staged source and the distinct requested destination."""
    _, _, inspection = staged
    if analysis is None:
        source_site, source_month = "Not checked yet", "Not checked yet"
    else:
        source_site = ("; ".join(site.title for site in analysis.source_sites)
                       if analysis.source_sites else "Unknown — confirmation required")
        source_month = (f"{analysis.source_period[0]:04d}-{analysis.source_period[1]:02d}"
                        if analysis.source_period else "Unconfirmed — review the source period")
        if source_month_unconfirmed:
            source_month = "Unconfirmed — choose the source reporting month"
    target_sites = ("; ".join(site.title for site in target.facilities)
                    if target and target.facilities else "Select the destination sites")
    st.markdown("**Loaded file:** " + literal(filename))
    st.caption("Recognized source sites: " + literal(source_site) + " · Source month: " + literal(source_month))
    st.caption("Target sites: " + literal(target_sites) + " · Target month: " + literal(period.label))
    # The card names the file, its sites and both months. A preview of raw
    # recognized text and a reminder that sections still need review were
    # diagnostic noise here (owner review F12); each section's own review
    # still follows. Only a file with no readable cover text keeps a note,
    # because the sites above then cannot have been read from it.
    if not any(str(line).strip() for line in inspection.title_candidates):
        st.info("No readable cover text. Review the original artwork; identity is not confirmed.")
    if staged[0] is not None:
        with st.sidebar.expander("Starting report options"):
            st.caption("Clear only the pending file review. Saved reports, original files and report history stay unchanged.")
            st.button("Clear pending starting report", key=remove_key, on_click=on_remove)
