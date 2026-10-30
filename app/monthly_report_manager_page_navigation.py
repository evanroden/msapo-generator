"""Exact shared-manager page navigation after old native editor capture/save.

Only unique report occurrences are admitted. Source-level review cannot stand
in for an ambiguous report occurrence's independent caption/review ownership.
"""
from dataclasses import replace
from hashlib import sha256
from html import escape
from uuid import uuid4
from app.monthly_report_correction_targets import picture_target, resolve_target

NOTICE = 'This source page changed or is unavailable. Your edits remain here; use its current warning.'


def manager_target(draft, contents, target, *, source_review=False):
    if (len({b.key for b in draft.blocks}) != len(draft.blocks)
            or len({s.id for s in draft.sources}) != len(draft.sources)
            or not any(s.key == 'activity' and s.included for s in draft.sections)):
        return None
    resolved = resolve_target(draft, target)
    if resolved is None:
        return None
    block, index, source = resolved
    if block is None or source is None or target.page < 1:
        return None
    matches = [c for c in contents if c.source.id == source.id]
    if len(matches) != 1 or matches[0].source != source:
        return None
    from app.monthly_report_sources import image_numbers
    from app.monthly_report_asset_review import asset_context
    from app.monthly_report_section_uploads import page_identity, source_destinations
    if target.page not in image_numbers(matches[0]):
        return None
    occurrences = [(b.key, n) for b in draft.blocks for n in range(len(b.asset_hashes))
        if (source.id, target.page) in {page_identity(ref) for ref in asset_context(b,n)}]
    if (block.key,index) not in occurrences or (not source_review and occurrences != [(block.key,index)]):
        return None
    from app.monthly_report_page_controls import page_asset_index
    if not source_review and page_asset_index(block, source.id, target.page) != index:
        return None
    owners = source_destinations(contents, {}, {b.key:b for b in draft.blocks})
    if (owners.get(source.id) == {'water_reports'}
            and any(s.key == 'water' and s.included for s in draft.sections)):
        return None  # That exact source has the established Water owner.
    caption = dict(source.captions).get(target.page)
    attached = block.asset_captions[index] if index < len(block.asset_captions) else ''
    if not source_review and caption is not None and caption != attached:
        return None  # Existing conflict choice, not a competing caption editor.
    return block, index, source


def unavailable_reason(draft, contents, target, *, source_review=False):
    resolved = resolve_target(draft,target)
    if resolved is None or resolved[0] is None or resolved[2] is None:
        return None
    block,index,source=resolved
    from app.monthly_report_asset_review import asset_context
    from app.monthly_report_section_uploads import page_identity,source_destinations
    occurrences=[(b.key,n) for b in draft.blocks for n in range(len(b.asset_hashes))
        if (source.id,target.page) in {page_identity(ref) for ref in asset_context(b,n)}]
    owners=source_destinations(contents,{}, {b.key:b for b in draft.blocks})
    if len(occurrences)>1 and (not source_review or owners.get(source.id)=={'water_reports'}):
        return ('This source page has multiple report occurrences with independent captions. '
                'Exact occurrence routing is unavailable here; keep each caption and use its existing report editor. '
                'Source-page review and each picture review are separate.')
    caption=dict(source.captions).get(target.page)
    attached=block.asset_captions[index] if index<len(block.asset_captions) else ''
    if not source_review and caption is not None and caption!=attached:
        return ('The source and report captions differ. Use the existing caption-conflict choices '
                'in Manage source files; neither caption will be overwritten by navigation.')
    return None


def queue_navigation(state, prefix, draft, contents, target, scope, *, source_review=False):
    for suffix in ('pending','ready','open'):
        state.pop(prefix + '_manager_page_navigation_' + suffix, None)
    if not scope or manager_target(draft, contents, target, source_review=source_review) is None:
        state[prefix + '_manager_page_navigation_notice'] = (unavailable_reason(
            draft,contents,target,source_review=source_review) or NOTICE)
        return False
    # Native selections are unchanged. The ordinary manager must read the old
    # page's delivered caption and keep every buffered source form mounted.
    state[prefix + '_manager_page_navigation_pending'] = {
        'target':target, 'before':draft, 'scope':scope, 'nonce':uuid4().hex, 'source_review':source_review}
    state.pop(prefix + '_manager_page_navigation_notice',None)
    return True


def caption_only_target(before, current, contents, target, changes, *, source_review=False):
    """Renew only a proven same-render caption change, never a stale revision."""
    from app.monthly_report_model import ReportDraft
    if not isinstance(before,ReportDraft) or resolve_target(before,target) is None:
        return None
    if [s.id for s in before.sources] != [s.id for s in current.sources]:
        return None
    changed = False
    for old, new in zip(before.sources,current.sources):
        if old == new:
            continue
        if (changes.get(old.id) != (old,new)
                or replace(old,captions=new.captions) != new):
            return None
        changed = True
    if not changed:
        return None
    from app.monthly_report_page_captions import synchronize_source_captions
    from app.monthly_report_asset_review import refresh_asset_source_context
    blocks, conflicts = synchronize_source_captions({b.key:b for b in before.blocks},
                                                   before.sources,current.sources)
    if not source_review and any(c.block_key == target.block_key and c.source_id == target.source_id
           and c.number == target.page for c in conflicts):
        return None
    blocks = {key:refresh_asset_source_context(block,current.sources) for key,block in blocks.items()}
    original = resolve_target(before,target)
    if original is None:
        return None
    old_block,index,old_source=original
    block=blocks.get(old_block.key)
    source=next((s for s in current.sources if s.id==old_source.id),None)
    if block is None or source is None or block.asset_hashes != old_block.asset_hashes:
        return None
    expected=replace(before,blocks=tuple(blocks.values()),sources=current.sources)
    renewed=picture_target(expected,block,index,source=source,page=target.page)
    return renewed if manager_target(current,contents,renewed,source_review=source_review) is not None else None


def finish_navigation(state,prefix,draft,contents,scope):
    request=state.pop(prefix+'_manager_page_navigation_pending',None)
    if request is None:
        return False
    if (not isinstance(request,dict) or request.get('scope')!=scope
            or not isinstance(request.get('nonce'),str) or not request['nonce']):
        state[prefix+'_manager_page_navigation_notice']=NOTICE
        return False
    target=request.get('target')
    source_review=request.get('source_review') is True
    if manager_target(draft,contents,target,source_review=source_review) is None:
        before=request.get('before')
        target=(caption_only_target(before,draft,contents,target,
                    state.get(prefix+'_source_native_changes',{}), source_review=source_review) if before is not None else None)
    if target is None or manager_target(draft,contents,target,source_review=source_review) is None:
        state[prefix+'_manager_page_navigation_notice']=NOTICE
        return False
    state[prefix+'_manager_page_navigation_ready']={
        'target':target,'scope':scope,'nonce':request['nonce'],'source_review':source_review}
    state[prefix+'_period_editor_refresh']=True
    return True


def consume_navigation(state,prefix,draft,contents,scope):
    request=state.pop(prefix+'_manager_page_navigation_ready',None)
    if request is None:
        return False
    if (not isinstance(request,dict) or request.get('scope')!=scope
            or not isinstance(request.get('nonce'),str) or not request['nonce']
            or manager_target(draft,contents,request.get('target'),source_review=request.get('source_review') is True) is None):
        state[prefix+'_manager_page_navigation_notice']=NOTICE
        return False
    target=request['target']
    # Complete previous native render/save attempt has finished. These are
    # existing manager presentation keys, written before their widgets exist.
    state[prefix+'_batch_files_open']=True
    state[prefix+'_batch_files_open_open_request']=True
    state[prefix+'_evidence_selected']=target.source_id
    state[prefix+'_source_active_selected']=target.source_id
    state[prefix+'_evidence_'+target.source_id+'_page']=target.page
    state[prefix+'_manager_page_navigation_open']=request
    return True


def page_markup(state,prefix,source,page,field_key,scope,*,source_review=False):
    request=state.get(prefix+'_manager_page_navigation_open')
    if (not isinstance(request,dict) or request.get('scope')!=scope
            or (request.get('source_review') is True) != source_review):
        return ''
    target=request.get('target')
    if (target is None or source.id!=target.source_id or source.sha256!=target.source_hash
            or source.fingerprint!=target.source_revision or page!=target.page):
        return ''
    state.pop(prefix+'_manager_page_navigation_open',None)
    from app.monthly_report_correction_ui import marker_id
    identity=sha256(prefix.encode()).hexdigest()[:24]
    destination=marker_id(prefix,target)
    return ('<span class="enfra-picture-correction" id="'+destination+
        '" data-report-identity="'+identity+'" data-field-kind="'+('combobox' if source_review else 'input')+'" data-field-key="'+
        escape(field_key,quote=True)+'" aria-hidden="true"></span>'+
        '<a class="enfra-page-correction-request" data-report-identity="'+identity+
        '" data-token="'+escape(request['nonce'],quote=True)+'" href="#'+destination+'" hidden></a>')
