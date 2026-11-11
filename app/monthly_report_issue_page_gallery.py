"""Preview-driven equipment-issue source-page choices.

The gallery is an alternative input to the existing receipt-protected
Supporting source pages multiselect. It does not approve source content, mutate stored originals, or change
another issue's references. Output emission is separately review-gated.
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
    """Show up to four actual thumbnails and an optional large preview.

    Only the visible page group is rasterized, via the existing bounded cache.
    A broken/unavailable thumbnail never rewrites its selection.
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
            "Visible thumbnails are previews, not approval. Use Preview to enlarge one page; no file or page is automatically attached.")
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
        duplicate_name = sum(candidate.filename == source.filename for candidate in files) > 1
        for number, reference in shown:
            label = f"{source.filename} · page {number}"
            if duplicate_name:
                label += f" · source {source.id[:8]}"
            with st.container(border=True):
                checkbox_key = p + "_gallery_check_" + _key(reference)
                # Set before widget creation: the current saved issue/receipt
                # wins over an old browser mirror even after source replacement.
                st.session_state[checkbox_key] = reference in selected
                st.checkbox(
                    "Include " + label + " as issue evidence",
                    key=checkbox_key,
                    on_change=_choose_page,
                    args=(widget_key, checkbox_key, reference, tuple(options),
                          identity, registration["token"]),
                )
                picture = None
                if source.suffix in PREVIEWABLE:
                    try:
                        picture = sources.page_image(
                            draft.profile, sources.SourceContent(source), number,
                            preview=True)
                    except (ValueError, OSError, IndexError, RuntimeError):
                        st.warning("Preview unavailable for " + label +
                                   ". Restore the original or reopen Manage source files. "
                                   "Your evidence selection was not changed.")
                else:
                    st.caption("No raster thumbnail for " + label +
                               ". Inspect the original in Manage source files.")
                if picture is not None:
                    st.image(picture.data, width=160,
                             caption=label + (" · Selected" if reference in selected else " · Not selected"))
                if st.button("Preview " + label, key=p + "_gallery_show_" + _key(reference)):
                    st.session_state[preview_key] = reference
                    preview_ref = reference
                if preview_ref != reference:
                    continue
                if picture is None:
                    st.caption("Large preview unavailable. Reopen Manage source files; selection is unchanged.")
                    continue
                st.image(picture.data, width="stretch",
                         caption=label + " · Preview only; use fullscreen to inspect details.")
