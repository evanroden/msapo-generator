"""Automatic, session-local preview beside the active section editor."""

from base64 import b64encode
from html import escape
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from time import monotonic

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_render_jobs import RenderBusy
from app.monthly_report_preview import (
    MAX_PREVIEW_BYTES, preview_page, preview_section, section_preview_fingerprint,
)


MAX_CACHED_SECTIONS = 3
MAX_CACHE_BYTES = 40 * 1024 * 1024
PREVIEW_HEIGHT = 760


def _page_window(preview, title):
    """A sharp, scrollable document surface, without image/download toolbars."""
    pages = []
    size = 0
    for index in range(preview.pages):
        raw = preview_page(preview, index, dpi=150)
        size += len(raw)
        if size > MAX_PREVIEW_BYTES:
            raise ValueError("The section preview is too large to display. Reduce the size of its pictures.")
        pages.append(
            '<figure><img loading="lazy" alt="' + escape(title, quote=True)
            + ' — page ' + str(index + 1) + '" src="data:image/png;base64,'
            + b64encode(raw).decode("ascii") + '"><figcaption>Page '
            + str(index + 1) + ' of ' + str(preview.pages) + '</figcaption></figure>'
        )
    return """<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
html { background:#edf1ef; color:#40524a; font:13px system-ui,sans-serif; }
body { margin:0; padding:12px; }
figure { margin:0 0 16px; }
img { display:block; width:100%; height:auto; background:white; box-shadow:0 1px 6px #18382b26; }
figcaption { text-align:center; padding-top:7px; }
</style></head><body>""" + "".join(pages) + "</body></html>"


def _trim_cache(cache):
    while len(cache) > MAX_CACHED_SECTIONS or sum(
        len(value.get("html", "")) + len(value["preview"].pdf) if value.get("preview") else 0
        for value in cache.values()
    ) > MAX_CACHE_BYTES:
        # A single valid entry fits the independent PDF/raster bounds and must
        # remain usable even if HTML's base64 expansion exceeds the soft budget.
        if len(cache) == 1:
            break
        del cache[next(iter(cache))]


def render_section_preview(draft, section_key, assets, prefix, *, deferred=False):
    """Call in the right column after editor values are applied to ``draft``.

    The preview refreshes automatically on Streamlit's edit rerun. Cache state
    lives only in the current visitor's session; neither approval metadata nor
    the production directory is changed. No finished-report approval is implied.
    """
    if deferred:
        return render_ordered_section_preview(draft, section_key, assets, prefix)
    title = "Cover" if section_key == "cover" else next(
        (section.title for section in draft.sections if section.key == section_key), "Report section"
    )
    st.subheader("Section preview")
    st.caption(title + " · Draft layout · Updates when you finish an edit.")
    cache_key = prefix + "_section_preview_cache"
    cache = st.session_state.get(cache_key, {})
    try:
        fingerprint = section_preview_fingerprint(draft, section_key)
    except Exception as exc:
        st.warning(str(exc) if isinstance(exc, ValueError) else
                   "The section preview is unavailable. Your edits are still here.")
        return None
    entry = cache.pop(fingerprint, None)
    if entry is None:
        def loader(ref):
            return assets.get(ref) or library.read_asset(draft.profile.contract, draft.profile.key, ref)

        try:
            with st.spinner("Updating section preview…"):
                preview = preview_section(draft, section_key, loader)
                entry = {"preview": preview, "html": _page_window(preview, title)}
        except Exception as exc:
            entry = {"error": str(exc) if isinstance(exc, ValueError) else
                     "The section preview could not update. Your edits are still here. Retry the preview when ready."}
    cache[fingerprint] = entry
    _trim_cache(cache)
    st.session_state[cache_key] = cache
    if entry.get("error"):
        # Never leave a previous version looking like the current edit.
        st.warning(entry["error"])
        if st.button("Retry preview", key=prefix + "_section_preview_retry_" + section_key):
            cache.pop(fingerprint, None)
            st.session_state[cache_key] = cache
            st.rerun()
        return None
    # HTML is authored here; the only user text in it is escaped image alt text.
    # st.iframe is the supported Streamlit 1.61 replacement for components.html.
    st.iframe(entry["html"], height=PREVIEW_HEIGHT)
    return entry["preview"]


# Conversion is CPU/memory intensive. One worker serves the app; at most one job
# per session is submitted. Other section requests remain lightweight snapshots.
_PREVIEW_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="report-preview")
_PREVIEW_SLOT = BoundedSemaphore(1)
ORDERED_CACHE_BYTES = 80 * 1024 * 1024


def _build_preview_entry(draft, section_key, assets, title):
    def loader(ref):
        return assets.get(ref) or library.read_asset(draft.profile.contract, draft.profile.key, ref)

    try:
        preview = preview_section(draft, section_key, loader)
        return {"html": _page_window(preview, title), "pages": preview.pages}
    except RenderBusy:
        return {"busy": True}
    except Exception as exc:
        return {"error": str(exc) if isinstance(exc, ValueError) else
                "The section preview could not update. Your edits are still here. Retry the preview when ready."}
    finally:
        _PREVIEW_SLOT.release()


def _bound_ordered_preview_cache(state):
    cache = state["cache"]
    # Retain every normal section, but never an unbounded raster/PDF duplicate.
    # Oversized entries become a stable error instead of triggering rerender loops.
    if sum(len(entry.get("html", "")) for entry in cache.values()) > ORDERED_CACHE_BYTES:
        for key in list(cache):
            entry = cache[key]
            if "html" in entry:
                cache[key] = {"fingerprint": entry["fingerprint"],
                              "error": "This preview exceeded the display memory limit. Retry it after finishing other edits."}
                if sum(len(value.get("html", "")) for value in cache.values()) <= ORDERED_CACHE_BYTES:
                    break


def _advance_preview_queue(state):
    running = state.get("running")
    if running and running[2].done():
        section, fingerprint, future = running
        try:
            entry = future.result()
        except Exception:
            entry = {"error": "The section preview could not update. Your edits are still here."}
        # An edit made during conversion invalidates that result immediately.
        if state["wanted"].get(section) == fingerprint:
            if entry.get("busy"):
                request = state.get("running_request")
                if request is not None:
                    state["queue"].setdefault(section, request)
                    state["retry_after"] = monotonic() + 2
                else:
                    state["wanted"].pop(section, None)
            else:
                state["cache"][section] = {"fingerprint": fingerprint, **entry}
        state["running"] = None
        state.pop("running_request", None)
        _bound_ordered_preview_cache(state)
    if state.get("running") or not state["queue"]:
        return
    if monotonic() < state.get("retry_after", 0):
        return
    if not _PREVIEW_SLOT.acquire(blocking=False):
        return
    section = next(iter(state["queue"]))
    fingerprint, draft, assets, title = state["queue"].pop(section)
    try:
        future = _PREVIEW_WORKER.submit(_build_preview_entry, draft, section, assets, title)
    except Exception:
        _PREVIEW_SLOT.release()
        state["cache"][section] = {"fingerprint": fingerprint, "error": "The preview could not start. Your edits are still here."}
    else:
        state["running"] = (section, fingerprint, future)
        state["running_request"] = (fingerprint, draft, assets, title)


def _ordered_preview_state(prefix):
    return st.session_state.setdefault(prefix + "_ordered_previews", {
        "wanted": {}, "queue": {}, "cache": {}, "running": None,
    })


def _render_ordered_preview(section_key, prefix, title):
    state = _ordered_preview_state(prefix)
    _advance_preview_queue(state)
    entry = state["cache"].get(section_key)
    if state.get("polling") and not state.get("running") and not state["queue"]:
        state["polling"] = False
        # Stop all timers once the queue drains; cached document panes then
        # remain static until another edit creates work.
        st.rerun()
    st.subheader("Section preview")
    st.caption(title + " · Updates automatically after edits.")
    if not entry or entry.get("fingerprint") != state["wanted"].get(section_key):
        st.info("Preparing this section’s preview… You can keep editing.")
        return
    if entry.get("error"):
        st.warning(entry["error"])
        if st.button("Retry preview", key=prefix + "_ordered_retry_" + section_key):
            state["wanted"].pop(section_key, None)
            state["cache"].pop(section_key, None)
            st.rerun()
        return
    st.iframe(entry["html"], height=PREVIEW_HEIGHT)


def render_ordered_section_preview(draft, section_key, assets, prefix):
    """Enqueue this pane without blocking or converting every section on reruns."""
    title = "Cover" if section_key == "cover" else next(
        (section.title for section in draft.sections if section.key == section_key), "Report section")
    state = _ordered_preview_state(prefix)
    try:
        fingerprint = section_preview_fingerprint(draft, section_key)
    except Exception:
        st.warning("The section preview is unavailable. Your edits are still here.")
        return None
    prior = state["wanted"].get(section_key)
    if prior != fingerprint:
        state["wanted"][section_key] = fingerprint
        state["cache"].pop(section_key, None)
        state["queue"].pop(section_key, None)
        request = (fingerprint, draft, dict(assets), title)
        # Newly edited sections take priority over first-load background work.
        if prior is not None:
            state["queue"] = {section_key: request, **state["queue"]}
        else:
            state["queue"][section_key] = request
    _advance_preview_queue(state)
    pending = section_key in state["queue"] or bool(
        state.get("running") and state["running"][0] == section_key)
    if pending:
        state["polling"] = True
    st.fragment(run_every="2s" if pending else None)(_render_ordered_preview)(section_key, prefix, title)
    return None
