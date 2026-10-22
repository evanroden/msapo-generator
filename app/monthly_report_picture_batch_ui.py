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


def _unique_blocks(draft):
    return len({b.key for b in draft.blocks}) == len(draft.blocks)


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
    if not _unique_blocks(draft):
        raise ValueError('Repeated section identifiers need correction before picture review.')
    pending = tuple(e for e in entries if e[1] in pending_asset_indexes(next(b for b in draft.blocks if b.key == e[0])))
    counts = Counter(e[2] for e in entries)
    fallback = _blocked(draft, entries)
    fallback.update(e[0] for e in pending if counts[e[2]] != 1 or not _eligible(draft, e))
    selected, raw_images = [], []
    total_bytes = total_pixels = 0
    for entry in pending:
        if entry[0] in fallback or entry[2] in deferred:
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
    # Deferred occurrences do not prevent reviewing later valid pictures.
    # Offer their correction controls only after ordinary pending groups.
    fallback.update(e[0] for e in pending if e[2] in deferred)
    return tuple(selected), raw_images, fallback


def _apply(draft, assets, incarnation, request):
    """All validation precedes immutable receipt updates; no partial success."""
    if not _unique_blocks(draft):
        raise ValueError('Repeated section identifiers need correction before picture review.')
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


def _queue_component(prefix, envelope, key):
    state = st.session_state.get(key)
    value = state.get('submission') if isinstance(state, dict) else None
    if st.session_state.get(prefix + '_picture_batch_active') != envelope or not isinstance(value, dict):
        return
    if value.get('identity') != envelope['identity'] or value.get('nonce') != envelope['nonce']:
        return
    count = len(envelope['entries'])
    left, loaded = value.get('left'), value.get('loaded')
    if (not isinstance(left, list) or not isinstance(loaded, list) or len(left) != count or len(loaded) != count
            or any(type(x) is not bool for x in left) or any(x is not True for x in loaded)):
        return
    st.session_state[prefix + '_picture_batch_request'] = {
        **envelope, 'left': tuple(e for e, value in zip(envelope['entries'], left) if value)}
    st.session_state.pop(prefix + '_picture_batch_active', None)


def _queue_remove(prefix, envelope, entry):
    if st.session_state.get(prefix + '_picture_remove_active') != envelope or entry not in envelope['entries']:
        return
    st.session_state[prefix + '_picture_remove_request'] = (envelope, entry)
    st.session_state.pop(prefix + '_picture_remove_active', None)


def _next_correction(prefix, envelope, target):
    if (st.session_state.get(prefix + '_picture_correction_active') != envelope
            or target not in envelope['entries']):
        return
    st.session_state[prefix + '_picture_correction_cursor'] = (envelope['identity'], target)
    for suffix in ('_picture_correction_active', '_picture_batch_active', '_picture_remove_active',
                   '_picture_batch_request', '_picture_remove_request'):
        st.session_state.pop(prefix + suffix, None)


def _render_group(prefix, envelope, pictures):
    from app.monthly_report_picture_group import PictureMediaError, render_group
    key = prefix + '_picture_component_' + envelope['nonce']
    try:
        render_group(key=key, envelope=envelope, pictures=pictures, media_scope=prefix,
                     on_change=lambda: _queue_component(prefix, envelope, key))
    except PictureMediaError:
        st.session_state.pop(prefix + '_picture_batch_active', None)
        st.warning('These pictures could not be displayed. They remain pending; retry on the next review or use Correction controls below. Your other edits can still save.')


def review_picture_batch(draft, assets, prefix, field, *, incarnation):
    """Bounded browser-decoded pictures per explicit confirmation, with opt-outs."""
    if not _unique_blocks(draft):
        for suffix in ('_picture_batch_active', '_picture_batch_request',
                       '_picture_remove_active', '_picture_remove_request',
                       '_picture_correction_active', '_picture_correction_cursor'):
            st.session_state.pop(prefix + suffix, None)
        st.warning('Repeated section identifiers need correction before pictures can be reviewed or removed here. Your pictures and other edits are unchanged.')
        return draft
    draft, entries, identity = _manifest(draft, incarnation)
    removal = st.session_state.pop(prefix + '_picture_remove_request', None)
    if removal is not None:
        st.session_state.pop(prefix + '_picture_correction_cursor', None)
        envelope, entry = removal
        if envelope['identity'] == identity and entry in entries:
            from app.monthly_report_saved_pictures_ui import remove_saved_picture
            draft = replace(draft, blocks=tuple(remove_saved_picture(b, entry[1]) if b.key == entry[0] else b for b in draft.blocks))
            draft, entries, identity = _manifest(draft, incarnation)
    deferred_key = prefix + '_picture_batch_deferred'
    deferred = st.session_state.get(deferred_key, ())
    request = st.session_state.pop(prefix + '_picture_batch_request', None)
    if request is not None:
        st.session_state.pop(prefix + '_picture_correction_cursor', None)
        try:
            draft = _apply(draft, assets, incarnation, request)
        except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
            st.warning('Those pictures changed or could not be checked. Nothing was marked ready; review them again.')
        else:
            left_fingerprints = tuple(e[2] for e in request['left'])
            # Re-deferring a correction moves it behind the other deferred
            # occurrences, so no doubtful first picture traps navigation.
            deferred = tuple(fp for fp in deferred if fp not in left_fingerprints) + left_fingerprints
            st.session_state[deferred_key] = deferred
        draft, entries, identity = _manifest(draft, incarnation)
    selected, raw_images, fallback = _choose(draft, assets, entries, deferred)
    correction_entries = selected
    # Never decode an entire fallback block, including its approved pictures.
    # After ordinary groups, inspect just one current pending picture, using
    # the same strict browser and server gates. Unsupported pictures stay
    # removable via the unchanged removal helper, including cover artwork.
    correction_navigation = None
    if not selected and fallback:
        pending_corrections = [e for e in entries if e[0] in fallback and
                               e[1] in pending_asset_indexes(next(b for b in draft.blocks if b.key == e[0]))]
        deferred_order = {fp: i for i, fp in enumerate(deferred)}
        pending_corrections.sort(key=lambda e: deferred_order.get(e[2], -1))
        cursor = st.session_state.get(prefix + '_picture_correction_cursor')
        current = (cursor[1] if cursor and cursor[0] == identity and cursor[1] in pending_corrections
                   else next(iter(pending_corrections), None))
        if len(pending_corrections) > 1:
            correction_navigation = (tuple(pending_corrections), current)
        if current:
            correction_entries = (current,)
            counts = Counter(e[2] for e in entries)
            if current[0] not in _blocked(draft, entries) and _eligible(draft, current) and counts[current[2]] == 1:
                try:
                    raw, pixels = _read_picture(draft, assets, current)
                except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
                    st.warning('This picture cannot be safely displayed here. Replace or resize it in its section, or remove it from this draft below.')
                else:
                    selected, raw_images = (current,), [(raw, pixels)]
            else:
                st.warning('This picture needs source or occurrence correction. Correct it in its section, or remove it from this draft below.')
    navigation_key = prefix + '_picture_correction_active'
    if correction_navigation:
        candidates, current = correction_navigation
        navigation = st.session_state.get(navigation_key)
        if (not navigation or navigation['identity'] != identity
                or navigation['entries'] != candidates or navigation['current'] != current):
            navigation = {'identity': identity, 'entries': candidates, 'current': current, 'nonce': uuid4().hex}
        st.session_state[navigation_key] = navigation
        target = candidates[(candidates.index(current) + 1) % len(candidates)]
        st.button('Next picture to correct', key=prefix + '_picture_next_' + navigation['nonce'],
                  on_click=_next_correction, args=(prefix, navigation, target))
        st.caption('Moving to another picture does not mark this one ready or remove it.')
    else:
        st.session_state.pop(navigation_key, None)
    active_key = prefix + '_picture_batch_active'
    if selected:
        active = st.session_state.get(active_key)
        if not active or active['identity'] != identity or active['entries'] != selected:
            active = {'identity': identity, 'entries': selected, 'nonce': uuid4().hex}
        st.session_state[active_key] = active
        st.markdown('**Check this picture**' if len(selected) == 1 else f'**Check these {len(selected)} pictures**')
        st.caption(f'{draft.profile.title} · {draft.period.label}')
        st.caption('Inspect every picture for the selected sites and for visible prices, private information, or legal-only, blank or signature-only pages. Leave doubtful pictures for correction.')
        from app.monthly_report_sections import readable_label
        pictures = []
        for n, (entry, (raw, _)) in enumerate(zip(selected, raw_images), 1):
            block = next(b for b in draft.blocks if b.key == entry[0])
            context = [entry[4]]
            for source in draft.sources:
                if any(ref.startswith(source.id + ':') for ref in asset_context(block, entry[1])):
                    context.append(' · '.join(filter(None, (source.filename, source.facility, source.service_date))))
            pictures.append((raw, f'{n}. {readable_label(entry[0])} · picture {entry[1] + 1}', ' · '.join(filter(None, context))))
        _render_group(prefix, active, pictures)
    else:
        st.session_state.pop(active_key, None)
    remove_key = prefix + '_picture_remove_active'
    if correction_entries:
        removal_active = st.session_state.get(remove_key)
        if not removal_active or removal_active['identity'] != identity or removal_active['entries'] != correction_entries:
            removal_active = {'identity': identity, 'entries': correction_entries, 'nonce': uuid4().hex}
        st.session_state[remove_key] = removal_active
        with st.expander('Correction controls', expanded=not bool(selected)):
            st.caption('Removing changes this draft only; the saved original stays intact.')
            for entry in correction_entries:
                st.button(f'Remove picture {entry[1] + 1} from {entry[0].replace("_", " ")}',
                          key=prefix + '_picture_remove_' + removal_active['nonce'] + '_' + entry[0] + '_' + str(entry[1]),
                          on_click=_queue_remove, args=(prefix, removal_active, entry))
    else:
        st.session_state.pop(remove_key, None)
    pending_count = sum(len(pending_asset_indexes(b)) for b in draft.blocks if b.key in used_block_keys(draft) and b.source != 'Omit')
    if pending_count > len(selected):
        remaining = pending_count - len(selected)
        noun = 'picture still needs' if remaining == 1 else 'pictures still need'
        st.caption(f'{remaining} other {noun} review. The next group appears after confirmation.')
    elif not pending_count:
        st.caption('All included pictures are ready. Change pictures in their report sections if needed.')
    return draft
