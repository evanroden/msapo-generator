"""Edit saved pictures beside their previews, retaining immutable originals."""

from dataclasses import replace
import hashlib

import streamlit as st


def _move_page(key, delta, last):
    st.session_state[key] = min(last, max(0, st.session_state.get(key, 0) + delta))


def _request_removal(key, references, index):
    st.session_state[key] = (references, index)


def edit_saved_pictures(block, key, loader):
    """Return the current block; the caller retains it in its working draft.

    Buttons record an exact image-list decision before rerun, so removal happens
    before drawing previews. A stale button cannot remove a different picture.
    """
    pending_key = key + "_remove_request"
    pending = st.session_state.pop(pending_key, None)
    if pending and pending[0] == block.asset_hashes and 0 <= pending[1] < len(block.asset_hashes):
        index = pending[1]
        keep = [n for n in range(len(block.asset_hashes)) if n != index]
        captions = tuple(block.asset_captions[n] if n < len(block.asset_captions) else "" for n in keep)
        references = tuple(block.references[n] for n in keep) if len(block.references) == len(block.asset_hashes) else block.references
        block = replace(block, asset_hashes=tuple(block.asset_hashes[n] for n in keep),
                        asset_captions=captions, references=references,
                        client_reviewed_fingerprint="", reviewed_fingerprint="")
    count = len(block.asset_hashes)
    if not count:
        st.caption("No pictures are included here. Add a picture below when you need one.")
        return block
    page_key = key + "_picture_page"
    last = (count - 1) // 4
    page = min(max(0, st.session_state.get(page_key, 0)), last)
    st.session_state[page_key] = page
    if last:
        previous, status, following = st.columns([1, 2, 1])
        previous.button("Previous pictures", key=key + "_previous", disabled=page == 0,
                        on_click=_move_page, args=(page_key, -1, last))
        status.caption(f"Pictures {page * 4 + 1}–{min(page * 4 + 4, count)} of {count}")
        following.button("Next pictures", key=key + "_next", disabled=page == last,
                         on_click=_move_page, args=(page_key, 1, last))
    st.caption("These pictures are included in this report. Removing one changes this draft; saved originals remain available.")
    version = hashlib.sha256(repr(block.asset_hashes).encode()).hexdigest()[:16]
    for index in range(page * 4, min(page * 4 + 4, count)):
        with st.container(border=True):
            caption = block.asset_captions[index] if index < len(block.asset_captions) else ""
            label = caption or ("Current picture" if count == 1 else f"Picture {index + 1}")
            st.write(label)
            try:
                st.image(loader(block.asset_hashes[index]), width="stretch")
            except (ValueError, OSError):
                st.warning("This picture could not be displayed. Replace it with a clear copy or remove it from this draft.")
            st.button("Remove this picture" if count == 1 else f"Remove picture {index + 1}",
                      key=key + f"_remove_{version}_{index}", on_click=_request_removal,
                      args=(pending_key, block.asset_hashes, index))
    return block
