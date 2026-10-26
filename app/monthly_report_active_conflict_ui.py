"""An explicit, current-copy-bound choice after browser recovery rejects a stale page."""
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import streamlit as st

from app import monthly_report_active_work as active_work
from app import monthly_report_library as library
from app.monthly_report_compare_ui import render_draft_comparison, render_recovery_scope, recovery_time
from app.monthly_report_start import membership_key, refresh_profile_identity


def _open(key):
    st.session_state[key] = True


def _report_identity(profile):
    # A standing inventory revision is independent of a choice between these
    # report copies. Only fields defining the reviewed report identity bind it.
    return (profile.contract, profile.key, profile.title, profile.scope_type, profile.facilities)


def _same_sites(draft, profile):
    return (profile is not None
            and (draft.profile.contract, draft.profile.key) == (profile.contract, profile.key)
            and membership_key(draft.profile.facilities) == membership_key(profile.facilities))


def _current_profile(draft):
    try:
        return library.load_profile(draft.profile.contract, draft.profile.key).profile
    except (library.LibraryError, OSError):
        st.error("The current report identity could not be read. Both copies remain available; retry when it can be loaded.")
        return None


def _reviewable_sites(profile, *drafts):
    valid = profile is not None and all(_same_sites(draft, profile) for draft in drafts if draft is not None)
    if profile is not None and not valid:
        st.error("The current report sites changed. Both copies are preserved. Return to report selection to review the sites before choosing a copy.")
    return valid


@contextmanager
def _guard_report_identity(draft, reviewed_profile):
    # Confirmed report renames and site changes use this same lock. Hold it
    # through the browser journal's own CAS; do not refresh content or design.
    with library._locked(library._profile_path(draft.profile.contract, draft.profile.key)):
        current = library.load_profile(draft.profile.contract, draft.profile.key).profile
        if (reviewed_profile is None or _report_identity(current) != _report_identity(reviewed_profile)
                or not _same_sites(draft, current)):
            raise active_work.ActiveWorkConflict()
        yield current


def _retire_replaced_save(prefix, token, draft, request):
    """A successful explicit whole-copy choice supersedes only its old receipt."""
    from app.monthly_report_recovery_save import PendingSave
    key = prefix + "_pending_browser_save"
    scope = (draft.profile.contract, draft.profile.key, draft.period.key,
             st.session_state.get(prefix + "_rich_text_epoch"),
             st.session_state.get("_monthly_qa_generation", ""))
    if (isinstance(request, PendingSave) and request.token == token and request.scope == scope
            and st.session_state.get(key) is request):
        st.session_state.pop(key, None)


def _use_newer(prefix, newer):
    # A deliberate whole-copy choice replaces this report's widgets together.
    # Keeping old widget deltas would immediately overwrite the chosen copy.
    # Retire the CURRENT finished-PDF owner before removing the old report's
    # epoch. The new browser copy may have the same site/month but new bytes;
    # otherwise an old preview fragment remains authorized after replacement.
    if st.session_state.get(prefix + "_rich_text_epoch"):
        from app.monthly_report_guided import _rich_text_scope
        from app.monthly_report_output_ui import discard_current_session_pdf_preview
        discard_current_session_pdf_preview(prefix, _rich_text_scope(prefix))
    for key in list(st.session_state):
        if key.startswith(prefix):
            del st.session_state[key]
    st.session_state["report_draft_mirror"] = {
        key: value for key, value in st.session_state.get("report_draft_mirror", {}).items()
        if not key.startswith(prefix)
    }
    st.session_state[prefix + "_draft"] = newer.draft
    st.session_state[prefix + "_rich_text_epoch"] = uuid4().hex
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
    profile = _current_profile(draft)
    same_sites = _reviewable_sites(profile, draft, snapshot.draft if snapshot else None)
    render_recovery_scope(refresh_profile_identity(draft, profile) if same_sites else draft,
                          snapshot.draft if snapshot else None,
                          label="Unfinished draft", other_label="Saved report")
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
    identity = sha256(repr((contract, selected, period.key, pair,
                           _report_identity(profile) if profile else None)).encode()).hexdigest()[:24]
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
    keep_draft = st.button("Continue with unfinished draft", key=choice_key + "_draft", disabled=not same_sites)
    use_saved = snapshot and st.button("Open saved report", key=choice_key + "_saved", disabled=not same_sites)
    if not same_sites or not (keep_draft or use_saved):
        return None
    try:
        current = active_work.load(token, contract, selected, period)
        head = library.load_snapshot(contract, selected, period)
        if (_active_identity(current), _saved_identity(head)) != pair:
            raise active_work.ActiveWorkConflict()
        chosen = draft if keep_draft else snapshot.draft
        chosen_assets = pending_assets if keep_draft else {}
        with _guard_report_identity(chosen, profile) as current_profile:
            chosen = refresh_profile_identity(chosen, current_profile)
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
    profile = _current_profile(draft)
    display_draft = refresh_profile_identity(draft, profile) if _same_sites(draft, profile) else draft
    st.caption("This page · unsaved changes · last browser save: " +
               recovery_time(st.session_state.get(prefix + "_active_updated_at")))
    if not st.session_state.get(open_key):
        render_recovery_scope(display_draft)
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

    same_sites = _reviewable_sites(profile, draft, newer.draft if newer else None)
    render_recovery_scope(display_draft, newer.draft if newer else None,
                          label="This page", other_label="Newer browser copy")
    identity = sha256(repr((contract, selected, period.key, draft.fingerprint, base_revision,
        generation, newer.revision if newer else 0,
        newer.draft.fingerprint if newer else "",
        _report_identity(profile) if profile else None)).encode()).hexdigest()[:24]
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
    if st.button("Keep this page for recovery", key=choice_key + "_keep", disabled=not same_sites) and same_sites:
        try:
            pending_save = st.session_state.get(prefix + "_pending_browser_save")
            with _guard_report_identity(draft, profile) as current_profile:
                chosen = refresh_profile_identity(draft, current_profile)
                kept = active_work.save(token, chosen,
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
            st.session_state[prefix + "_draft"] = kept.draft
            _retire_replaced_save(prefix, token, draft, pending_save)
            st.session_state.pop(open_key, None)
            st.session_state.pop(identity_key, None)
            st.rerun()
    if newer and st.button("Use the newer browser copy", key=choice_key + "_use", disabled=not same_sites) and same_sites:
        try:
            current = active_work.load(token, contract, selected, period)
            if _active_identity(current) != _active_identity(newer):
                raise active_work.ActiveWorkConflict()
            with _guard_report_identity(current.draft, profile) as current_profile:
                chosen = refresh_profile_identity(current.draft, current_profile)
                if chosen != current.draft:
                    kept = active_work.save(token, chosen,
                        expected_revision=current.revision, expected_generation=current.generation,
                        base_snapshot_revision=current.base_snapshot_revision, assets=dict(current.assets))
                    current = replace(kept, assets=current.assets)
        except active_work.ActiveWorkConflict:
            st.error("The recovery copy changed again. This page is unchanged; compare the latest copies before choosing.")
        except (library.LibraryError, OSError):
            st.error("The newer copy could not be opened. This page is unchanged; try the same action again.")
        else:
            _use_newer(prefix, current)
            st.rerun()
