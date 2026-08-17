"""Transient highlighting for fields the operator still has to fill.

Shared by both workflows. It lives in its own module because ``app.web_ui``
imports ``app.expense_ui``, so the expense workflow cannot import back from the
purchase-order page without a cycle.

The two callers reach it differently, on purpose. ``app.web_ui`` passes ONE
static container key (``po_needs_you``), because that page already routes each
unresolved field into that container -- a field leaves the highlight by moving
out of it. ``app.expense_ui`` passes the individual field keys, because its
detail block has no resolved/unresolved split. Both are correct; do not
"unify" them.

Nothing here reads or writes state. That is what makes the mark transient, and
it is the whole design: see :func:`highlight_needed_fields`.
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
    """Rewrite a widget key the way Streamlit names its container class.

    One hyphen per unsafe CHARACTER, never collapsed: Streamlit substitutes
    one-for-one, so "LCMC - Children's" becomes "LCMC---Children-s". Collapsing
    runs would look neater and would match nothing.

    Pinned by test_widget_keys_are_normalised_the_way_streamlit_names_the_class
    specifically because the failure is silent.
    """
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

    Emits NOTHING for an empty or all-falsy key list, rather than an empty
    ``<style>`` block. Guaranteed by test_helper_emits_nothing_for_an_empty_list
    -- an empty rule set would still occupy a markdown slot, and the PO test
    asserts on the ABSENCE of a style block to prove the highlight cleared.

    Returns None and reports nothing on failure, because there is no failure it
    can detect: a selector that matches no element is valid CSS. Everything this
    function can get wrong is invisible in a green test run, which is why the
    normalisation above is pinned rather than trusted.
    """
    # Two-stage on purpose, and the second stage is not currently reachable:
    # _class_name's output already satisfies _SAFE_CLASS by construction. It is
    # the standing guarantee that no operator-typed text can escape into the
    # emitted CSS, and it only stays honest while the two patterns remain exact
    # complements. Edit one and you must edit the other.
    safe = [
        name
        for name in (_class_name(key) for key in widget_keys if key)
        if _SAFE_CLASS.fullmatch(name)
    ]
    if not safe:
        return
    # set() because the PO and expense callers can both offer a key twice in one
    # run; sorted() because a stable selector string keeps the emitted markdown
    # identical between reruns, which is what stops Streamlit re-painting the
    # block and what makes the substring assertions in the tests deterministic.
    selectors = ", ".join(f".st-key-{name}" for name in sorted(set(safe)))
    # Injected as raw HTML from the CALLER's render position rather than added
    # to web_ui.CUSTOM_CSS. That is precisely what makes the highlight
    # transient: the caller recomputes the key list from live values every
    # rerun, so nothing has to be cleared when a field is filled. Moving these
    # declarations into the static stylesheet would make the bar permanent and
    # there would be no state to turn it off.
    #
    # --enfra-yellow is defined in web_ui.CUSTOM_CSS, which is emitted earlier
    # in the same document. If that definition ever moves into a scope this
    # element is not inside, the custom property resolves to nothing and the
    # border silently disappears -- the tint stays, so the bar looks merely
    # restyled rather than broken.
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
