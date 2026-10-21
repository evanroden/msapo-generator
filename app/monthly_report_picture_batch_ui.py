"""Bounded, explicit guided picture review; existing per-image receipts only."""
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from uuid import uuid4

from PIL import Image
import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_asset_review import (
    approve_asset, asset_context, asset_fingerprint, asset_reviewed,
    pending_asset_indexes, refresh_asset_source_context,
)
from app.monthly_report_model import used_block_keys

MAX_PICTURES = 6
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_BATCH_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 4_000_000
MAX_BATCH_PIXELS = 16_000_000


def _manifest(draft, incarnation):
    used = used_block_keys(draft)
    blocks = tuple(refresh_asset_source_context(b, draft.sources) for b in draft.blocks)
    draft = replace(draft, blocks=blocks)
    entries = tuple((b.key, i, asset_fingerprint(b, i), ref,
                     b.asset_captions[i] if i < len(b.asset_captions) else '')
                    for b in blocks if b.key in used and b.source != 'Omit'
                    for i, ref in enumerate(b.asset_hashes))
    identity = (draft.profile.contract, draft.profile.key, draft.profile.imported_from,
                draft.profile.template, tuple((f.key, f.title) for f in draft.profile.facilities),
                draft.period.key, draft.prepared_by, incarnation, entries,
                tuple((s.id, s.fingerprint) for s in draft.sources))
    return draft, entries, sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def _read_picture(draft, assets, entry):
    ref = entry[3]
    raw = assets.get(ref)
    if raw is None:
        raw = library.read_asset(draft.profile.contract, draft.profile.key, ref)
    if (not isinstance(raw, bytes) or not raw or len(raw) > MAX_IMAGE_BYTES
            or ref != library.asset_reference(raw, ref.rsplit('.', 1)[-1])):
        raise ValueError('Picture identity or byte budget changed.')
    with Image.open(BytesIO(raw)) as image:
        pixels = image.width * image.height
        if image.format not in ('PNG', 'JPEG') or not 0 < pixels <= MAX_IMAGE_PIXELS:
            raise ValueError('Picture is outside the bounded review size.')
        image.verify()
    # Header verification alone accepts some truncated JPEG payloads.
    with Image.open(BytesIO(raw)) as image:
        image.load()
    return raw, pixels


def _eligible(draft, entry):
    block = next((b for b in draft.blocks if b.key == entry[0]), None)
    i = entry[1]
    return (block is not None and i in pending_asset_indexes(block)
            and asset_fingerprint(block, i) == entry[2]
            and asset_reviewed(refresh_asset_source_context(approve_asset(block, i), draft.sources), i))


def _blocked(draft, entries):
    from app.monthly_report_checks import preflight
    checks = preflight(draft)
    blocked = {c.block_key for c in checks if c.code in ('client_source_missing', 'client_source_page', 'pricing')}
    sources = {c.block_key for c in checks if c.code in ('source_facility', 'source_missing')}
    for entry in entries:
        block = next((b for b in draft.blocks if b.key == entry[0]), None)
        if any(ref == sid or ref.startswith(sid + ':')
               for ref in asset_context(block, entry[1]) for sid in sources):
            blocked.add(entry[0])
    return blocked


def _choose(draft, assets, entries, deferred):
    pending = tuple(e for e in entries if e[1] in pending_asset_indexes(next(b for b in draft.blocks if b.key == e[0])))
    counts = Counter(e[2] for e in entries)
    fallback = _blocked(draft, entries)
    fallback.update(e[0] for e in pending if counts[e[2]] != 1 or e[2] in deferred or not _eligible(draft, e))
    selected, raw_images = [], []
    total_bytes = total_pixels = 0
    for entry in pending:
        if entry[0] in fallback:
            continue
        try:
            raw, pixels = _read_picture(draft, assets, entry)
        except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
            fallback.add(entry[0])
            # Do not mix a partly unreadable block into a joint confirmation.
            retained = [(e, data, px) for e, (data, px) in zip(selected, raw_images) if e[0] != entry[0]]
            selected = [x[0] for x in retained]
            raw_images = [(x[1], x[2]) for x in retained]
            total_bytes = sum(len(x[0]) for x in raw_images)
            total_pixels = sum(x[1] for x in raw_images)
            continue
        if total_bytes + len(raw) > MAX_BATCH_BYTES or total_pixels + pixels > MAX_BATCH_PIXELS:
            break
        selected.append(entry); raw_images.append((raw, pixels))
        total_bytes += len(raw); total_pixels += pixels
        if len(selected) == MAX_PICTURES:
            break
    return tuple(selected), raw_images, fallback


def _apply(draft, assets, incarnation, request):
    """All validation precedes immutable receipt updates; no partial success."""
    draft, entries, identity = _manifest(draft, incarnation)
    expected, chosen, left = request['identity'], request['entries'], request['left']
    if not draft.prepared_by.strip() or identity != expected or not 0 < len(chosen) <= MAX_PICTURES:
        raise ValueError('The report or picture review changed. Review the current pictures again.')
    blocked = _blocked(draft, entries)
    if (len(set(chosen)) != len(chosen) or any(e not in entries or not _eligible(draft, e) for e in chosen)
            or any(e not in chosen for e in left) or any(e[0] in blocked for e in chosen)):
        raise ValueError('The selected picture review is no longer current.')
    counts = Counter(e[2] for e in entries)
    total_bytes = total_pixels = 0
    for entry in chosen:
        if counts[entry[2]] != 1:
            raise ValueError('An ambiguous picture occurrence needs individual review.')
        raw, pixels = _read_picture(draft, assets, entry)
        total_bytes += len(raw); total_pixels += pixels
    if total_bytes > MAX_BATCH_BYTES or total_pixels > MAX_BATCH_PIXELS:
        raise ValueError('The picture review exceeds its safe display budget.')
    blocks = {b.key: b for b in draft.blocks}
    for entry in chosen:
        if entry not in left:
            blocks[entry[0]] = approve_asset(blocks[entry[0]], entry[1])
    return replace(draft, blocks=tuple(blocks[b.key] for b in draft.blocks))


def _queue(prefix, envelope, widget_keys):
    active = prefix + '_picture_batch_active'
    if st.session_state.get(active) != envelope:
        return
    if len(widget_keys) != len(envelope['entries']) or len(set(widget_keys)) != len(widget_keys):
        return
    if any(key not in st.session_state for key in widget_keys):
        return
    values = [st.session_state[key] for key in widget_keys]
    if any(type(value) is not bool for value in values):
        return
    st.session_state[prefix + '_picture_batch_request'] = {
        **envelope, 'left': tuple(e for e, value in zip(envelope['entries'], values) if value)}
    st.session_state.pop(active, None)  # Single-use; a delayed second click has no authority.


def review_picture_batch(draft, assets, prefix, field, *, incarnation):
    """Six fully displayed pictures per explicit confirmation, with opt-outs."""
    draft, entries, identity = _manifest(draft, incarnation)
    deferred_key = prefix + '_picture_batch_deferred'
    deferred = st.session_state.get(deferred_key, ())
    request = st.session_state.pop(prefix + '_picture_batch_request', None)
    if request is not None:
        try:
            draft = _apply(draft, assets, incarnation, request)
        except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
            st.warning('Those pictures changed or could not be checked. Nothing was marked ready; review them again.')
        else:
            deferred = tuple(set((*deferred, *(e[2] for e in request['left']))))
            st.session_state[deferred_key] = deferred
        draft, entries, identity = _manifest(draft, incarnation)
    selected, raw_images, fallback = _choose(draft, assets, entries, deferred)
    active_key = prefix + '_picture_batch_active'
    if selected:
        active = st.session_state.get(active_key)
        if not active or active['identity'] != identity or active['entries'] != selected:
            active = {'identity': identity, 'entries': selected, 'nonce': uuid4().hex}
        st.session_state.pop(active_key, None)
        st.markdown(f'**Check these {len(selected)} pictures**')
        st.caption(f'{draft.profile.title} · {draft.period.label}')
        st.caption('Check every picture below for the selected sites and for visible prices, private information, or legal-only, blank or signature-only pages. Leave any doubtful picture for correction.')
        from app.monthly_report_sections import readable_label
        keys = []
        displayed = True
        with st.form(prefix + '_picture_batch_' + active['nonce'], clear_on_submit=False):
            for n, (entry, (raw, _)) in enumerate(zip(selected, raw_images), 1):
                st.markdown(f'**{n}. {readable_label(entry[0])} · picture {entry[1] + 1}**')
                if entry[4]:
                    st.caption(entry[4])
                block = next(b for b in draft.blocks if b.key == entry[0])
                for source in draft.sources:
                    if any(ref.startswith(source.id + ':') for ref in asset_context(block, entry[1])):
                        st.caption(' · '.join(filter(None, (source.filename, source.facility, source.service_date))))
                try:
                    st.image(raw, width='stretch')
                except (ValueError, OSError):
                    displayed = False
                    st.warning('This picture could not be displayed. Use individual review below.')
                    fallback.add(entry[0])
                key = prefix + '_picture_leave_' + active['nonce'] + '_' + str(n)
                keys.append(key)
                st.checkbox('Leave for correction', key=key)
            if displayed:
                st.session_state[active_key] = active
            st.form_submit_button(f'Confirm these {len(selected)} pictures are ready (except those left for correction)',
                                  disabled=not displayed or not draft.prepared_by.strip(),
                                  on_click=_queue, args=(prefix, active, tuple(keys)))
        pending_count = sum(len(pending_asset_indexes(b)) for b in draft.blocks if b.key in used_block_keys(draft) and b.source != 'Omit')
        if pending_count > len(selected):
            st.caption(f'{pending_count - len(selected)} other pictures still need review. The next group appears after confirmation.')
    else:
        st.session_state.pop(active_key, None)
    # Do not hand unreadable/unbounded rasters to the compatibility reviewer:
    # its st.image call is not proof of a successful full raster decode.
    unsafe = set()
    for entry in entries:
        if entry[0] not in fallback:
            continue
        try:
            _read_picture(draft, assets, entry)
        except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
            unsafe.add(entry[0])
    if unsafe:
        st.warning('Some pictures cannot be safely displayed here. Replace or resize them in their report sections; they remain unapproved.')
        fallback.difference_update(unsafe)
    scope_key = prefix + '_picture_individual_scope'
    if fallback:
        # A fresh, non-reusable namespace isolates legacy session receipts.
        # Keep it only while this exact pending context remains current.
        signature = (identity, tuple(e for e in entries if e[0] in fallback
                     and e[1] in pending_asset_indexes(next(b for b in draft.blocks if b.key == e[0]))),
                     tuple(sorted(deferred)))
        scope = st.session_state.get(scope_key)
        if not scope or scope[0] != signature:
            scope = (signature, uuid4().hex)
            st.session_state[scope_key] = scope
        from app.monthly_report_editor import review_client_images
        st.caption('These pictures need the individual review controls; they were not approved with the group.')
        subset = replace(draft, blocks=tuple(b for b in draft.blocks if b.key in fallback))
        reviewed = review_client_images(subset, assets, prefix + '_picture_individual_' + scope[1], field)
        updates = {b.key: b for b in reviewed.blocks}
        draft = replace(draft, blocks=tuple(updates.get(b.key, b) for b in draft.blocks))
    else:
        st.session_state.pop(scope_key, None)
    if not selected and not fallback and not unsafe:
        st.caption('All included pictures are ready. Change pictures in their report sections if needed.')
    return draft
