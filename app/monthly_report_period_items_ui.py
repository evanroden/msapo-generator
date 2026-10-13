"""Small item-local period actions beside the existing authoritative editor."""
from html import escape

import streamlit as st

from app.monthly_report_period_items import (
    apply_exclusions, exclusions, item_sources, pending_items, resolve_item, restore_excluded,
)


def render_period_items(block, period, sources, prefix, *, section_title, editor_anchor):
    """Return canonical wording; caller must reconcile its existing editor mirror.

    Emit ``editor_anchor`` once immediately before that block's ordinary editor.
    Do not add a second text editor or acknowledge unrelated preflight findings.
    """
    block = apply_exclusions(block, period)
    pending = pending_items(block, period, sources)
    removed = exclusions(block, period)
    if not pending and not removed:
        return block
    st.markdown('<span id="period-items-' + escape(block.key, quote=True) + '"></span>', unsafe_allow_html=True)
    if pending:
        st.caption(section_title + " · Check these dated items for " + period.label)
    for item in pending:
        identity = prefix + "_period_item_" + block.key + "_" + block.fingerprint + "_" + str(item.index)
        with st.container(border=True):
            st.caption(f"Report text item {item.index + 1} · " + ", ".join(item.mentions))
            st.write(item.text)
            labels = item_sources(block, item, sources)
            if labels:
                st.caption("Source: " + "; ".join(labels))
            else:
                st.caption("Entered report wording; no exact linked source passage was established.")
            st.markdown("[Correct this wording or date in its editor](#" + editor_anchor + ")")
            left, right = st.columns(2)
            history = left.button("Retain as historical context", key=identity + "_history", disabled=not item.historical_allowed)
            excluded = right.button("Exclude this item from this report", key=identity + "_exclude")
            if history or excluded:
                try:
                    return resolve_item(block, period, item.index, "historical" if history else "exclude",
                                        expected_fingerprint=block.fingerprint, sources=sources)
                except ValueError as exc:
                    st.warning(str(exc))
    if removed:
        with st.expander("Excluded dated wording · " + str(len(removed))):
            for index, value in enumerate(removed):
                st.write(value["text"])
                if st.button("Restore this wording", key=prefix + "_period_restore_" + block.key + "_" + block.fingerprint + "_" + str(index)):
                    return restore_excluded(block, period, value["text"], expected_fingerprint=block.fingerprint)
    return block
