"""Native Prepared by defaults without one-shot-only hydration or stale mirrors."""
from uuid import uuid4

import streamlit as st


def pending_preparer(prefix, default=None, *, canonical=None):
    """Read a delivered native edit for actions rendered before the input."""
    stable = prefix + "_prepared"
    record = st.session_state.get(stable + "_editor")
    mirror = st.session_state.get("report_draft_mirror", {})
    if isinstance(record, dict):
        same_epoch = record.get("epoch") == st.session_state.get(prefix + "_rich_text_epoch", "")
        same_actor = canonical is None or canonical in (record["canonical"], record["returned"])
        if not (same_epoch and same_actor):
            # An action above the input must observe the same replacement actor
            # as the input below, rather than an old native/stable attribution.
            return canonical if canonical is not None else default
        key = record["key"]
        if key in st.session_state.get("report_widget_keys", ()) and key in st.session_state:
            return st.session_state[key]
        if key in mirror:
            return mirror[key]
    fallback = canonical if canonical is not None else default
    return st.session_state.get(stable, mirror.get(stable, fallback))


def render_preparer(prefix, canonical, field):
    """Keep attribution separate from the current native editor incarnation.

    The stable slot remains available to report-details actions and navigation
    mirrors. Only the native input owns its initialization: its protocol default
    is the exact pending text, including a deliberate clear. Replacing canonical
    attribution or returning after widget teardown retires the old native ID.
    """
    stable = prefix + "_prepared"
    metadata = stable + "_editor"
    epoch = st.session_state.get(prefix + "_rich_text_epoch", "")
    mirror = st.session_state.get("report_draft_mirror", {})
    prior = st.session_state.get(metadata)
    same_report = isinstance(prior, dict) and prior.get("epoch") == epoch
    # The last returned value may not yet have reached the canonical draft if
    # a later section yielded for capacity. Both that pending edit and its old
    # baseline are known; any other canonical actor is an external replacement.
    same_actor = same_report and canonical in (prior["canonical"], prior["returned"])
    if same_actor:
        old_key = prior["key"]
        owned = old_key in st.session_state.get("report_widget_keys", ())
        retained = mirror.get(old_key, st.session_state.get(stable, mirror.get(stable, canonical)))
        pending = st.session_state.get(old_key, retained) if owned else retained
        native_key = old_key if owned and old_key in st.session_state else stable + "_native_" + uuid4().hex
    else:
        # Initial QA/setup can seed the stable attribution slot. A replacement
        # draft/epoch instead owns its actor and must not inherit that old slot.
        pending = (st.session_state.get(stable, mirror.get(stable, canonical))
                   if prior is None else canonical)
        native_key = stable + "_native_" + uuid4().hex
    if isinstance(prior, dict) and prior["key"] != native_key:
        # Retired widget values are not recovery authority and must not
        # accumulate in the navigation mirror or its registered key list.
        retired = prior["key"]
        st.session_state["report_widget_keys"] = tuple(
            key for key in st.session_state.get("report_widget_keys", ()) if key != retired)
        st.session_state["report_draft_mirror"] = {
            key: value for key, value in mirror.items() if key != retired}
    prepared = st.text_input("Prepared by", value=pending, key=native_key,
                             help="Shown on this report; not a sign-in.")
    # Register only after native initialization; no redundant Session State seed.
    field(native_key, prepared)
    field(stable, prepared)
    st.session_state[stable] = prepared
    st.session_state[metadata] = {
        "epoch": epoch, "canonical": canonical, "returned": prepared, "key": native_key,
    }
    return prepared
