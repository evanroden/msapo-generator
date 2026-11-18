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
    st.caption("File read; report sections and artwork still require their ordinary review.")
    with st.expander("Preview recognized content", expanded=False):
        st.caption("Text found in the Word file; this is not a rendered page or artwork approval.")
        headings = tuple(str(line).strip()[:180] for line in inspection.title_candidates if str(line).strip())
        if headings:
            for heading in headings[:5]:
                st.text(heading)
        else:
            st.info("No readable cover text. Review the original artwork; identity is not confirmed.")
    if staged[0] is not None:
        st.button("Remove loaded file", key=remove_key, on_click=on_remove)
    else:
        st.caption("Saved original — closing this review does not delete the original.")
