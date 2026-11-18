"""Explicit conflict-by-field browser choice; the active journal owns the CAS."""
from dataclasses import asdict, replace
from hashlib import sha256

import streamlit as st

from app import monthly_report_active_work as active_work
from app import monthly_report_library as library
from app.monthly_report_conflict_merge import merge_base, merge_drafts


def _display(value):
    text = repr(value)
    return text if len(text) <= 200 else text[:197] + "..."


def render_merge_choice(draft, newer, token, prefix, assets, profile, identity):
    """Offer a merge only from the exact acknowledged ancestor of this page."""
    from app.monthly_report_active_conflict_ui import (
        _active_identity, _guard_report_identity, _use_newer,
    )
    base = merge_base(st.session_state.get(prefix + "_active_base"))
    base_sequence = st.session_state.get(prefix + "_active_base_revision")
    base_generation = st.session_state.get(prefix + "_active_base_generation")
    if (base is None or not isinstance(base_sequence, int)
            or base_sequence < 1 or base_sequence >= newer.revision
            or base_generation != newer.generation):
        return
    try:
        candidate, conflicts = merge_drafts(base, draft, newer.draft)
    except ValueError:
        return  # Site/period changes require the existing complete-copy review.

    with st.container(border=True):
        st.write("Combine edits from both browser pages")
        st.caption("Only fields changed independently are combined. Changes to the same field "
                   "need an explicit choice. Neither original copy changes until Save succeeds.")
        choice_key = prefix + "_merge_" + identity + "_" + sha256(
            repr((base_sequence, base.fingerprint)).encode()).hexdigest()[:12]
        decisions = {}
        for i, item in enumerate(conflicts):
            st.warning("Both pages changed " + item.path)
            st.caption("Newer browser copy: " + _display(item.newer))
            st.caption("This page: " + _display(item.this_page))
            answer = st.radio(
                "Resolve " + item.path,
                ("Retain newer value", "Use this page value"),
                index=None, key=choice_key + "_" + str(i),
                horizontal=True,
            )
            if answer:
                decisions[item.path] = "newer" if answer == "Retain newer value" else "this_page"

        ready = len(decisions) == len(conflicts)
        button = "Save resolved field choices" if conflicts else "Merge independent changes"
        if not st.button(button, key=choice_key + "_save", disabled=not ready):
            return
        try:
            result, unresolved = merge_drafts(base, draft, newer.draft, decisions)
            if unresolved or result is None:
                raise active_work.ActiveWorkConflict()
            # A legal three-way choice must still satisfy the complete saved
            # draft schema, including source-receipt integrity and size budgets.
            # Reject it before publishing any images or recovery metadata.
            library.draft_from_dict(asdict(result))
            combined_assets = dict(newer.assets)
            for name, raw in assets.items():
                if name in combined_assets and combined_assets[name] != raw:
                    raise active_work.ActiveWorkConflict()
                combined_assets[name] = raw
            current = active_work.load(token, draft.profile.contract, draft.profile.key, draft.period)
            if _active_identity(current) != _active_identity(newer):
                raise active_work.ActiveWorkConflict()
            with _guard_report_identity(result, profile) as current_profile:
                # Profile refresh may update display metadata but may not
                # redefine contract, site membership or the chosen period.
                from app.monthly_report_start import refresh_profile_identity
                result = refresh_profile_identity(result, current_profile)
                kept = active_work.save(
                    token, result, expected_revision=newer.revision,
                    expected_generation=newer.generation,
                    base_snapshot_revision=newer.base_snapshot_revision,
                    assets=combined_assets,
                )
        except active_work.ActiveWorkConflict:
            st.error("A browser version changed during this choice. Nothing was replaced; compare the new copies.")
        except (library.LibraryError, OSError):
            st.error("The resolved edits could not be saved. Both original copies remain available for retry.")
        else:
            _use_newer(prefix, replace(kept, assets=tuple(combined_assets.items())))
            st.rerun()
