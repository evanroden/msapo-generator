"""Minimal native coverage view; no AI calls and no export admission changes."""
from dataclasses import replace
from hashlib import sha256
import streamlit as st

from app.monthly_report_extraction_coverage import (
    all_sources_summary, exclude_from_coverage, source_coverage,
)


def render_coverage(draft, contents, prefix, blocks):
    """Display a truthful all-source count and one direct source-item route."""
    from app.monthly_report_source_manager_ui import open_source_review
    from app import monthly_report_sources as sources

    known = {content.source.id: content for content in contents}
    current = replace(draft, blocks=tuple(blocks.values()))
    ledgers = []
    for source in current.sources:
        content = known.get(source.id)
        if content is not None:
            content = replace(content, source=source)
        try:
            size = sources._path(draft.profile, source.sha256, source.suffix).stat().st_size
        except (ValueError, OSError):
            size = None
        ledgers.append(source_coverage(current, source, content, byte_count=size))
    summary = all_sources_summary(ledgers)
    st.caption(f"All sources · {summary['files']} files analyzed · "
               f"{summary['useful_items_added']} exact useful items added · "
               f"{summary['issues']} issues need review · "
               f"{summary['files_limited']} files limited · "
               f"{summary['pages_unread']} pages unread")
    if not ledgers:
        return draft
    key = prefix + "_coverage_expanded"
    if st.button("Hide extraction coverage" if st.session_state.get(key) else "Review extraction coverage",
                 key=prefix + "_coverage_toggle"):
        st.session_state[key] = not st.session_state.get(key, False)
    if not st.session_state.get(key, False):
        return draft
    st.caption("A file being accepted does not establish complete understanding. "
               "AI attempt/page coverage is not yet instrumented; unknown is not zero.")
    choices = [(ledger, item) for ledger in ledgers for item in ledger.items
               if item.state in ("review", "blocked")]
    if not choices:
        st.caption("No currently visible unresolved elements. This is not proof of semantic completeness.")
        return draft
    selected = st.selectbox("Source item needing review", range(len(choices)),
        format_func=lambda number: (
            choices[number][0].filename + " · " + choices[number][1].item_id +
            " · " + choices[number][1].state),
        key=prefix + "_coverage_selected")
    ledger, item = choices[selected]
    st.caption(item.reason + (" · Destination: " + item.destination if item.destination else ""))
    st.caption(f"{ledger.pages} pages/items · {ledger.tables if ledger.tables is not None else 'unknown'} parsed tables · "
               f"{ledger.rows} rows · {ledger.images} visual candidates · "
               f"{ledger.facts} classified facts · {ledger.bytes if ledger.bytes is not None else 'unknown'} bytes")
    st.button("Open original item for review", key=prefix + "_coverage_go",
              on_click=open_source_review,
              args=(prefix, item.source_id, "page" if item.page else "site",
                    item.page if item.page else None))
    if item.state == "review":
        # A reason typed for a different item must not follow a new selection.
        item_key = sha256((item.source_id + item.item_id + item.digest).encode()).hexdigest()[:16]
        reason = st.text_input("Reason to exclude this item from completeness accounting",
                               key=prefix + "_coverage_reason_" + item_key, max_chars=300)
        if st.button("Record intentional exclusion", key=prefix + "_coverage_exclude_" + item_key):
            # Recompute against live state to prevent a stale selectbox click
            # silently excluding another item or bypassing report safeguards.
            current_item = next((entry for entry in source_coverage(
                current, next(s for s in current.sources if s.id == item.source_id),
                known.get(item.source_id)).items
                if entry.item_id == item.item_id and entry.digest == item.digest), None)
            if current_item is None:
                st.warning("The item changed. Select its current version.")
            else:
                try:
                    draft = exclude_from_coverage(current, current_item, reason, content=known.get(item.source_id))
                except ValueError as exc:
                    st.warning(str(exc))
                else:
                    st.session_state[prefix + "_period_editor_refresh"] = True
                    st.caption("Exclusion saved in this report only. Source and generation checks are unchanged.")
    return draft
