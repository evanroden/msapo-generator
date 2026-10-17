"""An explicit, current-copy-bound choice after browser recovery rejects a stale page."""
from dataclasses import replace
from hashlib import sha256

import streamlit as st

from app import monthly_report_active_work as active_work
from app import monthly_report_library as library
from app.monthly_report_compare_ui import render_draft_comparison, render_recovery_scope, recovery_time


def _open(key):
    st.session_state[key] = True


def _use_newer(prefix, newer):
    # A deliberate whole-copy choice replaces this report's widgets together.
    # Keeping old widget deltas would immediately overwrite the chosen copy.
    for key in list(st.session_state):
        if key.startswith(prefix):
            del st.session_state[key]
    st.session_state["report_draft_mirror"] = {
        key: value for key, value in st.session_state.get("report_draft_mirror", {}).items()
        if not key.startswith(prefix)
    }
    st.session_state[prefix + "_draft"] = newer.draft
    st.session_state[prefix + "_assets"] = dict(newer.assets)
    st.session_state[prefix + "_revision"] = newer.base_snapshot_revision
    st.session_state[prefix + "_active_sequence"] = newer.revision
    st.session_state[prefix + "_active_generation"] = newer.generation
    st.session_state[prefix + "_active_updated_at"] = newer.updated_at
    st.session_state[prefix + "_directory_defaults_attempted"] = True


def _active_identity(copy):
    return (copy.generation, copy.revision, copy.draft.fingerprint, copy.base_snapshot_revision) if copy else None


def _saved_identity(copy):
    return (copy.revision, copy.draft.fingerprint) if copy else None


def render_older_draft_conflict(active, snapshot, token, prefix):
    """Choose an exact compared pair; persist only the explicit browser choice."""
    draft = active.draft
    contract, selected, period = draft.profile.contract, draft.profile.key, draft.period
    render_recovery_scope(draft)
    st.warning("This browser has an unfinished draft based on an older saved version. "
               "Review the changes before continuing.")
    st.caption(f"Unfinished draft · browser copy {active.revision} · last saved: {recovery_time(active.updated_at)}")
    st.caption(f"Saved report · version {snapshot.revision} · saved: {recovery_time(snapshot.generated_at)}"
               if snapshot else "Saved report · no saved version is currently available")
    st.caption("Prepared by: " + (draft.prepared_by or "Not recorded") +
               (" · Saved version by: " + (snapshot.entered_editor or snapshot.draft.prepared_by or "Not recorded")
                if snapshot else ""))
    open_key = prefix + "_older_draft_comparison_open"
    if not st.session_state.get(open_key):
        st.button("Review draft changes", key=prefix + "_review_older_draft",
                  on_click=_open, args=(open_key,))
        return None

    pair = (_active_identity(active), _saved_identity(snapshot))
    identity = sha256(repr((contract, selected, period.key, pair)).encode()).hexdigest()[:24]
    identity_key = prefix + "_older_draft_comparison_identity"
    previous = st.session_state.get(identity_key)
    st.session_state[identity_key] = identity
    if previous and previous != identity:
        st.info("A version changed. Review the current differences before choosing.")
    pending_assets = dict(active.assets)
    if snapshot:
        render_draft_comparison(draft, snapshot.draft,
            saved_label="Saved report", working_label="Unfinished draft",
            image_key=prefix + "_older_draft_images_" + identity,
            saved_asset_loader=lambda ref: library.read_asset(contract, selected, ref),
            working_asset_loader=lambda ref: pending_assets.get(ref) or library.read_asset(contract, selected, ref))
    st.caption("Continue with the draft keeps its unfinished changes in this browser. "
               "Open saved report replaces the browser draft with the saved report. "
               "The versions are not merged. Completed report versions, standing data and original files stay unchanged.")
    choice_key = prefix + "_older_draft_choice_" + identity
    keep_draft = st.button("Continue with unfinished draft", key=choice_key + "_draft")
    use_saved = snapshot and st.button("Open saved report", key=choice_key + "_saved")
    if not (keep_draft or use_saved):
        return None
    try:
        current = active_work.load(token, contract, selected, period)
        head = library.load_snapshot(contract, selected, period)
        if (_active_identity(current), _saved_identity(head)) != pair:
            raise active_work.ActiveWorkConflict()
        chosen = draft if keep_draft else snapshot.draft
        chosen_assets = pending_assets if keep_draft else {}
        kept = active_work.save(token, chosen, expected_revision=active.revision,
            expected_generation=active.generation, base_snapshot_revision=snapshot.revision if snapshot else 0,
            assets=chosen_assets)
    except active_work.ActiveWorkConflict:
        st.error("A version changed again. Nothing was replaced; review the latest differences before choosing.")
        return None
    except (library.LibraryError, OSError):
        st.error("Your choice could not be saved. Both versions remain available. Try the same action again.")
        return None
    st.session_state.pop(open_key, None)
    st.session_state.pop(identity_key, None)
    st.session_state[prefix + "_recovery_choice_notice"] = (
        "Your unfinished draft is saved in this browser. The completed report is unchanged."
        if keep_draft else f"Opened saved report version {snapshot.revision}. Your browser copy now matches that version.")
    return replace(kept, assets=tuple(chosen_assets.items()))


def render_browser_conflict(draft, token, prefix, assets, base_revision):
    """Never load or save a replacement until the operator reviews this exact pair."""
    open_key = prefix + "_browser_comparison_open"
    render_recovery_scope(draft)
    st.caption("This page · unsaved changes · last browser save: " +
               recovery_time(st.session_state.get(prefix + "_active_updated_at")))
    if not st.session_state.get(open_key):
        st.button("Compare browser copies", key=prefix + "_compare_browser_copies",
                  on_click=_open, args=(open_key,))
        return

    contract, selected, period = draft.profile.contract, draft.profile.key, draft.period
    try:
        newer = active_work.load(token, contract, selected, period)
        generation = newer.generation if newer else active_work.current_generation(token, contract, selected, period)
    except (library.LibraryError, OSError):
        st.error("The newer recovery copy could not be read. Your current edits remain on this page.")
        return

    identity = sha256(repr((contract, selected, period.key, draft.fingerprint, base_revision,
        generation, newer.revision if newer else 0,
        newer.draft.fingerprint if newer else "")).encode()).hexdigest()[:24]
    identity_key = prefix + "_browser_comparison_identity"
    previous = st.session_state.get(identity_key)
    st.session_state[identity_key] = identity
    if previous and previous != identity:
        st.info("A browser copy changed. Review the current differences before choosing.")
    if newer:
        recovered_assets = dict(newer.assets)
        st.caption(f"Newer browser copy {newer.revision} · saved: {recovery_time(newer.updated_at)}"
                   f" · Prepared by: {newer.draft.prepared_by or 'Not recorded'}")
        st.caption("Compare the newer browser copy on the left with this page on the right.")
        render_draft_comparison(draft, newer.draft,
            saved_label="Newer browser copy", working_label="This page",
            image_key=prefix + "_browser_comparison_images_" + identity,
            saved_asset_loader=lambda ref: recovered_assets.get(ref) or library.read_asset(contract, selected, ref),
            working_asset_loader=lambda ref: assets.get(ref) or library.read_asset(contract, selected, ref))
        st.caption("Keeping this page replaces the newer recovery copy. Using the newer copy replaces this page's edits. "
                   "Completed report versions and original files stay unchanged.")
    else:
        st.warning("The browser recovery copy was cleared. There is no newer copy to load.")
        st.caption("Keeping this page creates a new recovery copy for this report. Completed versions and original files stay unchanged.")

    choice_key = prefix + "_browser_choice_" + identity
    if st.button("Keep this page for recovery", key=choice_key + "_keep"):
        try:
            kept = active_work.save(token, draft,
                expected_revision=newer.revision if newer else 0,
                expected_generation=generation, base_snapshot_revision=base_revision, assets=assets)
        except active_work.ActiveWorkConflict:
            st.error("The recovery copy changed again. Nothing was replaced; compare the latest copies before choosing.")
        except (library.LibraryError, OSError):
            st.error("This page could not be kept for recovery. Both existing copies are unchanged; try again when saving is available.")
        else:
            st.session_state[prefix + "_active_sequence"] = kept.revision
            st.session_state[prefix + "_active_generation"] = kept.generation
            st.session_state[prefix + "_active_updated_at"] = kept.updated_at
            st.session_state.pop(open_key, None)
            st.session_state.pop(identity_key, None)
            st.rerun()
    if newer and st.button("Use the newer browser copy", key=choice_key + "_use"):
        try:
            current = active_work.load(token, contract, selected, period)
            if _active_identity(current) != _active_identity(newer):
                raise active_work.ActiveWorkConflict()
        except active_work.ActiveWorkConflict:
            st.error("The recovery copy changed again. This page is unchanged; compare the latest copies before choosing.")
        except (library.LibraryError, OSError):
            st.error("The newer copy could not be opened. This page is unchanged; try the same action again.")
        else:
            _use_newer(prefix, current)
            st.rerun()
