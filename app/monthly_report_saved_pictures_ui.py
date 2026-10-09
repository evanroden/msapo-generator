"""Edit saved pictures beside their previews, retaining immutable originals."""

from dataclasses import replace
import hashlib

import streamlit as st

from app.monthly_report_asset_review import pending_asset_indexes, preserve_asset_reviews


def _move_page(key, delta, last):
    st.session_state[key] = min(last, max(0, st.session_state.get(key, 0) + delta))


def _request_removal(key, references, index):
    st.session_state[key] = (references, index)


def _set_editing(key, value):
    st.session_state[key] = value


def remove_saved_picture(block, index):
    """Remove one picture without guessing which narrative evidence to discard."""
    block = preserve_asset_reviews(block, block)
    keep = tuple(n for n in range(len(block.asset_hashes)) if n != index)
    refs = block.references
    contexts = dict(block.asset_provenance)
    removed_context = {ref for ref in contexts.get(block.asset_hashes[index], ()) if ref in block.references}
    retained_context = {ref for n in keep for ref in contexts.get(block.asset_hashes[n], ())}
    native_content = bool(block.text.strip() or block.rows or block.extra_tables or block.ai_paragraphs or block.org_nodes)
    # Shared source references and evidence used by native content stay intact.
    # Multiple references on a final unmapped page can describe native content
    # outside the image; retain that ambiguous evidence conservatively.
    if not native_content and (keep or len(removed_context) <= 1):
        discarded = removed_context - retained_context
        refs = tuple(ref for ref in refs if ref not in discarded)
    return preserve_asset_reviews(block, replace(
        block,
        asset_hashes=tuple(block.asset_hashes[n] for n in keep),
        asset_captions=tuple(block.asset_captions[n] if n < len(block.asset_captions) else "" for n in keep),
        references=refs,
        client_reviewed_fingerprint="",
        reviewed_fingerprint="",
    ))


def edit_saved_pictures(block, key, loader, *, show_preview=True):
    """Return the current block; the caller retains it in its working draft.

    Buttons record an exact image-list decision before rerun, so removal happens
    before drawing previews. A stale button cannot remove a different picture.
    """
    block = preserve_asset_reviews(block, block)
    pending_key = key + "_remove_request"
    pending = st.session_state.pop(pending_key, None)
    if pending and pending[0] == block.asset_hashes and 0 <= pending[1] < len(block.asset_hashes):
        block = remove_saved_picture(block, pending[1])
    count = len(block.asset_hashes)
    if not count:
        st.caption("No pictures are included here. Add a picture below when you need one.")
        return block
    editing_key = key + "_editing"
    pending_indexes = pending_asset_indexes(block)
    ready = not pending_indexes
    if ready and not st.session_state.get(editing_key):
        st.caption(f"{count} {'picture is' if count == 1 else 'pictures are'} ready. Earlier reviews are saved.")
        st.button("View or change pictures", key=key + "_edit", on_click=_set_editing, args=(editing_key, True))
        return block
    editing = st.session_state.get(editing_key, False)
    if editing:
        st.button("Done editing pictures", key=key + "_done", on_click=_set_editing, args=(editing_key, False))
    elif len(pending_indexes) < count:
        st.caption(f"{len(pending_indexes)} new or changed pictures. The other pictures keep their saved reviews.")
        st.button("View all pictures", key=key + "_edit_all", on_click=_set_editing, args=(editing_key, True))
    visible = tuple(range(count)) if editing else pending_indexes
    page_key = key + "_picture_page"
    last = (len(visible) - 1) // 4
    page = min(max(0, st.session_state.get(page_key, 0)), last)
    st.session_state[page_key] = page
    if last:
        previous, status, following = st.columns([1, 2, 1])
        previous.button("Previous pictures", key=key + "_previous", disabled=page == 0,
                        on_click=_move_page, args=(page_key, -1, last))
        status.caption(f"Pictures {page * 4 + 1}–{min(page * 4 + 4, len(visible))} of {len(visible)}")
        following.button("Next pictures", key=key + "_next", disabled=page == last,
                         on_click=_move_page, args=(page_key, 1, last))
    st.caption("These pictures are included in this report. Removing one changes this draft; saved originals remain available.")
    version = hashlib.sha256(repr(block.asset_hashes).encode()).hexdigest()[:16]
    for index in visible[page * 4:page * 4 + 4]:
        with st.container():
            caption = block.asset_captions[index] if index < len(block.asset_captions) else ""
            label = caption or ("Current picture" if count == 1 else f"Picture {index + 1}")
            st.write(label)
            if show_preview:
                try:
                    st.image(loader(block.asset_hashes[index]), width="stretch")
                except (ValueError, OSError):
                    st.warning("This picture could not be displayed. Replace it with a clear copy or remove it from this draft.")
            st.button("Remove this picture" if count == 1 else f"Remove picture {index + 1}",
                      key=key + f"_remove_{version}_{index}", on_click=_request_removal,
                      args=(pending_key, block.asset_hashes, index))
    return block
