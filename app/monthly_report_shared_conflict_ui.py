"""Protect shared Monthly history from wholesale stale-draft adoption.

A different browser identity has its own recovery journal. Shared snapshot
conflicts therefore need their *own* ancestor and explicit three-way choices.
Adopting a merged draft does not publish it; the existing shared-save button
still performs the revision-guarded history write.
"""
from dataclasses import asdict
from hashlib import sha256

import streamlit as st

from app import monthly_report_active_work as active_work
from app import monthly_report_library as library
from app.monthly_report_active_conflict_ui import (
    _guard_report_identity, _report_identity, _reviewable_sites, _use_newer,
)
from app.monthly_report_conflict_merge import MergeBase, merge_base, merge_drafts


def _ancestor(draft, prefix):
    revision = st.session_state.get(prefix + "_revision")
    saved_rev = st.session_state.get(prefix + "_shared_base_revision")
    saved_draft = merge_base(st.session_state.get(prefix + "_shared_base"))
    if (saved_rev == revision and saved_draft is not None
            and saved_draft.profile.key == draft.profile.key
            and saved_draft.period == draft.period):
        return saved_draft
    if type(revision) is int and revision > 0:
        # Compatibility with a running editor from before this improvement:
        # recover the exact immutable published ancestor, never guess it.
        prior = library.load_snapshot_version(
            draft.profile.contract, draft.profile.key, draft.period, revision)
        return prior.draft
    return None


def _text(value):
    shown = repr(value)
    return shown if len(shown) < 240 else shown[:237] + "..."


def render_shared_merge_choice(draft, snapshot, prefix, assets, profile):
    """Continue only with an exact three-way field reconciliation.

    Returning never advances the shared revision without a scoped choice.
    A later shared version remains protected by the ordinary save_snapshot CAS.
    """
    current_revision = snapshot.revision if snapshot else 0
    if not snapshot or not _reviewable_sites(profile, draft, snapshot.draft):
        st.error("The shared version identity needs review; nothing was adopted.")
        return
    try:
        base = _ancestor(draft, prefix)
        if base is None:
            st.warning("No exact original shared draft is available for a safe comparison. "
                       "The current edits remain here; do not replace newer saved work.")
            return
        _, conflicts = merge_drafts(base, draft, snapshot.draft)
    except (library.LibraryError, OSError, ValueError) as exc:
        st.error("The shared versions could not be compared safely: " + str(exc))
        return

    pair = (draft.profile.contract, draft.profile.key, draft.period.key,
            base.fingerprint, draft.fingerprint, current_revision,
            snapshot.draft.fingerprint, _report_identity(profile))
    identity = sha256(repr(pair).encode()).hexdigest()[:24]
    decisions = {}
    if len(conflicts) > 50:
        st.error("More than 50 fields changed on both pages. No values were adopted. "
                 "Review smaller changes before continuing.")
        return
    for index, item in enumerate(conflicts):
        st.warning("Both editors changed " + item.path)
        st.caption("Newer shared version: " + _text(item.newer))
        st.caption("This browser: " + _text(item.this_page))
        decision = st.radio("Resolve " + item.path,
            ("Retain newer value", "Use this page value"),
            index=None, horizontal=True,
            key=prefix + "_shared_field_choice_" + identity + "_" + str(index))
        if decision:
            decisions[item.path] = "newer" if decision == "Retain newer value" else "this_page"

    confirmed = st.checkbox(
        "I compared the saved version and want to save my draft as the next version",
        key=prefix + "_accept_" + identity)
    st.caption("Continue combines independent fields and your explicit collision choices. "
               "It does not save a shared report; Save shared version or Create Word and PDF still does that.")
    if not st.button("Continue with my draft", key=prefix + "_accept_revision_" + identity,
                     disabled=not confirmed or len(decisions) != len(conflicts)):
        return
    try:
        merged, unresolved = merge_drafts(base, draft, snapshot.draft, decisions)
        if unresolved or merged is None:
            raise active_work.ActiveWorkConflict("Unresolved shared changes.")
        library.draft_from_dict(asdict(merged))
        head = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
        if (head is None or head.revision != snapshot.revision
                or head.draft.fingerprint != snapshot.draft.fingerprint):
            raise active_work.ActiveWorkConflict("The shared report advanced during comparison.")
        with _guard_report_identity(merged, profile) as valid_profile:
            from app.monthly_report_start import refresh_profile_identity
            merged = refresh_profile_identity(merged, valid_profile)
    except active_work.ActiveWorkConflict:
        st.error("The shared report changed again. Neither draft was replaced; review the latest version.")
        return
    except (library.LibraryError, ValueError, OSError):
        st.error("The combined draft is not valid for this report. Both existing copies were retained.")
        return

    # Retire old native editors/preview identities, otherwise their cached
    # deltas would immediately write pre-merge text over the chosen fields.
    previous_sequence = st.session_state.get(prefix + "_active_sequence", 0)
    previous_generation = st.session_state.get(prefix + "_active_generation", "")
    previous_updated = st.session_state.get(prefix + "_active_updated_at", "")
    _use_newer(prefix, active_work.ActiveWork(
        merged, previous_sequence, snapshot.revision, tuple(assets.items()),
        previous_generation, previous_updated))
    st.session_state[prefix + "_shared_base"] = MergeBase(snapshot.draft)
    st.session_state[prefix + "_shared_base_revision"] = snapshot.revision
    st.session_state[prefix + "_shared_merge_notice"] = (
        "Reconciled this draft with shared version "
        + str(snapshot.revision) + ". Save shared version when ready.")
    st.rerun()
