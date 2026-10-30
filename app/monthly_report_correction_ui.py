"""Exact Review links into existing native picture-caption editors."""
from hashlib import sha256
from html import escape
import streamlit as st
from app.monthly_report_correction_targets import picture_target, resolve_target


def _identity(prefix):
    return sha256(prefix.encode()).hexdigest()[:24]


def marker_id(prefix, target):
    return 'report-correction-' + sha256((prefix + '\0' + (target.navigation_key or target.token)).encode()).hexdigest()


def picture_marker(draft, block, index, prefix, caption_key):
    target = picture_target(draft, block, index)
    return ('<span class="enfra-picture-correction" id="' + marker_id(prefix, target) +
        '" data-report-identity="' + _identity(prefix) + '" data-field-key="' +
        escape(caption_key, quote=True) + '" aria-hidden="true"></span>')


def render_picture_links(check, draft, prefix):
    specs = {b.key: b for section in draft.sections if section.included for b in section.blocks}
    links = []
    for target in check.targets:
        resolved = resolve_target(draft, target)
        if resolved is None:
            continue
        block, index, source = resolved
        spec = specs.get(block.key) if block else None
        # Source-page approvals are owned by the source workspace, not the
        # photo-caption editor. Never advertise a nearby substitute editor.
        if source is not None or not spec or spec.type != 'image_grid':
            continue
        links.append('<a class="enfra-picture-correction-link" data-report-identity="' +
            _identity(prefix) + '" href="#' + marker_id(prefix, target) + '">Edit photo ' +
            str(index + 1) + '</a>')
    if links:
        st.markdown(' · '.join(links), unsafe_allow_html=True)


def _queue_source_page(prefix, target, scope):
    from app.monthly_report_page_navigation import queue_navigation
    draft = st.session_state.get(prefix + '_draft')
    if draft is not None:
        queue_navigation(st.session_state, prefix, draft,
            st.session_state.get(prefix + '_evidence', ()), target, scope)


def _queue_manager_page(prefix, target, scope):
    from app.monthly_report_manager_page_navigation import queue_navigation
    draft = st.session_state.get(prefix + '_draft')
    if draft is not None:
        queue_navigation(st.session_state, prefix, draft,
            st.session_state.get(prefix + '_evidence', ()), target, scope, source_review=True)


def render_source_page_links(check, draft, prefix):
    # Financial source pages have a separate attestation owner and policy.
    if check.code != "client_source_page":
        return
    from app.monthly_report_page_navigation import _water_target
    from app.monthly_report_manager_page_navigation import manager_target, unavailable_reason
    from app.monthly_report_guided import _rich_text_scope
    contents = st.session_state.get(prefix + '_evidence', ())
    for target in check.targets:
        resolved = _water_target(draft, contents, target)
        callback = _queue_source_page
        label = "Review"
        if resolved is None:
            resolved = manager_target(draft, contents, target, source_review=check.code == "client_source_page")
            callback, label = _queue_manager_page, "Open"
        if resolved is None:
            reason = unavailable_reason(draft, contents, target, source_review=check.code == "client_source_page")
            if reason:
                st.caption(reason)
            continue
        _, index, _ = resolved
        with st.container(key='monthly_source_warning_' + target.token + '_' + check.code):
            st.markdown('<span class="enfra-source-warning" data-source-id="' +
                escape(target.source_id, quote=True) + '" data-report-identity="' +
                _identity(prefix) + '"' + (' data-navigation-owner="exact-manager-page"'
                    if callback == _queue_manager_page else '') + '></span>', unsafe_allow_html=True)
            if callback == _queue_manager_page:
                st.caption('Source-page selection and review are shared; each report caption and picture review stays separate.')
            st.button(f'{label} source page {target.page} · picture {index + 1}',
                key=prefix + '_page_correction_' + target.token + '_' + check.code,
                on_click=callback, args=(prefix, target, _rich_text_scope(prefix)))
