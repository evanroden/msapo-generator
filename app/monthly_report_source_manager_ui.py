"""One source manager, with direct re-entry for specific file problems."""
from dataclasses import replace

import streamlit as st

from app.monthly_report_source_status import source_manager_status
from app.monthly_report_upload_ui import render_uploads
from app.monthly_report_model import used_source_ids


def _open_manager(manager_key, selection_key, source_id):
    st.session_state[manager_key] = True
    if source_id:
        st.session_state[selection_key] = source_id


def _pending_source_selection(prefix):
    """A single unsettled file task, independent of the number of old sources."""
    evidence = prefix + "_evidence"
    return bool(st.session_state.get(evidence + "_pending_acceptance")
                or st.session_state.get(evidence + "_accepted_failure")
                or any(value for key, value in st.session_state.items()
                       if key.startswith(evidence + "_structured_")
                       and key.endswith(("_job", "_pending"))))


def _source_status_caption(states, pending):
    """Show one global pending task without manufacturing N file corrections."""
    count = len(states)
    if pending:
        if not count:
            return "Finish current file selection"
        return f"{count} source {'file' if count == 1 else 'files'} · Finish current file selection"
    if not count:
        return ""
    attention = sum(item.needs_correction for item in states)
    return (f"{count} source {'file' if count == 1 else 'files'}" +
            (f" · {attention} need details" if attention else ""))


def _statuses(draft, blocks, prefix):
    evidence = prefix + "_evidence"
    return source_manager_status(replace(draft, blocks=tuple(blocks.values())),
        st.session_state.get(evidence, ()),
        unavailable=st.session_state.get(prefix + "_unavailable_sources", ()),
        pending=_pending_source_selection(prefix))


def open_source_review(prefix, source_id, target, page=None):
    """Native navigation callback; no source or report content changes."""
    from uuid import uuid4
    _open_manager(prefix + "_batch_files_open", prefix + "_evidence_selected", source_id)
    st.session_state[prefix + "_source_review_target"] = (source_id, target, uuid4().hex)
    if type(page) is int and page > 0:
        st.session_state[prefix + "_evidence_" + source_id + "_page"] = page
    st.session_state[prefix + "_source_review_context"] = source_id


def render_guided_source_manager(draft, blocks, prefix, field, apply_prepared, keep_missing, *,
                                 assets=None, table_columns=None):
    """One stable source workspace; hiding never retires buffered native forms."""
    from html import escape
    from hashlib import sha256
    from app.monthly_report_guided import _current_source_detail, _forget_block_widgets
    from app.monthly_report_source_scope import artwork_scope_keys
    from app.monthly_report_source_details import detail_problems
    from app.monthly_report_upload_ui import (
        render_source_details, render_structured_uploads, render_workorder_metrics,
        _remember_delivered_source_edit,
    )
    st.session_state[prefix + "_source_native_changes"] = {}
    selection_key = prefix + "_evidence_selected"
    active_key = prefix + "_source_active_selected"
    pending = _pending_source_selection(prefix)
    states = _statuses(draft, blocks, prefix)
    # First-file intake is immediately available. Seed only once so an explicit
    # Done remains respected, including on empty reports and interrupted work.
    manager_key = field(prefix + "_batch_files_open", not states)
    status_key = prefix + "_source_manager_resolution"
    previous = st.session_state.get(status_key)
    resolution = {item.source_id: item.resolved for item in states}
    # Acceptance can be consumed by the Activity editor before this renderer.
    # Compare the prior render so completion does not require an extra Done.
    # Reopening an already resolved file never triggers this transition.
    if (isinstance(previous, dict) and previous.keys() == resolution.keys()
            and not all(previous.values()) and resolution and all(resolution.values())):
        st.session_state[manager_key] = False
    opened = bool(st.session_state[manager_key])
    with st.container(key=prefix + "_source_file_status"):
        status_line = _source_status_caption(states, pending)
        if status_line:
            st.caption(status_line)
    st.button("Done with source files" if opened else "Manage source files",
              key=prefix + "_source_manager_" + str(opened),
              on_click=_open_manager if not opened else _close_manager,
              args=(manager_key, selection_key, "") if not opened else (manager_key,))
    panel_key = prefix + "_source_manager_panel"
    # Keep child keys and delta paths stable. Native form buffers are not sent
    # by an unrelated file-selection click and cannot be reconstructed in Python.
    st.markdown('<style>.st-key-' + panel_key + '{display:' + ("block" if opened else "none") +
                ';}</style>', unsafe_allow_html=True)
    with st.container(key=panel_key):
        st.markdown('<span class="enfra-source-correction-owner" data-report-identity="' +
                    sha256(prefix.encode()).hexdigest()[:24] + '" aria-hidden="true"></span>',
                    unsafe_allow_html=True)
        entry_sources = draft.sources
        before_sources = {source.id: source.fingerprint for source in draft.sources}
        before_sources.update((content.source.id, content.source.fingerprint)
                              for content in st.session_state.get(prefix + "_evidence", ()))
        before_ids = set(before_sources)
        has_activity = any(section.key == "activity" for section in draft.sections)
        if has_activity:
            sources, additions, _ = render_structured_uploads(
                draft.profile, draft.period, prefix, field, "activity_summary", blocks=blocks,
                assets=assets, table_columns=table_columns, managed=True)
        else:
            sources, additions = draft.sources, {}
        draft = replace(draft, sources=keep_missing(prefix, sources))
        if additions:
            from app.monthly_report_guided import merge_blocks, _advance_rich_text_receipt
            for key, block in additions.items():
                previous = blocks.get(key)
                blocks[key] = merge_blocks(blocks.get(key), block) if key == "improvements" else block
                _advance_rich_text_receipt(prefix, previous, blocks[key])
            _forget_block_widgets(prefix, additions)
        contents = st.session_state.get(prefix + "_evidence", ())
        ordered = {source.id: source for source in draft.sources}
        ordered.update((content.source.id, content.source) for content in contents)
        ids = tuple(ordered)
        shown_page = []
        if ids:
            fresh = tuple(identity for identity in ids if identity not in before_ids)
            field(selection_key, ids[0])
            if fresh:
                st.session_state[selection_key] = fresh[0]
            if st.session_state[selection_key] not in ordered:
                st.session_state[selection_key] = ids[0]
            requested = st.selectbox("File to review", ids,
                format_func=lambda identity: ordered[identity].filename, key=selection_key)
            selected = st.session_state.setdefault(active_key, requested)
            if selected not in ordered:
                selected = requested
                st.session_state[active_key] = selected
            current = replace(draft, blocks=tuple(blocks.values()))
            included = used_source_ids(current)
            corrected = {}
            for source in ordered.values():
                source = _current_source_detail(source, contents)
                owner_key = prefix + "_managed_source_" + source.id
                st.markdown('<style>.st-key-' + owner_key + '{display:' +
                            ("block" if source.id == selected else "none") + ';}</style>',
                            unsafe_allow_html=True)
                with st.container(key=owner_key):
                    st.markdown('<a class="enfra-source-review-return" data-source-id="' +
                                escape(source.id, quote=True) + '" href="#report-review" hidden>Return to review</a>',
                                unsafe_allow_html=True)
                    def source_preview(source_id=source.id):
                        if not opened or selected != source_id or st.session_state.get(prefix + "_source_review_context") != source_id:
                            return
                        content = next((item for item in contents if item.source.id == source_id), None)
                        if content is None:
                            st.caption("This original is unavailable. Re-upload its unchanged file to inspect this page.")
                            return
                        page = st.session_state.get(prefix + "_evidence_" + source_id + "_page", 1)
                        from app.monthly_report_page_context_ui import render_correction_page
                        shown = render_correction_page(draft.profile, content, page)
                        if shown is not None:
                            shown_page.append(shown)
                    corrected[source.id] = render_source_details(
                        source, draft.profile, prefix + "_evidence_" + source.id, field,
                        artwork_keys=artwork_scope_keys(current, source.id), manager_owner=True,
                        source_preview=source_preview,
                        compact_problems=detail_problems(source, draft.profile, draft.period,
                            in_report=source.id in included, draft=current))
                    _remember_delivered_source_edit(prefix, source, corrected[source.id])
                    target = st.session_state.get(prefix + "_source_review_target")
                    if target and target[0] == selected == source.id:
                        st.markdown('<span class="enfra-source-review-target" data-source-id="' +
                            escape(source.id, quote=True) + '" data-field="' + escape(target[1], quote=True) +
                            '" data-token="' + escape(target[2], quote=True) + '"></span>', unsafe_allow_html=True)
            contents = tuple(replace(content, source=corrected.get(content.source.id, content.source))
                             for content in contents)
            st.session_state[prefix + "_evidence"] = contents
            st.session_state[prefix + "_unavailable_sources"] = tuple(
                corrected.get(source.id, source)
                for source in st.session_state.get(prefix + "_unavailable_sources", ()))
            draft = replace(draft, sources=tuple(corrected.get(source.id, source) for source in draft.sources))
            selected_status = next((item for item in _statuses(draft, blocks, prefix)
                                    if item.source_id == selected), None)
            if selected_status and not _pending_source_selection(prefix):
                if selected_status.needs_correction:
                    st.caption(selected_status.reason)
                elif selected_status.summary:
                    st.caption(selected_status.filename + " · " + selected_status.summary)
        else:
            selected = requested = None
        from app.monthly_report_section_uploads import source_destinations
        water_is_present = any(section.key == "water" and section.included for section in draft.sections)
        page_owners = source_destinations(contents, st.session_state.get(prefix + "_evidence_section_routes", {}), blocks)
        section_page_owners = tuple(identity for identity, owners in page_owners.items()
                                    if water_is_present and owners == {"water_reports"})
        sources, additions, incoming_specs = render_uploads(
            draft.profile, draft.period, prefix, field, attached_blocks=blocks,
            scope_draft=replace(draft, blocks=tuple(blocks.values())),
            included_source_ids=used_source_ids(replace(draft, blocks=tuple(blocks.values()))),
            show_intake=not has_activity, selected_source_id=selected, visible=opened,
            shown_source_page=shown_page[0] if shown_page else None, section_page_owners=section_page_owners)
        from app.monthly_report_page_captions import synchronize_source_captions
        current_sources = keep_missing(prefix, sources)
        # Compare with the sources this render opened with: caption corrections
        # above and page decisions in the intake both reach included pages.
        blocks, conflicts = synchronize_source_captions(blocks, entry_sources, current_sources,
            decision=st.session_state.pop(prefix + "_evidence_page_decision", None))
        draft = replace(draft, sources=current_sources)
        for conflict in conflicts:
            source = next(source for source in draft.sources if source.id == conflict.source_id)
            block = blocks[conflict.block_key]
            st.warning(f"{source.filename} · page {conflict.number}: the report and source have different captions. Choose which wording to keep, then review this page.")
            st.caption("Report caption: " + (conflict.report_caption or "(blank)"))
            st.caption("Source caption: " + (conflict.source_caption or "(blank)"))
            stamp = prefix + "_caption_conflict_" + block.fingerprint + "_" + source.fingerprint + "_" + str(conflict.number)
            use_source, keep_report = st.columns(2)
            selected_caption = None
            if use_source.button("Use source caption in report", key=stamp + "_source"):
                selected_caption = conflict.source_caption
            if keep_report.button("Keep report caption", key=stamp + "_report"):
                selected_caption = conflict.report_caption
            if selected_caption is not None:
                from app.monthly_report_page_controls import revise_included_page
                revised, source = revise_included_page(block, source, conflict.number, "caption",
                    caption=selected_caption, all_sources=draft.sources)
                source = replace(source, client_page_reviews=tuple((number, receipt)
                    for number, receipt in source.client_page_reviews if number != conflict.number))
                blocks[block.key] = revised
                draft = replace(draft, sources=tuple(source if item.id == source.id else item for item in draft.sources))
                evidence_key = prefix + "_evidence"
                st.session_state[evidence_key] = tuple(replace(content, source=source)
                    if content.source.id == source.id else content for content in st.session_state.get(evidence_key, ()))
                forms = st.session_state.get("_monthly_source_detail_forms")
                if isinstance(forms, dict):
                    forms[source.id] = source
                st.session_state[prefix + "_period_editor_refresh"] = True
        if before_sources != {source.id: source.fingerprint for source in draft.sources}:
            # Intake/read controls precede metadata and page controls. Finish
            # their delivered edits/defaults, then bind the displayed read
            # request to the settled source. This is not paid-read consent.
            # Classification also routes on this action, not a second click.
            st.session_state[prefix + "_period_editor_refresh"] = True
        if additions:
            previous_blocks = blocks
            draft, blocks = apply_prepared(draft, blocks, additions, incoming_specs, prefix)
            updated = _statuses(draft, blocks, prefix)
            if blocks is not previous_blocks and updated and all(item.resolved for item in updated):
                st.session_state[manager_key] = False
                st.session_state[prefix + "_period_editor_refresh"] = True
        if selected and has_activity:
            render_workorder_metrics(draft.profile, draft.period, prefix,
                st.session_state.get(prefix + "_evidence", ()), blocks, selected_id=selected)
        if requested != selected:
            # The old source's ordinary inputs were delivered with this select
            # event. Commit them before switching its page controls; all native
            # metadata forms remain mounted throughout.
            st.session_state[active_key] = requested
            st.session_state[prefix + "_period_editor_refresh"] = True
    if st.session_state.pop(manager_key + "_close_request", False):
        st.session_state[manager_key] = False
        st.session_state[prefix + "_period_editor_refresh"] = True
    st.session_state[status_key] = {item.source_id: item.resolved
                                    for item in _statuses(draft, blocks, prefix)}
    return draft, blocks


def _close_manager(manager_key):
    st.session_state[manager_key + "_close_request"] = True
