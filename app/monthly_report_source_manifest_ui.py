"""Compact operator navigation for the read-only source coverage manifest."""
import streamlit as st

from app.monthly_report_source_manifest import (
    report_manifest, report_manifest_counts,
)


def render_source_manifest_audit(draft, contents, prefix):
    """Compute the row-sized manifest only when opened; preserve native forms."""
    key = prefix + "_source_manifest_open"
    if st.button("Hide source-content coverage" if st.session_state.get(key)
                 else "Review source-content coverage", key=key + "_toggle"):
        st.session_state[key] = not st.session_state.get(key, False)
    if not st.session_state.get(key, False):
        return
    manifests = report_manifest(draft, contents)
    counts = report_manifest_counts(manifests)
    st.caption(
        f"Source coverage · {counts['sources']} originals · {counts['items']} observable elements · "
        f"{counts['extracted']} extracted · {counts['excluded']} excluded · "
        f"{counts['not_relevant']} not relevant · {counts['included']} included but unconfirmed · "
        f"{counts['blocked']} blocked · {counts['unreadable']} unreadable"
    )
    st.caption("A source upload or accepted summary is not complete page/table/visual coverage. "
               "No paid-AI page-attempt receipt is assumed. Exclusions do not bypass preflight.")
    pending = [manifest for manifest in manifests if manifest.pending]
    if not pending:
        st.caption("No parser-visible tasks remain. Uninstrumented semantic/AI recall is unknown.")
        return

    selected = st.selectbox("Original needing source-content review", range(len(pending)),
        format_func=lambda index: (
            f"{pending[index].filename} ({len(pending[index].pending)} items)"),
        key=key + "_source")
    manifest = pending[selected]
    candidates = manifest.pending
    chosen = st.selectbox("Source-content item", range(len(candidates)),
        format_func=lambda index: (
            f"{candidates[index].key} · {candidates[index].status}"),
        key=key + "_item")
    item = candidates[chosen]
    st.caption(item.reason + (f" · Report section: {item.section}" if item.section else ""))
    from app.monthly_report_source_manager_ui import open_source_review
    # CSV/XLSX table indexes are not literal PDF/Word pages.
    can_open_page = item.page is not None and item.kind in {"page", "photo"}
    st.button("Open original item for correction", key=key + "_open_item",
        on_click=open_source_review,
        args=(prefix, item.source_id, "page" if can_open_page else "site",
              item.page if can_open_page else None))
