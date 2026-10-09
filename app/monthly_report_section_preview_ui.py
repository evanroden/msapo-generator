"""Viewport-driven section previews with bounded work and disposable shared cache."""
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from time import monotonic
from uuid import uuid4

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_render_jobs import RenderBusy
from app.monthly_report_preview import (
    _section_scope, preview_page, preview_section, section_preview_fingerprint,
)
from app.monthly_report_preview_store import STORE, PreviewTicket
from app.monthly_report_preview_view import render_view, viewport


PREVIEW_HEIGHT = 760
# Only lightweight tickets live in session state. PDFs and visible page rasters
# are bounded across all visitors by STORE, rather than once for each session.
ORDERED_CACHE_BYTES = 256 * 1024
DEBOUNCE_SECONDS = 1.5
_PREVIEW_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix='report-preview')
_PREVIEW_SLOT = BoundedSemaphore(1)


def _build_preview_entry(draft, section_key, assets, title, owner=None):
    def loader(ref):
        return assets.get(ref) or library.read_asset(draft.profile.contract, draft.profile.key, ref)
    try:
        preview = preview_section(draft, section_key, loader)
        ticket = STORE.put(owner or uuid4().hex, preview)
        return {'ticket': ticket, 'pages': ticket.pages}
    except RenderBusy:
        return {'busy': True}
    except Exception as exc:
        return {'error': str(exc) if isinstance(exc, ValueError) else
                'The section preview could not update. Your edits are still here. Retry the preview when ready.'}
    finally:
        _PREVIEW_SLOT.release()


def _discard(state, entry):
    if isinstance(entry.get('ticket'), PreviewTicket):
        STORE.discard(state.get('owner'), entry['ticket'])


def _bound_ordered_preview_cache(state):
    cache = state['cache']
    # Drop legacy raster/PDF copies, including oversized single entries. Cache
    # eviction is a cache miss, never a permanent "render failed" result.
    for key, entry in list(cache.items()):
        if 'html' in entry or 'preview' in entry:
            del cache[key]
    while len(cache) > 16 or sum(len(str(value)) for value in cache.values()) > ORDERED_CACHE_BYTES:
        key = next(iter(cache))
        _discard(state, cache.pop(key))


def _is_visible(state, section):
    # Pure queue callers predating viewport tracking do not have this mapping.
    return state.get('visible', {}).get(section, 'visible' not in state)


def _advance_preview_queue(state):
    running = state.get('running')
    if running and running[2].done():
        section, fingerprint, future = running
        try:
            entry = future.result()
        except Exception:
            entry = {'error': 'The section preview could not update. Your edits are still here.'}
        if state['wanted'].get(section) == fingerprint:
            if entry.get('busy'):
                request = state.get('running_request')
                if request is not None and _is_visible(state, section):
                    state['queue'].setdefault(section, request)
                    state['retry_after'] = monotonic() + 2
            else:
                previous = state['cache'].pop(section, {})
                _discard(state, previous)
                state['cache'][section] = {'fingerprint': fingerprint, **entry}
        else:
            _discard(state, entry)
        state['running'] = None
        state.pop('running_request', None)
        _bound_ordered_preview_cache(state)
    for section, request in list(state['queue'].items()):
        if state['wanted'].get(section) != request[0] or not _is_visible(state, section):
            del state['queue'][section]
    if state.get('running') or not state['queue'] or monotonic() < state.get('retry_after', 0):
        return
    ready = next((section for section in state['queue']
                  if monotonic() >= state.get('ready_after', {}).get(section, 0)), None)
    if ready is None or not _PREVIEW_SLOT.acquire(blocking=False):
        return
    fingerprint, draft, assets, title = state['queue'].pop(ready)
    try:
        future = _PREVIEW_WORKER.submit(_build_preview_entry, draft, ready, assets, title,
                                        state.setdefault('owner', uuid4().hex))
    except Exception:
        _PREVIEW_SLOT.release()
        state['cache'][ready] = {'fingerprint': fingerprint, 'error': 'The preview could not start. Your edits are still here.'}
    else:
        state['running'] = (ready, fingerprint, future)
        state['running_request'] = (fingerprint, draft, assets, title)


def _ordered_preview_state(prefix):
    st.session_state.pop(prefix + '_section_preview_cache', None)
    state = st.session_state.setdefault(prefix + '_ordered_previews', {
        'wanted': {}, 'queue': {}, 'cache': {}, 'running': None,
    })
    for name in ('visible', 'requests', 'page_requests', 'ready_after', 'timers'):
        state.setdefault(name, {})
    state.setdefault('owner', uuid4().hex)
    _bound_ordered_preview_cache(state)
    return state


def _current_entry(state, section):
    entry = state['cache'].get(section)
    if entry and entry.get('fingerprint') == state['wanted'].get(section):
        if entry.get('error') or STORE.available(state['owner'], entry.get('ticket')):
            return entry
        _discard(state, state['cache'].pop(section))
    return None


def _enqueue_visible(state, section):
    if not state['visible'].get(section) or _current_entry(state, section):
        return
    running = state.get('running')
    if running and running[:2] == (section, state['wanted'].get(section)):
        return
    request = state['requests'].get(section)
    if request is not None:
        state['queue'][section] = request


def _pending(state, section):
    return bool(state['visible'].get(section) and (section in state['queue'] or
                state.get('running') and state['running'][0] == section))


def _viewport_changed(prefix, section, widget_key):
    state = _ordered_preview_state(prefix)
    value = st.session_state.get(widget_key, {})
    view = viewport(value.get('viewport'), state['wanted'].get(section)) if isinstance(value, dict) else None
    if view is None:
        return
    state['visible'][section] = view['visible']
    state['page_requests'][section] = view
    if not view['visible']:
        state['queue'].pop(section, None)
    else:
        _enqueue_visible(state, section)


def _render_ordered_preview(section_key, prefix, title):
    state = _ordered_preview_state(prefix)
    _enqueue_visible(state, section_key)
    _advance_preview_queue(state)
    pending = _pending(state, section_key)
    if state['timers'].get(section_key, False) != pending:
        state['timers'][section_key] = pending
        # Install/remove this visible pane's timer once. Offscreen sections have
        # neither conversion jobs nor recurring two-second fragment reruns.
        st.rerun(scope='app')
    entry = _current_entry(state, section_key)
    st.subheader('Section preview')
    st.caption(title + ' · Updates automatically while in view.')
    images, ticket = (), None
    status = 'Preparing this section’s preview… You can keep editing.' if pending else ''
    if entry and entry.get('error'):
        st.warning(entry['error'])
        if st.button('Retry preview', key=prefix + '_ordered_retry_' + section_key):
            _discard(state, state['cache'].pop(section_key))
            state['ready_after'][section_key] = 0
            _enqueue_visible(state, section_key)
            st.rerun(scope='app')
    elif entry:
        ticket = entry['ticket']
        view = state['page_requests'].get(section_key, {'pages': (0,), 'dpi': 120})
        if state['visible'].get(section_key):
            indexes = tuple(index for index in view['pages'] if index < ticket.pages) or (0,)
            try:
                images = STORE.pages(state['owner'], ticket, indexes, dpi=view['dpi']) or ()
            except (ValueError, OSError):
                status = 'This page preview is temporarily unavailable. Your edits are still here.'
    widget_key = prefix + '_preview_surface_' + section_key
    render_view(key=widget_key, generation=state['wanted'].get(section_key, ''), title=title,
                ticket=ticket, images=images, status=status,
                on_change=lambda: _viewport_changed(prefix, section_key, widget_key))


def _request_scope(draft, section_key, assets):
    """Do not pin unrelated uploads or complete source packets in queued work."""
    from dataclasses import replace
    from app.monthly_report_model import used_asset_references
    scope, _ = _section_scope(draft, section_key)
    references = {ref for block in scope.blocks for ref in (
        *block.references, *(table.reference for table in block.extra_tables),
        *(ref for paragraph in block.ai_paragraphs for ref in paragraph.references))}
    references.update(ref for item in scope.follow_ups for ref in item.references)
    fact_ids = {fact for block in scope.blocks for paragraph in block.ai_paragraphs for fact in paragraph.fact_ids}
    sources = tuple(source for source in scope.sources if any(
        ref == source.id or ref.startswith(source.id + ':') for ref in references)
        or any(fact.id in fact_ids for fact in source.facts))
    scope = replace(scope, sources=sources)
    used = used_asset_references(scope)
    return scope, {ref: assets[ref] for ref in used if ref in assets}


def render_ordered_section_preview(draft, section_key, assets, prefix):
    title = 'Cover' if section_key == 'cover' else next(
        (section.title for section in draft.sections if section.key == section_key), 'Report section')
    state = _ordered_preview_state(prefix)
    try:
        fingerprint = section_preview_fingerprint(draft, section_key)
    except Exception:
        st.warning('The section preview is unavailable. Your edits are still here.')
        return None
    prior = state['wanted'].get(section_key)
    if prior != fingerprint:
        state['wanted'][section_key] = fingerprint
        _discard(state, state['cache'].pop(section_key, {}))
        state['queue'].pop(section_key, None)
        scope, needed_assets = _request_scope(draft, section_key, assets)
        state['requests'][section_key] = (fingerprint, scope, needed_assets, title)
        state['ready_after'][section_key] = monotonic() + DEBOUNCE_SECONDS if prior else 0
    _enqueue_visible(state, section_key)
    _advance_preview_queue(state)
    pending = _pending(state, section_key)
    state['timers'][section_key] = pending
    st.fragment(run_every='2s' if pending else None)(_render_ordered_preview)(section_key, prefix, title)
    return None


def render_section_preview(draft, section_key, assets, prefix, *, deferred=False):
    # Legacy single-section callers use the same scheduler, not a second
    # synchronous converter/cache that bypasses the resource limits.
    return render_ordered_section_preview(draft, section_key, assets, prefix)
