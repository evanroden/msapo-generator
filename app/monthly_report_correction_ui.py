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
    # Overlong ordinary captions require the native closed-editor route below,
    # not an additional link to a field that may not be mounted yet.
    if check.code in {"photo_caption", "document_caption"} or (
            check.targets and check.code in {"pricing", "placeholder", "text_character"}):
        return
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


# Ordinary photo-caption warnings are different from pending picture approvals:
# a previously reviewed photo's editor can be intentionally collapsed. Stage a
# native, exact-occurrence request rather than linking to an absent sibling field.
PHOTO_CAPTION_NOTICE = (
    "That photo or its caption changed or is unavailable. Your edits remain here; "
    "use the current Review warning to open its correction."
)


def _current_photo_caption(draft, target, code=None):
    resolved = resolve_target(draft, target)
    if resolved is None:
        return False
    block, index, source = resolved
    if block is None or index is None:
        return False
    if code in {"pricing", "placeholder", "text_character"}:
        if index >= len(block.asset_captions):
            return False
        caption = block.asset_captions[index]
        if code == "pricing":
            from app.monthly_report_content_policy import contains_price
            valid = contains_price(caption)
        elif code == "placeholder":
            from app.monthly_report_checks import placeholder_matches
            valid = bool(placeholder_matches(caption))
        else:
            import re
            valid = bool(re.search(r"[\\x00-\\x08\\x0e-\\x1b\\x1f\\ud800-\\udfff\\ufffe\\uffff]", caption))
        if not valid:
            return False
        # No sibling may substitute for the exact caption occurrence.
        from app.monthly_report_checks import preflight
        return any(check.code == code and target in check.targets
                   for check in preflight(draft))
    # A source-page caption must remain a source-page warning after source loss.
    expected = "document_caption" if source is not None else "photo_caption"
    if code not in (None, expected):
        return False
    from app.monthly_report_layout_checks import layout_checks
    return any(check.code == expected and target in check.targets
               for check in layout_checks(draft))


def queue_photo_caption(prefix, target, scope, code=None):
    from uuid import uuid4
    from app.monthly_report_guided import _rich_text_scope
    state = st.session_state
    state.pop(prefix + "_photo_caption_navigation_open", None)
    state.pop(prefix + "_photo_caption_navigation_pending", None)
    draft = state.get(prefix + "_draft")
    if (not scope or scope != _rich_text_scope(prefix) or draft is None
            or not _current_photo_caption(draft, target, code)):
        state[prefix + "_photo_caption_navigation_notice"] = PHOTO_CAPTION_NOTICE
        return
    state[prefix + "_photo_caption_navigation_pending"] = {
        "scope": scope, "target": target, "code": code, "nonce": uuid4().hex}


def consume_photo_caption(prefix, draft, scope):
    """Before editors mount, reveal only the currently bound photo's owner."""
    state = st.session_state
    request = state.pop(prefix + "_photo_caption_navigation_pending", None)
    if request is None:
        return
    if (not isinstance(request, dict) or request.get("scope") != scope
            or not isinstance(request.get("nonce"), str) or not request["nonce"]
            or not _current_photo_caption(draft, request.get("target"),
                                         request.get("code"))):
        state[prefix + "_photo_caption_navigation_notice"] = PHOTO_CAPTION_NOTICE
        return
    block, _, _ = resolve_target(draft, request["target"])
    state[prefix + "_photos_" + block.key + "_editing"] = True
    state[prefix + "_photo_caption_navigation_open"] = request


def photo_caption_request(prefix, draft, block, index):
    """Issue one native jump only beside the exact rendered caption field."""
    request = st.session_state.get(prefix + "_photo_caption_navigation_open")
    if not isinstance(request, dict):
        return ""
    target = request.get("target")
    resolved = resolve_target(draft, target)
    if (resolved is None or resolved[0] != block or resolved[1] != index
            or not _current_photo_caption(draft, target, request.get("code"))):
        return ""
    from app.monthly_report_correction_targets import picture_target
    if picture_target(draft, block, index, source=resolved[2], page=target.page) != target:
        return ""
    st.session_state.pop(prefix + "_photo_caption_navigation_open", None)
    return ('<a class="enfra-page-correction-request" data-report-identity="' +
        _identity(prefix) + '" data-token="' + escape(request["nonce"], quote=True) +
        '" href="#' + marker_id(prefix, target) + '" hidden></a>')


def render_photo_caption_links(check, draft, prefix):
    if check.code not in {"photo_caption", "document_caption",
                          "pricing", "placeholder", "text_character"}:
        return
    from app.monthly_report_guided import _rich_text_scope
    for target in check.targets:
        if not _current_photo_caption(draft, target, check.code):
            st.caption(PHOTO_CAPTION_NOTICE)
            continue
        block, index, _ = resolve_target(draft, target)
        st.button("Edit caption · " + block.key.replace("_", " ") +
                  " · photo " + str(index + 1),
                  key=prefix + "_photo_caption_correction_" + check.code + "_" + target.token,
                  on_click=queue_photo_caption,
                  args=(prefix, target, _rich_text_scope(prefix), check.code))


def finish_photo_caption(prefix):
    """A missing exact native owner cannot redirect to a nearby photograph."""
    if st.session_state.pop(prefix + "_photo_caption_navigation_open", None) is not None:
        st.session_state[prefix + "_photo_caption_navigation_notice"] = PHOTO_CAPTION_NOTICE
    notice = st.session_state.pop(prefix + "_photo_caption_navigation_notice", None)
    if notice:
        st.warning(notice)


# Text-only blockers have one authoritative native rich-text editor. Do not
# replace source-page/AI/table/photo-specific owners with a nearby text box.
def _text_warning_target(draft, block):
    from app.monthly_report_correction_targets import report_identity
    from app.monthly_report_model import used_block_keys
    if (block is None or block.source == "Omit"
            or block.key not in used_block_keys(draft)
            or sum(item.key == block.key for item in draft.blocks) != 1
            or block.ai_paragraphs):
        return None
    specs = [spec for section in draft.sections if section.included
             for spec in section.blocks if spec.key == block.key]
    if len(specs) != 1 or specs[0].type not in ("rich_text", "stock_text"):
        return None
    import json
    return sha256(json.dumps((report_identity(draft), block.key, block.fingerprint),
                             sort_keys=True).encode()).hexdigest()


def text_warning_marker(draft, block, prefix, field_key):
    """The marker must sit beside the current field, not the previous block."""
    token = _text_warning_target(draft, block)
    if token is None:
        return ""
    return ('<span class="enfra-picture-correction" id="report-correction-' +
        sha256((prefix + "\\0" + token).encode()).hexdigest() +
        '" data-report-identity="' + _identity(prefix) +
        '" data-field-kind="textarea" data-field-key="' +
        escape(field_key, quote=True) + '" aria-hidden="true"></span>')


def render_text_warning_links(check, draft, prefix):
    """Only a proven problem in this block's text gets a direct field link."""
    if check.code not in ("required", "review", "placeholder", "pricing", "text_character",
                           "period_removed"):
        return
    if check.targets:
        # A caption or source-page warning already owns its exact occurrence.
        # Never advertise an adjacent narrative field as a substitute.
        return
    matches = [block for block in draft.blocks if block.key == check.block_key]
    if len(matches) != 1:
        return
    block = matches[0]
    token = _text_warning_target(draft, block)
    if token is None:
        return
    if check.code == "period_removed":
        from app.monthly_report_period_items import apply_exclusions
        if apply_exclusions(block, draft.period).text == block.text:
            return
    if check.code == "placeholder":
        from app.monthly_report_checks import placeholder_matches
        if not placeholder_matches(block.text):
            return
    if check.code == "pricing":
        from app.monthly_report_content_policy import contains_price
        if not contains_price(block.text):
            return
    if check.code == "text_character":
        import re
        if not re.search(r"[\x00-\x08\x0e-\x1b\x1f\ud800-\udfff\ufffe\uffff]", block.text):
            return
    destination = 'report-correction-' + sha256((prefix + "\\0" + token).encode()).hexdigest()
    st.markdown('<a class="enfra-picture-correction-link" data-report-identity="' +
        _identity(prefix) + '" href="#' + destination +
        '">Edit this exact report text</a>', unsafe_allow_html=True)


# Exact native controls for non-photo blockers. The revision is part of the
# marker: a stale warning must never open a newer sibling or reused widget.
def native_warning_marker(prefix, code, owner, revision, field_key, *, kind="button"):
    if kind not in ("button", "input", "textarea", "combobox"):
        raise ValueError("Unsupported native correction field")
    address = sha256((prefix + "\\0" + code + "\\0" + owner + "\\0" + revision).encode()).hexdigest()
    return ('<span class="enfra-picture-correction" id="report-correction-' + address +
            '" data-report-identity="' + _identity(prefix) +
            '" data-field-kind="' + kind + '" data-field-key="' +
            escape(field_key, quote=True) + '" aria-hidden="true"></span>')


def section_title_revision(section):
    """Only the blank title's structural slot, never a duplicate key, owns it."""
    return sha256(repr((section.key, section.number, section.blocks,
                        section.divider_asset, section.appendix)).encode()).hexdigest()


def section_title_problems(section):
    if not section.included:
        return ()
    from app.monthly_report_non_narrative_recovery import unsafe
    return tuple(code for code in ("pricing", "placeholder", "text_character")
                 if unsafe(section.title, code))


def edit_missing_section_title(section, prefix, field):
    """Repair blank or unsafe headings without remapping original section IDs."""
    from dataclasses import replace
    problems = section_title_problems(section)
    if not section.included or (section.title.strip() and not problems):
        return section
    key = prefix + "_repair_section_title_" + section.key
    revision = section_title_revision(section)
    st.markdown("".join(native_warning_marker(
                    prefix, code, section.key, revision, key, kind="input")
                    for code in (("title",) if not section.title.strip() else problems)),
                unsafe_allow_html=True)
    title = st.text_input("Title for section " + section.key.replace("_", " "),
                          value=section.title, key=field(key, section.title))
    return replace(section, title=title) if title != section.title else section


def render_native_warning_links(check, draft, prefix):
    """Only link a current, unique owner that has an authoritative native field."""
    if not check.blocking:
        return
    from app.monthly_report_correction_targets import report_identity
    code, owner = check.code, check.block_key
    if code == "prepared_by":
        if draft.prepared_by.strip():
            return
        owner, revision, label = "report", report_identity(draft), "Enter Prepared by"
    elif code in {"title", "pricing", "placeholder", "text_character"}:
        matching = [section for section in draft.sections
                    if section.key == owner and section.included and
                    ((code == "title" and not section.title.strip()) or
                     code in section_title_problems(section))]
        if len(matching) != 1 or sum(item.key == owner for item in draft.sections) != 1:
            return
        revision, label = section_title_revision(matching[0]), (
            "Enter this section's title" if code == "title" else
            "Correct unsafe text in this section title")
    elif code in {"carried_period", "photo_layout", "source", "library_save"}:
        matches = [block for block in draft.blocks if block.key == owner]
        if len(matches) != 1:
            return
        block = matches[0]
        if code in {"carried_period", "photo_layout"} and block.source == "Omit":
            return
        if code == "carried_period":
            from app.monthly_report_setup import carried_period
            if not carried_period(block, draft.period):
                return
        elif code == "photo_layout":
            if type(block.photos_per_page) is int and 1 <= block.photos_per_page <= 6:
                return
        elif code == "source":
            allowed = [spec for section in draft.sections if section.included
                       for spec in section.blocks if spec.key == owner]
            if len(allowed) != 1 or block.source in allowed[0].allowed_sources:
                return
        elif not block.pending_library_save:
            return
        revision, label = block.fingerprint, {
            "carried_period": "Confirm or correct this carried update",
            "photo_layout": "Correct this block's photo layout",
            "source": "Correct this block's source choice",
            "library_save": "Keep this block in this report without replacing the library",
        }[code]
    else:
        return
    destination = "report-correction-" + sha256(
        (prefix + "\\0" + code + "\\0" + owner + "\\0" + revision).encode()).hexdigest()
    st.markdown('<a class="enfra-picture-correction-link" data-report-identity="' +
                _identity(prefix) + '" href="#' + destination + '">' +
                escape(label) + '</a>', unsafe_allow_html=True)


def render_source_recovery_links(check, draft, prefix):
    """A lost original has no live page editor; open its one source manager."""
    if not check.blocking or check.code not in {
            "source_missing", "client_source_missing", "unavailable_source"}:
        return
    from app.monthly_report_source_manager_ui import _open_manager
    from app.monthly_report_model import used_source_ids
    from dataclasses import replace
    from app.monthly_report_correction_targets import report_identity
    known = {source.id: source for source in draft.sources}
    if check.code == "unavailable_source":
        ids = tuple(dict.fromkeys(getattr(target, "source_id", "")
                                  for target in check.targets if getattr(target, "source_id", "")))
    elif check.code == "source_missing":
        from app.monthly_report_correction_targets import CorrectionTarget, report_identity
        ids = tuple(dict.fromkeys(
            target.source_id for target in check.targets
            if isinstance(target, CorrectionTarget)
            and target.report == report_identity(draft)
            and target.source_id not in known))
        if not ids:
            st.caption("The original source identity changed. Recheck the current "
                       "source warning; no other file was substituted.")
            return
    else:
        # The preflight check already records the exact picture occurrences.
        # A missing original must not be recovered by selecting equal bytes.
        ids = ()
        from app.monthly_report_correction_targets import resolve_target
        for target in check.targets:
            resolved = resolve_target(draft, target)
            if resolved is None:
                continue
            block, index, _ = resolved
            from app.monthly_report_asset_review import asset_context
            for reference in asset_context(block, index):
                parts = reference.split(":")
                if len(parts) == 3 and parts[1].isdigit() and parts[0] not in known:
                    ids += (parts[0],)
        ids = tuple(dict.fromkeys(ids))
    if not ids:
        st.caption("No unique original source can be selected from this warning. Keep the "
                   "linked content unchanged until its provenance is restored or explicitly remove it.")
        return
    for source_id in ids:
        identity = known.get(source_id)
        label = identity.filename if identity else "source " + source_id
        st.caption("Original required: " + label + ". Re-upload the original source, "
                   "or deliberately remove/relink its dependent content. A new file with "
                   "the same name is not automatically the same source.")
        st.button("Open Manage source files · " + label,
            key=prefix + "_recover_source_" + sha256(
                (report_identity(draft) + "\\0" + check.code + "\\0" +
                 check.block_key + "\\0" + source_id + "\\0" +
                 repr(check.targets) + "\\0" + check.message).encode()).hexdigest(),
            on_click=_open_manager,
            args=(prefix + "_batch_files_open", prefix + "_evidence_selected",
                  source_id if identity else ""))


def render_inline_block_repairs(spec, block, prefix):
    """Expose existing-block corrections; never act without an explicit click.

    Key each action to the original block incarnation. A stale browser action
    cannot silently alter a newer replacement or an unrelated block.
    """
    from dataclasses import replace
    def choice():
        return next((name for name in ("Replace once", "This month")
                     if name in spec.allowed_sources), None)

    if block.source not in spec.allowed_sources:
        selection = choice()
        if selection is None:
            st.error("This block has no supported report-only source option. "
                     "Re-import it using an allowed source; its existing content is retained.")
        else:
            key = prefix + "_fix_source_" + block.key + "_" + block.fingerprint
            st.markdown(native_warning_marker(prefix, "source", block.key, block.fingerprint,
                                               key), unsafe_allow_html=True)
            if st.button("Use " + selection + " as the source for " +
                         block.key.replace("_", " "), key=key):
                block = replace(block, source=selection)
    if block.pending_library_save:
        selection = 'Omit' if block.source == 'Omit' else choice()
        if selection is None:
            st.error("Shared-library replacement cannot be completed here. "
                     "Keep this draft and import a supported report-only version.")
        else:
            key = prefix + "_fix_library_save_" + block.key + "_" + block.fingerprint
            st.markdown(native_warning_marker(prefix, "library_save", block.key,
                                               block.fingerprint, key),
                        unsafe_allow_html=True)
            if st.button(("Cancel the pending library replacement; keep this block omitted"
                          if block.source == "Omit" else
                          "Keep this block in this report only; do not replace the shared library"),
                         key=key):
                block = replace(block, source=selection, pending_library_save=False)
    if type(block.photos_per_page) is not int or not 1 <= block.photos_per_page <= 6:
        key = prefix + "_fix_photo_layout_" + block.key + "_" + block.fingerprint
        st.markdown(native_warning_marker(prefix, "photo_layout", block.key,
                                           block.fingerprint, key), unsafe_allow_html=True)
        if st.button("Use 3 photos per page for " + block.key.replace("_", " "),
                     key=key):
            block = replace(block, photos_per_page=3)
    return block


def render_imported_table_warning_links(check, draft, prefix):
    """Name one physical imported table, never a duplicate heading or filename."""
    if not check.blocking or check.code not in {"table_columns", "table_missing_columns"}:
        return
    from app.monthly_report_table_column_recovery import missing_positions
    blocks = [block for block in draft.blocks if block.key == check.block_key]
    if len(blocks) != 1:
        return
    block = blocks[0]
    for index, table in enumerate(block.extra_tables):
        positions = missing_positions(table)
        if not positions:
            continue
        code = "table_missing_columns" if not table.columns else "table_columns"
        stem = "Imported table " + str(index + 1)
        if code != check.code or not check.message.startswith((stem + " ", stem + ",")):
            continue
        owner = block.key + ":imported:" + str(index)
        destination = "report-correction-" + sha256(
            (prefix + "\\0" + code + "\\0" + owner + "\\0" + block.fingerprint).encode()).hexdigest()
        st.markdown('<a class="enfra-picture-correction-link" data-report-identity="' +
                    _identity(prefix) + '" href="#' + destination +
                    '">Correct imported table ' + str(index + 1) + ' · column ' +
                    str(positions[0] + 1) + '</a>', unsafe_allow_html=True)


def render_followup_identity_recovery(check, draft, prefix):
    """Explicitly make colliding saved row identities unique without losing rows."""
    if not check.blocking or check.code != "follow_up_identity":
        return
    from collections import Counter
    from app.monthly_report_followups import unique_followup_keys
    counts = Counter(item.key for item in draft.follow_ups)
    if not any(value > 1 for value in counts.values()):
        return
    st.caption("Saved follow-up row identifiers collide. Each occurrence can "
               "receive a separate stable identity; its wording, status, dates "
               "and sources remain. Changed proposal decisions must be reviewed again.")
    key = prefix + "_repair_followup_identities_" + draft.fingerprint
    if st.button("Give colliding issue/proposal rows separate identities",
                 key=key):
        current = st.session_state.get(prefix + "_draft")
        if current is None or current.fingerprint != draft.fingerprint:
            st.warning("The report changed before this identity repair. "
                       "Review the current rows and retry; no rows were altered.")
            return
        repaired = unique_followup_keys(current)
        if repaired == current:
            st.warning("The current rows no longer have colliding identities.")
            return
        st.session_state[prefix + "_draft"] = repaired
        st.rerun()


# Report-structure and follow-up recovery actions are explicit and positional.
# They intentionally do not route by a nonunique section/block or item key.
def _apply_review_recovery(prefix, displayed, action, *, target="", position=-1):
    from dataclasses import replace
    from app.monthly_report_model import ReportFollowUp
    state = st.session_state
    current = state.get(prefix + "_draft")
    if current is None or current.fingerprint != displayed.fingerprint:
        state[prefix + "_warning_recovery_notice"] = (
            "The report changed before this correction. Your edits are retained; "
            "review the current warning and repeat the action.")
        return
    if action == "include_section":
        matches = [s for s in current.sections if s.key == target]
        if len(matches) != 1 or matches[0].included:
            state[prefix + "_warning_recovery_notice"] = "That section changed; choose the current section."
            return
        sections = tuple(replace(s, included=True) if s.key == target else s
                         for s in current.sections)
        profile = replace(current.profile, excluded_sections=tuple(
            key for key in current.profile.excluded_sections if key != target))
        result = replace(current, sections=sections, profile=profile)
    elif action == "omit_followup":
        if not 0 <= position < len(current.follow_ups):
            return
        item = current.follow_ups[position]
        if item.key != target or not item.included or sum(
                i.key == target for i in current.follow_ups) != 1:
            state[prefix + "_warning_recovery_notice"] = "That item changed; review its current row."
            return
        items = tuple(replace(i, included=False, reviewed_fingerprint="")
                      if n == position else i
                      for n, i in enumerate(current.follow_ups))
        result = replace(current, follow_ups=items)
    elif action == "dedupe_sections":
        seen, sections = set(), []
        for section in current.sections:
            if section.key in seen:
                if section != next(s for s in sections if s.key == section.key):
                    state[prefix + "_warning_recovery_notice"] = (
                        "These sections differ. Retained both; re-import a corrected "
                        "section definition instead of losing either.")
                    return
                continue
            seen.add(section.key)
            sections.append(section)
        result = replace(current, sections=tuple(sections))
    elif action == "dedupe_blocks":
        seen, blocks = {}, []
        for block in current.blocks:
            previous = seen.get(block.key)
            if previous is not None:
                if block != previous:
                    state[prefix + "_warning_recovery_notice"] = (
                        "These blocks have different content. Retained both; restore "
                        "a corrected source rather than discarding either edit.")
                    return
                continue
            seen[block.key] = block
            blocks.append(block)
        result = replace(current, blocks=tuple(blocks))
    else:
        return
    if result != current:
        state[prefix + "_draft"] = result
        state[prefix + "_period_editor_refresh"] = True


def render_structure_and_followup_recovery(check, draft, prefix):
    if not check.blocking:
        return
    code = check.code
    from collections import Counter
    from app.monthly_report_followups import output_followups, MAX_INCLUDED_FOLLOWUPS
    if code == "sections":
        if any(s.included for s in draft.sections):
            return
        eligible = [(n, s) for n, s in enumerate(draft.sections)
                    if sum(other.key == s.key for other in draft.sections) == 1]
        if not eligible:
            st.caption("No uniquely owned section can be selected. Restore the "
                       "original report structure before including content.")
            return
        position = st.selectbox("Section to include in this report",
                                [n for n, _ in eligible],
                                format_func=lambda n: draft.sections[n].title or
                                draft.sections[n].key.replace("_", " ").capitalize(),
                                key=prefix + "_warning_include_section_" + draft.fingerprint)
        section = draft.sections[position]
        st.button("Include this selected section", key=prefix +
                  "_warning_include_section_confirm_" + draft.fingerprint,
                  on_click=_apply_review_recovery,
                  args=(prefix, draft, "include_section"),
                  kwargs={"target": section.key})
    elif code == "follow_up_section":
        matches = [(n, item) for n, item in enumerate(draft.follow_ups)
                   if item.key == check.block_key and item.included]
        if len(matches) != 1:
            st.caption("This item has no unique identity; repair colliding item identities first.")
            return
        index, item = matches[0]
        section_key = "issues" if item.category == "issue" else "proposals"
        options = [s for s in draft.sections if s.key == section_key]
        if len(options) == 1 and not options[0].included:
            st.button("Include " + section_key + " section", key=prefix +
                      "_warning_missing_section_" + check.block_key + "_" + draft.fingerprint,
                      on_click=_apply_review_recovery,
                      args=(prefix, draft, "include_section"),
                      kwargs={"target": section_key})
        st.button("Leave this exact item out of this report", key=prefix +
                  "_warning_omit_followup_" + check.block_key + "_" + draft.fingerprint,
                  on_click=_apply_review_recovery,
                  args=(prefix, draft, "omit_followup"),
                  kwargs={"position": index, "target": item.key})
    elif code == "follow_up_limit":
        if len(output_followups(draft)) <= MAX_INCLUDED_FOLLOWUPS:
            return
        if check.block_key not in ("equipment_issues", "proposals"):
            return
        category = "issue" if check.block_key == "equipment_issues" else "proposal"
        items = [(n, item) for n, item in enumerate(draft.follow_ups)
                 if item.included and item.category == category and
                 sum(other.key == item.key for other in draft.follow_ups) == 1]
        if not items:
            st.caption("No uniquely identified item can be left out here. "
                       "Repair duplicate row identities first.")
            return
        selection = st.selectbox("Select a " + category + " to leave out",
                                 [n for n, _ in items],
                                 format_func=lambda n: ("Row " + str(n + 1) + " · " +
                                     (draft.follow_ups[n].text[:90] or "Unfinished row")),
                                 key=prefix + "_warning_limit_select_" +
                                 category + "_" + draft.fingerprint)
        item = draft.follow_ups[selection]
        st.button("Leave out only this " + category + " · row " + str(selection + 1),
                  key=prefix + "_warning_limit_confirm_" + category + "_" + draft.fingerprint,
                  on_click=_apply_review_recovery,
                  args=(prefix, draft, "omit_followup"),
                  kwargs={"position": selection, "target": item.key})
    elif code in ("duplicate_sections", "duplicate_blocks"):
        entries = draft.sections if code == "duplicate_sections" else draft.blocks
        collisions = {key for key, n in Counter(item.key for item in entries).items() if n > 1}
        if not collisions:
            return
        groups = {key: [(n, item) for n, item in enumerate(entries) if item.key == key]
                  for key in collisions}
        same = all(all(item == group[0][1] for _, item in group)
                   for group in groups.values())
        for key, group in sorted(groups.items()):
            st.caption(key.replace("_", " ") + " · conflicting positions " +
                       ", ".join(str(n + 1) for n, _ in group) +
                       (" · identical records" if all(item == group[0][1] for _, item in group)
                        else " · different records; none will be discarded"))
        if same:
            st.button("Remove only byte-identical duplicate " +
                      ("section" if code == "duplicate_sections" else "block") +
                      " records", key=prefix + "_warning_dedupe_" + code + "_" + draft.fingerprint,
                      on_click=_apply_review_recovery,
                      args=(prefix, draft, "dedupe_sections" if code == "duplicate_sections"
                            else "dedupe_blocks"))
        else:
            st.caption("These records differ. Keep the current draft and "
                       "restore an original with unique structural identities; "
                       "no matching-name record can be silently selected.")


def render_receivable_recovery(check, draft, prefix):
    """Re-enter the real invoice source, never approve a stale AR receipt."""
    if not check.blocking or check.code != "receivable_source":
        return
    from app.monthly_report_model import used_block_keys
    from app.monthly_report_source_manager_ui import _open_manager
    from app.monthly_report_receivable_intake import decoded
    if "accounts_receivable" not in used_block_keys(draft):
        return
    source_ids = set()
    for raw in draft.source_row_reviews:
        try:
            record = decoded(raw)
        except (ValueError, TypeError):
            continue
        source_id = record.get("source_id")
        if isinstance(source_id, str) and source_id:
            source_ids.add(source_id)
    source = [item for item in draft.sources if item.id in source_ids]
    if len(source) == 1:
        st.caption("Invoice source: " + source[0].filename +
                   ". Reopen the original, then review the invoice-status rows "
                   "in Accounts Receivable. This action does not approve an amount.")
    else:
        st.caption("The saved invoice-status receipt is missing or ambiguous. "
                   "Re-upload the correct CSV/XLSX source and explicitly "
                   "re-review its current status rows; no amounts will be inferred.")
    st.button("Open Manage source files for invoice recovery",
        key=prefix + "_receivable_source_recover_" + draft.fingerprint,
        on_click=_open_manager,
        args=(prefix + "_batch_files_open", prefix + "_evidence_selected",
              source[0].id if len(source) == 1 else ""))


def render_identity_warning_recovery(check, draft, prefix):
    """Point unsafe identity text to its actual authority; do not remap sites."""
    if not check.blocking or check.block_key != "report_identity" or check.code not in (
            "pricing", "placeholder", "text_character"):
        return
    from app.monthly_report_non_narrative_recovery import unsafe
    from app.monthly_report_correction_targets import report_identity
    if unsafe(draft.prepared_by, check.code):
        # This exact marker is beside the one native Prepared by field.
        destination = "report-correction-" + sha256(
            (prefix + "\\0prepared_by\\0report\\0" + report_identity(draft)).encode()).hexdigest()
        st.markdown('<a class="enfra-picture-correction-link" data-report-identity="' +
                    _identity(prefix) + '" href="#' + destination +
                    '">Correct Prepared by</a>', unsafe_allow_html=True)
    if unsafe(draft.profile.title, check.code):
        st.markdown("[Correct the saved group name in Change report sites → More report details](#report-profile-details)")
        st.caption("Use Save report details after editing; this does not automatically "
                   "rename the underlying contract or overwrite report content.")
    if unsafe(draft.profile.contract, check.code):
        st.markdown("[Choose the correct contract and its report sites](#report-contract-selector)")
        st.caption("The contract identifier belongs to the contract directory. "
                   "Changing reports must not silently relabel the current site's content.")
    for index, site in enumerate(draft.profile.facilities):
        if unsafe(site.title, check.code):
            from app.monthly_report_admin_ui import admin_url
            st.caption("Site " + str(index + 1) + " · " + site.title +
                       " has unsafe label text. Correct that exact site in the contract directory "
                       "and reload this report; do not edit an unrelated site.")
            st.markdown("[Open contract directory for site " + str(index + 1) +
                        "](" + admin_url("directory") + ")")


def _footer_repair_revision(draft):
    blocks = [block for block in draft.blocks if block.key == "footer_text"]
    if len(blocks) > 1:
        return None
    block = blocks[0] if blocks else None
    return (block.fingerprint if block else sha256(draft.address_line.encode()).hexdigest())


def render_footer_warning_links(check, draft, prefix):
    if not check.blocking or check.block_key not in ("footer", "footer_text") or check.code not in (
            "pricing", "placeholder", "text_character"):
        return
    from app.monthly_report_non_narrative_recovery import unsafe
    blocks = [block for block in draft.blocks if block.key == "footer_text"]
    if len(blocks) > 1:
        st.caption("The footer has duplicate block identities. Repair them first.")
        return
    text = blocks[0].text if blocks else draft.address_line
    if not unsafe(text, check.code):
        return
    revision = _footer_repair_revision(draft)
    dest = "report-correction-" + sha256(
        (prefix + "\\0" + check.code + "\\0footer_text\\0" + revision).encode()).hexdigest()
    st.markdown('<a class="enfra-picture-correction-link" data-report-identity="' +
                _identity(prefix) + '" href="#' + dest +
                '">Correct the exact report footer</a>', unsafe_allow_html=True)


def render_footer_repair_editor(draft, checks, prefix, field):
    """One guarded report footer editor, not one per warning occurrence."""
    from app.monthly_report_non_narrative_recovery import unsafe
    from dataclasses import replace
    from app.monthly_report_model import ResolvedBlock
    blocks = [block for block in draft.blocks if block.key == "footer_text"]
    if len(blocks) > 1:
        return
    current = blocks[0] if blocks else ResolvedBlock("footer_text", "This month",
                                                      text=draft.address_line)
    codes = tuple(code for code in ("pricing", "placeholder", "text_character")
                  if unsafe(current.text, code) and any(
                      check.blocking and check.code == code and
                      check.block_key in ("footer", "footer_text") for check in checks))
    if not codes:
        return
    revision = _footer_repair_revision(draft)
    key = prefix + "_repair_footer_text_" + revision
    st.caption("Correct this report's footer. It is not a change to the contract's "
               "master address or to any source original.")
    st.markdown("".join(native_warning_marker(prefix, code, "footer_text",
                          revision, key, kind="textarea") for code in codes),
                unsafe_allow_html=True)
    edited = st.text_area("Correct report footer", value=current.text,
                          key=field(key, current.text), height=110)
    if st.button("Apply corrected footer in this report", key=prefix +
                 "_repair_footer_apply_" + revision):
        original = st.session_state.get(prefix + "_draft")
        if original is None or original.fingerprint != draft.fingerprint:
            st.warning("The report changed before this footer edit. Current values are retained.")
            return
        if edited == current.text:
            st.warning("The footer is unchanged. Correct or deliberately clear it first.")
            return
        changed = replace(current, source="This month", text=edited,
                          reviewed_fingerprint="", client_reviewed_fingerprint="")
        updated = tuple(changed if block.key == "footer_text" else block
                        for block in original.blocks)
        if not blocks:
            updated += (changed,)
        st.session_state[prefix + "_draft"] = replace(
            original, blocks=updated, address_line=edited)
        st.session_state[prefix + "_period_editor_refresh"] = True


def _resolve_unmounted_library(prefix, draft_identity, key, revision):
    from dataclasses import replace
    from app.monthly_report_correction_targets import report_identity
    from app.monthly_report_model import layout_blocks
    current = st.session_state.get(prefix + "_draft")
    matches = [b for b in current.blocks if b.key == key] if current else []
    specs = [spec for spec in layout_blocks() if spec.key == key]
    if (current is None or report_identity(current) != draft_identity
            or len(matches) != 1 or matches[0].fingerprint != revision
            or not matches[0].pending_library_save or len(specs) != 1):
        st.session_state[prefix + "_warning_recovery_notice"] = (
            "The shared replacement changed before the choice. Nothing was changed.")
        return
    block = matches[0]
    source = "Omit" if block.source == "Omit" else (
        "Replace once" if "Replace once" in specs[0].allowed_sources else "This month")
    changed = replace(block, source=source, pending_library_save=False)
    st.session_state[prefix + "_draft"] = replace(current, blocks=tuple(
        changed if value is block else value for value in current.blocks))
    st.session_state[prefix + "_period_editor_refresh"] = True


def render_unmounted_library_recovery(check, draft, prefix):
    """Layout/cover blocks have no ordinary _edit_content owner."""
    if not check.blocking or check.code != "library_save":
        return
    from app.monthly_report_model import layout_blocks
    from app.monthly_report_correction_targets import report_identity
    valid = {spec.key for spec in layout_blocks()}
    if check.block_key not in valid:
        return
    matches = [b for b in draft.blocks if b.key == check.block_key and b.pending_library_save]
    if len(matches) != 1:
        return
    st.button("Keep " + check.block_key.replace("_", " ") +
              " in this report only; cancel shared-library replacement",
              key=prefix + "_warning_unmounted_library_" + matches[0].fingerprint,
              on_click=_resolve_unmounted_library,
              args=(prefix, report_identity(draft), check.block_key, matches[0].fingerprint))
