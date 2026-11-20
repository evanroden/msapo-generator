"""On-demand, full-report Review preview from the authoritative current draft.

Existing editor section previews are viewport-driven. This bounded Review
action builds from the canonical report in one pass, without visiting them.
The resulting PDF is temporary, watermarked, ticketed and never a final
download or an approval receipt.
"""
from __future__ import annotations

from uuid import uuid4

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_model import included_sections
from app.monthly_report_preview import preview_report
from app.monthly_report_render_jobs import RenderBusy
from app.monthly_report_preview_store import STORE, PreviewTicket
from app.monthly_report_source_view_runtime import preview_fingerprint


def _discard_preview(owner, current):
    """Release one ticket without touching saved originals or other visitors."""
    if isinstance(current, dict) and isinstance(current.get("ticket"), PreviewTicket):
        try:
            STORE.discard(owner, current["ticket"])
        except (ValueError, OSError):
            # The isolated-QA namespace may be retired during another reset.
            # A missed cache discard can only expire; no draft is affected.
            pass


def discard_review_preview(prefix):
    """Retire this report's held ticket before its session keys disappear."""
    owner_key = prefix + "_review_preview_owner"
    state_key = prefix + "_review_draft_preview"
    owner = st.session_state.get(owner_key)
    if isinstance(owner, str) and owner:
        _discard_preview(owner, st.session_state.get(state_key))
    st.session_state.pop(state_key, None)
    st.session_state.pop(owner_key, None)


def _available(owner, ticket):
    try:
        return STORE.available(owner, ticket)
    except (ValueError, OSError):
        return False


def _visibility_changed(prefix, widget_key, identity):
    """A browser view receipt never edits the draft or starts a conversion."""
    from app.monthly_report_review_activation import valid_activation
    value = st.session_state.get(widget_key)
    if valid_activation(value, identity):
        st.session_state[prefix + "_review_preview_activation"] = identity


def _show_ticket(slot, owner, current, draft, prefix, *, stale):
    """Paint the last good ticket before potentially expensive replacement work."""
    ticket = current["ticket"]
    with slot.container():
        if stale:
            st.caption("Showing older preview — latest changes not shown. "
                       "This is not the current draft; refresh is pending or needs retry.")
        page = st.number_input(
            "Draft preview page", min_value=1, max_value=ticket.pages,
            value=1, step=1, key=prefix + "_review_preview_page_" + ticket.key,
        )
        try:
            # First two pages are decoded together, then only the visible pair
            # when the reader advances. Never request the remaining report eagerly.
            first = int(page) - 1
            visible = STORE.pages(owner, ticket, tuple(range(first, min(first + 2, ticket.pages))), dpi=120)
            if not visible:
                raise ValueError("The preview page expired.")
        except (ValueError, OSError):
            _discard_preview(owner, current)
            st.session_state.pop(prefix + "_review_draft_preview", None)
            st.warning("This draft page could not be displayed. Recreate the preview to retry.")
            return False
        for index, raster in visible:
            st.image(raster, width="stretch")
            if stale:
                st.caption(f"Older draft page {index + 1} of {ticket.pages} · latest changes not shown")
            else:
                st.caption(f"Draft page {index + 1} of {ticket.pages}")
        if stale:
            st.caption(f"Older draft · page {page} of {ticket.pages} · "
                       f"{current.get('period', draft.period.label)} · latest changes not shown")
        else:
            st.caption(f"Current draft · page {page} of {ticket.pages} · {draft.period.label} · "
                       "full report, no omitted pages")
    return True


def render_review_preview(draft, assets, prefix):
    """Populate Review directly when visible, from the complete canonical draft.

    The browser reports only that this revision's Review is in view. The server
    assembles from the already accepted/saved draft, never mounted widgets.
    One automatic attempt per revision prevents busy/error rerun loops; the
    native button is an explicit recovery path.
    """
    from app.monthly_report_review_activation import render_activation
    owner = st.session_state.setdefault(prefix + "_review_preview_owner", uuid4().hex)
    state_key = prefix + "_review_draft_preview"
    attempted_key = prefix + "_review_preview_attempted"
    current = st.session_state.get(state_key)
    sections = included_sections(draft.sections)
    profile = (draft.profile.contract, draft.profile.key, draft.period.key)

    try:
        identity = preview_fingerprint(draft)
    except (ValueError, OSError) as exc:
        _discard_preview(owner, current)
        st.session_state.pop(state_key, None)
        st.warning("The draft source or design changed. Check its source review before creating a preview: " + str(exc))
        return

    # Earlier pages can remain inspectable for the same site/month only, with
    # an explicit outdated label. A cross-report move retires them immediately.
    if current and (not isinstance(current, dict) or current.get("profile") != profile
                    or not isinstance(current.get("ticket"), PreviewTicket)):
        _discard_preview(owner, current)
        st.session_state.pop(state_key, None)
        current = None
    elif current and not _available(owner, current["ticket"]):
        st.session_state.pop(state_key, None)
        current = None
        st.caption("The temporary draft preview expired. Recreate it to see the current report.")

    stale = bool(current and current.get("fingerprint") != identity)
    st.markdown("**Draft report preview**")
    st.caption("Preview the entire current report, including sections you have not opened. "
               "This is a watermarked draft, not the finished Word or PDF.")
    if stale:
        st.caption("The report changed. An older preview is retained but is not current.")
    if not sections:
        _discard_preview(owner, current)
        st.session_state.pop(state_key, None)
        st.caption("No report sections are included. Choose a section before previewing.")
        return

    widget_key = prefix + "_review_visibility"
    attempted = st.session_state.get(attempted_key) == identity
    render_activation(
        key=widget_key, identity=identity, attempted=attempted or bool(current and not stale),
        on_change=lambda: _visibility_changed(prefix, widget_key, identity),
    )
    # A delayed click/request from a previous revision cannot build another
    # report on this key. The fallback remains useful without browser JS.
    pressed = st.button("Preview current draft", key=prefix + "_review_preview_build_" + identity)
    slot = st.empty()
    if current and not _show_ticket(slot, owner, current, draft, prefix, stale=stale):
        current = None
        stale = False

    activated = st.session_state.get(prefix + "_review_preview_activation") == identity
    if not (pressed or (activated and not attempted)) or (current and not stale):
        return

    # Record before work starts; a failed/busy conversion must not rerun
    # automatically on every harmless Streamlit rerender.
    st.session_state[attempted_key] = identity
    loader = lambda ref: (
        assets.get(ref) or library.read_asset(draft.profile.contract, draft.profile.key, ref))
    try:
        with st.spinner("Preparing the current draft preview…"):
            # Ticket PDFs never leave the store: only rasterized pages reach
            # this UI. Downloadable draft PDFs keep the flattened path.
            preview = preview_report(draft, loader, ticket_only=True)
            if preview.fingerprint != identity:
                raise ValueError("The report changed while its draft preview was being prepared. Retry with the current version.")
            ticket = STORE.put(owner, preview)
    except (ValueError, OSError, RenderBusy) as exc:
        st.warning(str(exc))
        st.caption("The report is unchanged. Correct the named issue or retry the draft preview.")
        return
    except Exception:
        st.warning("The draft preview could not finish. Your edits are unchanged; retry when ready.")
        return

    fresh = {"fingerprint": identity, "profile": profile, "period": draft.period.label,
             "ticket": ticket}
    st.session_state[state_key] = fresh
    if current:
        _discard_preview(owner, current)
    _show_ticket(slot, owner, fresh, draft, prefix, stale=False)
