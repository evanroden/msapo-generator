"""Preview-driven equipment-issue source-page choices.

The gallery is an alternative input to the existing receipt-protected
Supporting source pages multiselect. It never embeds pages, approves source
content, mutates stored originals, or changes another issue's references.
"""
import hashlib

import streamlit as st

from app import monthly_report_sources as sources


PAGE_SIZE = 4
PREVIEWABLE = frozenset({".pdf", *sources.ocr.SUPPORTED_IMAGE_SUFFIXES})


def _key(reference):
    return hashlib.sha256(reference.encode("utf-8")).hexdigest()[:20]


def _choose_page(widget_key, checkbox_key, reference, options, identity, token):
    """Capture a delivered checkbox as the existing multiselect's one edit.

    Stale row/source callbacks may not resurrect an old page selection. Source
    ordering (not click sequence) defines the issue evidence's stable order.
    """
    registration = st.session_state.get(widget_key + "_delivery")
    if (not isinstance(registration, dict)
            or registration.get("identity") != identity
            or registration.get("token") != token
            or reference not in options):
        return
    before = registration.get("before")
    active = st.session_state.get(widget_key)
    if (not isinstance(before, list) or not isinstance(active, list)
            or active != before or any(ref not in options for ref in active)):
        return
    wanted = set(active)
    if st.session_state.get(checkbox_key) is True:
        wanted.add(reference)
    else:
        wanted.discard(reference)
    revised = [ref for ref in options if ref in wanted]
    if revised == before:
        return
    st.session_state[widget_key] = revised
    # The established issue-edit journal sees the same exact native delivery
    # as a change made using the existing multiselect, not a second data path.
    from app.monthly_report_issues import _issue_changed
    _issue_changed(widget_key, before, identity, token)


def render_page_gallery(draft, options, selected, p, widget_key, identity, field):
    """Show small, explicit file/page controls and one on-demand preview.

    Source bytes are decoded only when the user opens one particular page.
    A broken/unavailable preview does not rewrite its existing selection.
    """
    files = tuple(source for source in draft.sources if source.page_texts)
    if not files:
        return
    registration = st.session_state.get(widget_key + "_delivery")
    if not isinstance(registration, dict) or registration.get("identity") != identity:
        return

    with st.expander("Choose supporting pages by preview"):
        st.caption(
            "Each checkbox links a saved source page to this issue only. "
            "Use Preview to inspect an image; no file or page is automatically attached.")
        by_id = {source.id: source for source in files}
        file_key = p + "_gallery_file"
        if st.session_state.get(file_key) not in by_id:
            st.session_state[file_key] = files[0].id
        if len(files) == 1:
            source = files[0]
            st.caption("Source: " + source.filename)
        else:
            names = {source.id: source.filename for source in files}
            duplicates = {name for name in names.values()
                          if list(names.values()).count(name) > 1}
            def label(source_id):
                name = names[source_id]
                return name + (" · " + source_id[:8] if name in duplicates else "")
            chosen = st.selectbox("Source file to inspect", list(by_id),
                                  format_func=label, key=file_key)
            source = by_id[chosen]

        pages = [(n, sources.source_reference(source, n))
                 for n in range(1, len(source.page_texts) + 1)
                 if sources.source_reference(source, n) in options]
        if not pages:
            st.caption("This source has no selectable pages in the current issue.")
            return

        range_key = p + "_gallery_range_" + _key(source.id)
        ranges = tuple(range(0, len(pages), PAGE_SIZE))
        if st.session_state.get(range_key) not in ranges:
            st.session_state[range_key] = ranges[0]
        start = (st.selectbox("Pages to review", ranges, key=range_key,
            format_func=lambda n: f"Pages {n + 1}–{min(n + PAGE_SIZE, len(pages))} of {len(pages)}")
            if len(ranges) > 1 else 0)
        shown = pages[start:start + PAGE_SIZE]
        preview_key = p + "_gallery_preview"
        preview_ref = st.session_state.get(preview_key)
        selected = set(selected)
        for number, reference in shown:
            label = f"{source.filename} · page {number}"
            with st.container(border=True):
                checkbox_key = p + "_gallery_check_" + _key(reference)
                # Set before widget creation: a multiselect edit, reload or
                # accepted callback must take precedence over stale UI mirrors.
                st.session_state[checkbox_key] = reference in selected
                st.checkbox(
                    "Include " + label + " as issue evidence",
                    key=checkbox_key,
                    on_change=_choose_page,
                    args=(widget_key, checkbox_key, reference, tuple(options),
                          identity, registration["token"]),
                )
                if st.button("Preview " + label, key=p + "_gallery_show_" + _key(reference)):
                    st.session_state[preview_key] = reference
                    preview_ref = reference
                if preview_ref != reference:
                    continue
                if source.suffix not in PREVIEWABLE:
                    st.caption(
                        "This source has no raster page preview here. "
                        "Inspect the original source file before selecting it.")
                    continue
                try:
                    image = sources.page_image(
                        draft.profile, sources.SourceContent(source), number,
                        preview=True)
                except (ValueError, OSError, IndexError):
                    st.warning(
                        "Preview unavailable for " + label +
                        ". Check the original in Manage source files. "
                        "The issue selection was not changed.")
                    continue
                st.image(
                    image.data, width="stretch",
                    caption=label + " · Preview only; use fullscreen to examine small details.",
                )
                st.caption(label + " · Preview only; original and issue links are unchanged.")
