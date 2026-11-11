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
    if check.code in {"photo_caption", "document_caption"}:
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


def _current_photo_caption(draft, target):
    resolved = resolve_target(draft, target)
    if resolved is None:
        return False
    block, index, source = resolved
    if block is None or index is None:
        return False
    # A source-page caption must remain a source-page warning: after source loss,
    # the same image could otherwise acquire an ordinary photo-caption warning.
    code = "document_caption" if source is not None else "photo_caption"
    from app.monthly_report_layout_checks import layout_checks
    return any(check.code == code and target in check.targets
               for check in layout_checks(draft))


def queue_photo_caption(prefix, target, scope):
    from uuid import uuid4
    from app.monthly_report_guided import _rich_text_scope
    state = st.session_state
    state.pop(prefix + "_photo_caption_navigation_open", None)
    state.pop(prefix + "_photo_caption_navigation_pending", None)
    draft = state.get(prefix + "_draft")
    if (not scope or scope != _rich_text_scope(prefix) or draft is None
            or not _current_photo_caption(draft, target)):
        state[prefix + "_photo_caption_navigation_notice"] = PHOTO_CAPTION_NOTICE
        return
    state[prefix + "_photo_caption_navigation_pending"] = {
        "scope": scope, "target": target, "nonce": uuid4().hex}


def consume_photo_caption(prefix, draft, scope):
    """Before editors mount, reveal only the currently bound photo's owner."""
    state = st.session_state
    request = state.pop(prefix + "_photo_caption_navigation_pending", None)
    if request is None:
        return
    if (not isinstance(request, dict) or request.get("scope") != scope
            or not isinstance(request.get("nonce"), str) or not request["nonce"]
            or not _current_photo_caption(draft, request.get("target"))):
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
            or not _current_photo_caption(draft, target)):
        return ""
    from app.monthly_report_correction_targets import picture_target
    if picture_target(draft, block, index, source=resolved[2], page=target.page) != target:
        return ""
    st.session_state.pop(prefix + "_photo_caption_navigation_open", None)
    return ('<a class="enfra-page-correction-request" data-report-identity="' +
        _identity(prefix) + '" data-token="' + escape(request["nonce"], quote=True) +
        '" href="#' + marker_id(prefix, target) + '" hidden></a>')


def render_photo_caption_links(check, draft, prefix):
    if check.code not in {"photo_caption", "document_caption"}:
        return
    from app.monthly_report_guided import _rich_text_scope
    for target in check.targets:
        if not _current_photo_caption(draft, target):
            st.caption(PHOTO_CAPTION_NOTICE)
            continue
        block, index, _ = resolve_target(draft, target)
        st.button("Edit caption · " + block.key.replace("_", " ") +
                  " · photo " + str(index + 1),
                  key=prefix + "_photo_caption_correction_" + target.token,
                  on_click=queue_photo_caption,
                  args=(prefix, target, _rich_text_scope(prefix)))


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
    if check.code not in ("required", "review", "placeholder", "pricing", "text_character"):
        return
    matches = [block for block in draft.blocks if block.key == check.block_key]
    if len(matches) != 1:
        return
    block = matches[0]
    token = _text_warning_target(draft, block)
    if token is None:
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
    elif code in {"carried_period", "photo_layout", "source", "library_save"}:
        matches = [block for block in draft.blocks if block.key == owner]
        if len(matches) != 1 or matches[0].source == "Omit":
            return
        block = matches[0]
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
        targets = [block for block in draft.blocks if block.key == check.block_key]
        items = [item for item in draft.follow_ups if item.key == check.block_key]
        if len(targets) + len(items) != 1:
            ids = ()
        else:
            refs = used_source_ids(replace(draft,
                blocks=tuple(targets), follow_ups=tuple(items)))
            ids = tuple(sorted(refs - set(known)))
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
                (report_identity(draft) + "\\0" + check.code + "\\0" + source_id).encode()).hexdigest(),
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
        selection = choice()
        if selection is None:
            st.error("Shared-library replacement cannot be completed here. "
                     "Keep this draft and import a supported report-only version.")
        else:
            key = prefix + "_fix_library_save_" + block.key + "_" + block.fingerprint
            st.markdown(native_warning_marker(prefix, "library_save", block.key,
                                               block.fingerprint, key),
                        unsafe_allow_html=True)
            if st.button("Keep this block in this report only; do not replace the shared library",
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
