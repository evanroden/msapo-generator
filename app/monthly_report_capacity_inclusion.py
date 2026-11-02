"""Report-only capacity inclusion; omitted values remain in the draft."""
from dataclasses import replace


def capacity_inclusion(block, included):
    if included == (block.source != "Omit"):
        return block
    return replace(block, source="This month" if included else "Omit",
                   pending_library_save=False, reviewed_fingerprint="",
                   client_reviewed_fingerprint="")


def inclusion_control(block, prefix, field):
    import streamlit as st
    return st.checkbox("Include thermal capacity", key=field(
        prefix + "_capacity_included", block.source != "Omit"),
        help="Applies to this report. Excluded values are kept for re-enabling.")
