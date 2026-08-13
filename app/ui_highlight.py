"""Transient highlighting for fields the operator still has to fill.

Shared by both workflows. It lives in its own module because ``app.web_ui``
imports ``app.expense_ui``, so the expense workflow cannot import back from the
purchase-order page without a cycle.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import streamlit as st

# Streamlit renders a keyed widget as class "st-key-<key>", rewriting anything
# outside this set -- a space, an apostrophe -- into a hyphen. Observed directly:
# key "requester_<tok>_Rochester Regional Health" becomes class
# "st-key-requester_<tok>-Rochester-Regional-Health".
#
# Emitting the RAW key therefore produces a selector that matches nothing, and
# it fails silently: no error, no highlight. Normalising here rather than
# rejecting means a caller whose key embeds a contract name still works.
_CLASS_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_SAFE_CLASS = re.compile(r"[A-Za-z0-9_-]+")


def _class_name(widget_key: str) -> str:
    return _CLASS_UNSAFE.sub("-", widget_key)

def highlight_needed_fields(widget_keys: Iterable[str]) -> None:
    """Mark the still-empty fields the operator has to fill.

    Streamlit puts a ``st-key-<widget key>`` class on each keyed widget's
    container, which is the only supported hook for styling one specific field.
    Emitting the rule from the caller -- rather than baking it into CUSTOM_CSS --
    is what makes the highlight *transient*: the caller recomputes the key list
    from the live values on every rerun, so a field stops being highlighted on
    the run after it is filled, with no state to clear.

    Keys are filtered to the character set Streamlit puts in that class name, so
    a caller cannot inject a selector through a widget key built from operator
    input.
    """
    safe = [
        name
        for name in (_class_name(key) for key in widget_keys if key)
        if _SAFE_CLASS.fullmatch(name)
    ]
    if not safe:
        return
    selectors = ", ".join(f".st-key-{name}" for name in sorted(set(safe)))
    st.markdown(
        f"<style>{selectors} {{"
        "background:#FCFCF3;"
        "border-left:4px solid var(--enfra-yellow);"
        "border-radius:4px;"
        "padding:0.35rem 0 0.35rem 0.7rem;"
        "margin:0.25rem 0;"
        "}</style>",
        unsafe_allow_html=True,
    )
