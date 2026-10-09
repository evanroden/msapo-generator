"""Automatic, session-local preview beside the active section editor."""

from base64 import b64encode
from html import escape

import streamlit as st

from app import monthly_report_library as library
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


def render_section_preview(draft, section_key, assets, prefix):
    """Call in the right column after editor values are applied to ``draft``.

    The preview refreshes automatically on Streamlit's edit rerun. Cache state
    lives only in the current visitor's session; neither approval metadata nor
    the production directory is changed. No finished-report approval is implied.
    """
    title = "Cover" if section_key == "cover" else next(
        (section.title for section in draft.sections if section.key == section_key), "Report section"
    )
    st.subheader("Section preview")
    st.caption(title + " · Draft layout · Updates when you finish an edit.")
    cache_key = prefix + "_section_preview_cache"
    cache = st.session_state.get(cache_key, {})
    try:
        fingerprint = section_preview_fingerprint(draft, section_key)
    except ValueError as exc:
        st.info(str(exc))
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
