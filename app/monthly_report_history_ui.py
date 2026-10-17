"""Read-only shared versions, separate from the operator's browser draft."""

from datetime import datetime, timezone
from html import escape
from hashlib import sha256

import streamlit as st

from app import monthly_report_library as library


def _saved_at(value):
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is not None:
            return moment.astimezone(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")
    except (TypeError, ValueError):
        pass
    return value or "Date not recorded"


def render_snapshot_history(draft, prefix, assets, snapshot):
    """Inspect actual immutable drafts without restoring, saving or assembling files."""
    if not draft.prepared_by.strip():
        st.caption("[Enter Prepared by](#report-prepared-by) to view shared report history.")
        return
    contract, selected, period = draft.profile.contract, draft.profile.key, draft.period
    context = (contract, selected, tuple(site.key for site in draft.profile.facilities), period.key)
    context_key = prefix + "_history_context"
    cursor_key = prefix + "_history_before"
    cache_key = prefix + "_history_index"
    if st.session_state.get(context_key) != context:
        st.session_state.pop(cursor_key, None)
        st.session_state.pop(cache_key, None)
        st.session_state[context_key] = context
    before = st.session_state.get(cursor_key)
    try:
        identity = (context, snapshot.revision, snapshot.generated_at, before) if snapshot else (context, 0, "", before)
        cached = st.session_state.get(cache_key)
        if not cached or cached[0] != identity:
            cached = (identity, library.snapshot_history(contract, selected, period, before_revision=before))
            st.session_state[cache_key] = cached
        versions, older = cached[1]
        if not versions:
            st.caption("No shared versions saved for " + period.label + ".")
        else:
            st.caption(period.label + " · newest first. Inspecting a version keeps your current draft.")
            # This immutable index needs real table semantics, not canvas
            # fallback headers whose accessibility differs between engines.
            # Escape entered names as text; no Markdown or external images.
            rows = "".join("<tr>" + "".join(
                "<td>" + escape(str(value)) + "</td>" for value in (
                    version.revision, _saved_at(version.generated_at),
                    version.entered_editor or "Not recorded")) + "</tr>"
                for version in versions)
            st.html('<style>.enfra-history-versions{overflow-x:auto}'
                    '.enfra-history-versions table{width:100%;border-collapse:collapse}'
                    '.enfra-history-versions th,.enfra-history-versions td{'
                    'padding:.5rem;text-align:left;vertical-align:top;'
                    'border-bottom:1px solid #a5b5b1;overflow-wrap:anywhere}'
                    '</style><div class="enfra-history-versions">'
                    '<table aria-label="Saved report versions"><thead><tr>'
                    '<th scope="col">Version</th><th scope="col">Saved</th>'
                    '<th scope="col">Saved by</th></tr></thead><tbody>'
                    + rows + '</tbody></table></div>')
            by_revision = {version.revision: version for version in versions}
            selection_identity = sha256(repr((identity, tuple(
                (version.revision, version.generated_at, version.entered_editor)
                for version in versions))).encode()).hexdigest()[:20]
            revision = st.selectbox(
                "Inspect a saved version", (None, *by_revision),
                format_func=lambda value: "Choose a version" if value is None else (
                    f"Version {value} · {_saved_at(by_revision[value].generated_at)} · "
                    + (by_revision[value].entered_editor or "Saved by not recorded")),
                key=prefix + "_history_inspect_" + selection_identity,
            )
            if revision is not None:
                saved = library.load_snapshot_version(contract, selected, period, revision)
                from app.monthly_report_compare_ui import render_conflict_comparison
                render_conflict_comparison(
                    draft, saved, can_accept=False,
                    image_key=prefix + f"_history_images_{selection_identity}_{revision}",
                    working_asset_loader=lambda ref: assets.get(ref) or library.read_asset(contract, selected, ref),
                    saved_asset_loader=lambda ref: library.read_asset(contract, selected, ref),
                )
        if older and st.button("Older versions", key=prefix + "_history_older"):
            st.session_state[cursor_key] = versions[-1].revision
            st.rerun()
        if before is not None and st.button("Newest versions", key=prefix + "_history_newest"):
            st.session_state.pop(cursor_key, None)
            st.rerun()
        if st.button("Refresh shared history", key=prefix + "_history_refresh"):
            st.session_state.pop(cache_key, None)
            st.rerun()
    except (library.LibraryError, OSError) as exc:
        st.error("Shared report history could not be read: " + str(exc))
        st.caption("Your current draft and existing saved versions have not been changed.")
