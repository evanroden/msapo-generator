"""Three-phase source-page navigation; input commit precedes selection changes.

Only the existing included Water-page owner is admitted in this first slice.
No helper here approves/includes a page or reports a recovery save successful.
"""
from dataclasses import replace
from uuid import uuid4

from app.monthly_report_correction_targets import picture_target, resolve_target

NOTICE = 'This page changed or is unavailable. Your current edits remain here; try its current warning.'


def _water_target(draft, contents, target):
    if (len({b.key for b in draft.blocks}) != len(draft.blocks)
            or len({source.id for source in draft.sources}) != len(draft.sources)):
        return None
    resolved = resolve_target(draft, target)
    if resolved is None:
        return None
    block, index, source = resolved
    if (block is None or source is None or block.key != 'water_reports' or target.page < 1
            or not any(s.key == 'water' and s.included for s in draft.sections)):
        return None
    matches = [c for c in contents if c.source.id == source.id]
    if len(matches) != 1 or matches[0].source != source:
        return None
    from app.monthly_report_sources import image_numbers
    if target.page not in image_numbers(matches[0]):
        return None
    from app.monthly_report_page_controls import page_asset_index
    from app.monthly_report_section_uploads import source_destinations
    if page_asset_index(block, source.id, target.page) != index:
        return None
    owners = source_destinations(contents, {}, {b.key: b for b in draft.blocks})
    if owners.get(source.id) != {'water_reports'}:
        return None
    return block, index, source


def queue_navigation(state, prefix, draft, contents, target, scope):
    """Callback: capture delivered caption once; never select a file/page."""
    # A newer human request cancels older display intent, even when the new
    # destination has gone stale. Pending content receipts are never discarded.
    state.pop(prefix + '_page_navigation_ready', None)
    state.pop(prefix + '_page_navigation_open', None)
    previous = state.get(prefix + '_page_navigation_pending')
    def reject(message=NOTICE):
        state.pop(prefix + '_page_navigation_pending', None)
        state[prefix + '_page_navigation_notice'] = message
        return False
    if not scope or _water_target(draft, contents, target) is None:
        return reject()
    local = prefix + '_evidence_section_water_reports'
    action_key = local + '_page_edit'
    if state.get(action_key) is not None:
        # An identical repeated activation reuses its one pending commit.
        if (isinstance(previous, dict) and previous.get('scope') == scope
                and previous.get('original_target') == target
                and previous.get('caption_receipt') == state[action_key]):
            return True
        # A review/omit/move receipt must not be overwritten by navigation.
        return reject('Finish the current page action, then try again. Your current edits remain here.')
    expected = target
    caption_receipt = None
    origin = state.get(prefix + '_page_navigation_origin')
    if origin is not None:
        required = ('source_id', 'source_fingerprint', 'block_key', 'block_fingerprint', 'number', 'scope')
        if (not isinstance(origin, dict) or origin.get('scope') != scope
                or any(key not in origin for key in required)):
            return reject()
        key = origin.get('caption_key')
        if not isinstance(key, str) or key not in state or not isinstance(state[key], str):
            return reject()
        if state[key] != origin.get('caption'):
            caption_receipt = {key: origin[key] for key in (
                'source_id', 'source_fingerprint', 'block_key', 'block_fingerprint', 'number', 'scope')}
            caption_receipt.update(action='caption', caption=state[key])
            # Compute only the exact expected result, without changing state or
            # making a stale receipt valid. The ordinary owner commits it later.
            from app.monthly_report_page_controls import apply_page_request
            try:
                updated_contents, changes = apply_page_request(contents,
                    {b.key: b for b in draft.blocks}, caption_receipt)
            except (ValueError, KeyError):
                return reject()
            updated = replace(draft, blocks=tuple(changes.get(b.key, b) for b in draft.blocks),
                              sources=tuple(next((c.source for c in updated_contents if c.source.id == source.id), source)
                                            for source in draft.sources))
            before_block, index, source = _water_target(draft, contents, target)
            next_block = changes.get(before_block.key, before_block)
            next_source = next((s for s in updated.sources if s.id == source.id), None)
            # Caption-only commit cannot reorder, replace or add occurrences.
            if next_block.asset_hashes != before_block.asset_hashes or next_source is None:
                return reject()
            expected = picture_target(updated, next_block, index, source=next_source, page=target.page)
    nonce = uuid4().hex
    if caption_receipt is not None:
        state[action_key] = caption_receipt
    state.pop(prefix + '_page_navigation_ready', None)
    state.pop(prefix + '_page_navigation_open', None)
    state[prefix + '_page_navigation_pending'] = {
        'nonce': nonce, 'scope': scope, 'target': expected, 'original_target': target,
        'caption_receipt': caption_receipt,
    }
    state.pop(prefix + '_page_navigation_notice', None)
    return True


def finish_navigation(state, prefix, draft, contents, scope):
    """After the whole native draft/recovery attempt, stage one refresh only."""
    request = state.pop(prefix + '_page_navigation_pending', None)
    if request is None:
        return False
    action_key = prefix + '_evidence_section_water_reports_page_edit'
    if (not isinstance(request, dict) or not isinstance(request.get('nonce'), str)
            or not request['nonce'] or request.get('scope') != scope or state.get(action_key) is not None
            or _water_target(draft, contents, request.get('target')) is None):
        state[prefix + '_page_navigation_notice'] = NOTICE
        return False
    state[prefix + '_page_navigation_ready'] = request
    state[prefix + '_period_editor_refresh'] = True
    return True


def consume_navigation(state, prefix, draft, contents, scope):
    """Before widgets: one-shot validated request, never first-file fallback."""
    request = state.pop(prefix + '_page_navigation_ready', None)
    if request is None:
        return False
    if not isinstance(request, dict) or not isinstance(request.get('nonce'), str) or not request['nonce']:
        state[prefix + '_page_navigation_notice'] = NOTICE
        return False
    target = request.get('target')
    if request.get('scope') != scope or _water_target(draft, contents, target) is None:
        state[prefix + '_page_navigation_notice'] = NOTICE
        return False
    # All state writes below are presentation state in the existing owner.
    # The previous full render already committed every delivered old-page value.
    local = prefix + '_evidence_section_water_reports'
    state[local + '_selected'] = target.source_id
    state[local + '_' + target.source_id + '_next_page'] = target.page
    state[local + '_' + target.source_id + '_edit_page_reviews'] = True
    state[prefix + '_page_navigation_open'] = request
    return True


def ready_page_markup(state, prefix, source, block, page, caption_key, scope):
    """Emit focus intent only beside the exact current native caption field."""
    from html import escape
    from hashlib import sha256
    from app.monthly_report_correction_ui import marker_id
    request = state.get(prefix + '_page_navigation_open')
    if not isinstance(request, dict) or request.get('scope') != scope:
        return ''
    target = request.get('target')
    if (target is None or source.id != target.source_id or source.sha256 != target.source_hash
            or source.fingerprint != target.source_revision or page != target.page
            or block.key != target.block_key or block.fingerprint != target.block_revision):
        return ''
    state.pop(prefix + '_page_navigation_open', None)
    identity = sha256(prefix.encode()).hexdigest()[:24]
    destination = marker_id(prefix, target)
    return ('<span class="enfra-picture-correction" id="' + destination +
        '" data-report-identity="' + identity + '" data-field-kind="input" data-field-key="' +
        escape(caption_key, quote=True) + '" aria-hidden="true"></span>' +
        '<a class="enfra-page-correction-request" data-report-identity="' + identity +
        '" data-token="' + escape(request['nonce'], quote=True) + '" href="#' +
        destination + '" hidden></a>')
