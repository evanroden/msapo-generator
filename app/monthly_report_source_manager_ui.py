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


def _statuses(draft, blocks, prefix):
    evidence = prefix + "_evidence"
    pending = bool(st.session_state.get(evidence + "_pending_acceptance")
                   or st.session_state.get(evidence + "_accepted_failure")
                   or any(value for key, value in st.session_state.items()
                          if key.startswith(evidence + "_structured_")
                          and key.endswith(("_job", "_pending"))))
    return source_manager_status(replace(draft, blocks=tuple(blocks.values())),
        st.session_state.get(evidence, ()),
        unavailable=st.session_state.get(prefix + "_unavailable_sources", ()), pending=pending)


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
    from app.monthly_report_guided import _current_source_detail, _forget_block_widgets
    from app.monthly_report_source_scope import artwork_scope_keys
    from app.monthly_report_source_details import detail_problems
    from app.monthly_report_upload_ui import (
        render_source_details, render_structured_uploads, render_workorder_metrics,
        _remember_delivered_source_edit,
    )
    st.session_state[prefix + "_source_native_changes"] = {}
    manager_key = field(prefix + "_batch_files_open", False)
    selection_key = prefix + "_evidence_selected"
    active_key = prefix + "_source_active_selected"
    states = _statuses(draft, blocks, prefix)
    attention = tuple(item for item in states if item.needs_correction)
    opened = bool(st.session_state[manager_key])
    with st.container(key=prefix + "_source_file_status"):
        if states:
            st.caption(f"{len(states)} source {'file' if len(states) == 1 else 'files'}" +
                       (f" · {len(attention)} need details" if attention else ""))
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
        before_ids = {content.source.id for content in st.session_state.get(prefix + "_evidence", ())}
        has_activity = any(section.key == "activity" for section in draft.sections)
        if has_activity:
            sources, additions, _ = render_structured_uploads(
                draft.profile, draft.period, prefix, field, "activity_summary", blocks=blocks,
                assets=assets, table_columns=table_columns, managed=True)
        else:
            sources, additions = draft.sources, {}
        draft = replace(draft, sources=keep_missing(prefix, sources))
        if additions:
            from app.monthly_report_guided import merge_blocks
            for key, block in additions.items():
                blocks[key] = merge_blocks(blocks.get(key), block) if key == "improvements" else block
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
            if selected_status:
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
        draft = replace(draft, sources=keep_missing(prefix, sources))
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
    return draft, blocks


def _close_manager(manager_key):
    st.session_state[manager_key + "_close_request"] = True
