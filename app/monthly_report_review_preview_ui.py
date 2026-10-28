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
from app.monthly_report_preview_store import STORE, PreviewTicket
from app.monthly_report_source_view_runtime import preview_fingerprint


def _discard_preview(owner, current):
    """Release one ticket without touching saved originals or other visitors."""
    if isinstance(current, dict) and isinstance(current.get("ticket"), PreviewTicket):
        STORE.discard(owner, current["ticket"])


def render_review_preview(draft, assets, prefix):
    """Render the current *complete* draft only after an explicit Review action."""
    owner = st.session_state.setdefault(prefix + "_review_preview_owner", uuid4().hex)
    state_key = prefix + "_review_draft_preview"
    current = st.session_state.get(state_key)
    sections = included_sections(draft.sections)

    try:
        identity = preview_fingerprint(draft)
    except (ValueError, OSError) as exc:
        _discard_preview(owner, current)
        st.session_state.pop(state_key, None)
        st.warning("The draft source or design changed. Check its source review before creating a preview: " + str(exc))
        return

    # A changed profile, saved source view, draft field, attachment or include/
    # exclude decision must retire the old ticket before displaying any page.
    stale = bool(current and (
        not isinstance(current, dict)
        or current.get("fingerprint") != identity
        or current.get("profile") != (draft.profile.contract, draft.profile.key, draft.period.key)
    ))
    if stale:
        _discard_preview(owner, current)
        st.session_state.pop(state_key, None)
        current = None
    elif current and (not isinstance(current.get("ticket"), PreviewTicket)
                      or not STORE.available(owner, current["ticket"])):
        st.session_state.pop(state_key, None)
        current = None
        st.caption("The temporary draft preview expired. Recreate it to see the current report.")

    st.markdown("**Draft report preview**")
    st.caption("Preview the entire current report, including sections you have not opened. "
               "This is a watermarked draft, not the finished Word or PDF.")
    if stale:
        st.caption("The report changed. The earlier draft preview was discarded; recreate it to see the edits.")
    if not sections:
        st.caption("No report sections are included. Choose a section before previewing.")
        return

    # The native button identifies its exact report/source revision. A delayed
    # click from an earlier report cannot authorize a new preview on this key.
    button_key = prefix + "_review_preview_build_" + identity
    if st.button("Preview current draft", key=button_key):
        loader = lambda ref: (
            assets.get(ref) or library.read_asset(draft.profile.contract, draft.profile.key, ref))
        try:
            with st.spinner("Preparing the current draft preview…"):
                preview = preview_report(draft, loader)
                if preview.fingerprint != identity:
                    raise ValueError("The report changed while its draft preview was being prepared. Retry with the current version.")
                ticket = STORE.put(owner, preview)
        except (ValueError, OSError) as exc:
            st.warning(str(exc))
            st.caption("The report is unchanged. Correct the named issue or retry the draft preview.")
        except Exception:
            st.warning("The draft preview could not finish. Your edits are unchanged; retry when ready.")
        else:
            current = {
                "fingerprint": identity,
                "profile": (draft.profile.contract, draft.profile.key, draft.period.key),
                "ticket": ticket,
            }
            st.session_state[state_key] = current

    if not current:
        return
    ticket = current["ticket"]
    if not STORE.available(owner, ticket):
        st.session_state.pop(state_key, None)
        st.warning("The temporary preview is no longer available. Recreate it to see the current report.")
        return

    page = st.number_input(
        "Draft preview page", min_value=1, max_value=ticket.pages,
        value=1, step=1, key=prefix + "_review_preview_page_" + ticket.key,
    )
    try:
        visible = STORE.pages(owner, ticket, (int(page) - 1,), dpi=120)
        if not visible:
            raise ValueError("The preview page expired.")
    except (ValueError, OSError):
        _discard_preview(owner, current)
        st.session_state.pop(state_key, None)
        st.warning("This draft page could not be displayed. Recreate the preview to retry.")
        return
    st.image(visible[0][1], width="stretch")
    st.caption(f"Current draft · page {page} of {ticket.pages} · {draft.period.label}")
