"""Source navigation captures old native input before its selection can retire."""
from dataclasses import replace
import pytest
from app.monthly_report_correction_targets import picture_target
from app.monthly_report_model import ReportDraft, ReportPeriod, default_sections
from app.monthly_report_page_navigation import queue_navigation, finish_navigation, consume_navigation
from app.monthly_report_page_controls import apply_page_request
from app.monthly_report_content_policy import page_allowed
from test_monthly_report_page_manager import _prepared

PREFIX = 'nav'
LOCAL = PREFIX + '_evidence_section_water_reports'


def setup(monkeypatch, tmp_path, target_page=2):
    profile, content, block = _prepared(monkeypatch, tmp_path)
    draft = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Editor', default_sections(),
                        (block,), sources=(content.source,))
    target = picture_target(draft, block, target_page - 1, source=content.source, page=target_page)
    state = {PREFIX + '_page_navigation_origin': {
        'source_id':content.source.id, 'source_fingerprint':content.source.fingerprint,
        'block_key':block.key, 'block_fingerprint':block.fingerprint, 'number':1,
        'scope':'incarnation', 'caption_key':'native_caption', 'caption':block.asset_captions[0]},
        'native_caption':'Delivered without blur'}
    return draft, content, target, state


def commit(draft, content, state):
    receipt = state.pop(LOCAL + '_page_edit')
    contents, changes = apply_page_request((content,), {b.key:b for b in draft.blocks}, receipt)
    updated = replace(draft, blocks=tuple(changes.get(b.key,b) for b in draft.blocks),
                      sources=tuple(c.source for c in contents))
    return updated, contents


@pytest.mark.parametrize('target_page', [1,2])
def test_caption_only_commit_precedes_same_or_other_page_switch(monkeypatch,tmp_path,target_page):
    draft, content, target, state = setup(monkeypatch,tmp_path,target_page)
    original_selected = content.source.selected_pages
    assert queue_navigation(state,PREFIX,draft,(content,),target,'incarnation')
    assert LOCAL + '_selected' not in state
    assert state[LOCAL + '_page_edit']['action'] == 'caption'
    updated, contents = commit(draft,content,state)
    assert updated.blocks[0].asset_captions[0] == 'Delivered without blur'
    assert updated.sources[0].selected_pages == original_selected
    assert not page_allowed(updated.sources[0],1)  # No implicit Review/Include.
    assert finish_navigation(state,PREFIX,updated,contents,'incarnation')
    assert LOCAL + '_selected' not in state
    assert consume_navigation(state,PREFIX,updated,contents,'incarnation')
    assert state[LOCAL + '_selected'] == content.source.id
    assert state[LOCAL + '_' + content.source.id + '_next_page'] == target_page
    snapshot = dict(state)
    assert not consume_navigation(state,PREFIX,updated,contents,'incarnation')
    assert not finish_navigation(state,PREFIX,updated,contents,'incarnation')
    assert state == snapshot


@pytest.mark.parametrize('phase', ['queued','ready'])
@pytest.mark.parametrize('change', ['source','scope','removed','duplicate_source','duplicate_block'])
def test_changed_target_never_mutates_selection(monkeypatch,tmp_path,phase,change):
    draft, content, target, state = setup(monkeypatch,tmp_path)
    assert queue_navigation(state,PREFIX,draft,(content,),target,'incarnation')
    draft, contents = commit(draft,content,state)
    if phase == 'ready':
        assert finish_navigation(state,PREFIX,draft,contents,'incarnation')
    scope='incarnation'
    if change == 'source':
        source=replace(draft.sources[0],sha256='replacement')
        draft=replace(draft,sources=(source,));contents=(replace(contents[0],source=source),)
    elif change == 'scope':scope='new-incarnation'
    elif change == 'removed':draft=replace(draft,blocks=())
    elif change == 'duplicate_source':draft=replace(draft,sources=draft.sources*2);contents=contents*2
    else:draft=replace(draft,blocks=draft.blocks*2)
    action=finish_navigation if phase=='queued' else consume_navigation
    assert not action(state,PREFIX,draft,contents,scope)
    assert LOCAL + '_selected' not in state
    assert PREFIX + '_page_navigation_notice' in state


def test_existing_review_action_is_not_overwritten(monkeypatch,tmp_path):
    draft, content, target, state=setup(monkeypatch,tmp_path)
    original={'action':'review','nonce':'original'};state[LOCAL+'_page_edit']=original
    assert not queue_navigation(state,PREFIX,draft,(content,),target,'incarnation')
    assert state[LOCAL+'_page_edit'] is original
    assert PREFIX+'_page_navigation_pending' not in state


def test_uncommitted_caption_never_produces_ready_packet(monkeypatch,tmp_path):
    draft, content, target, state=setup(monkeypatch,tmp_path)
    assert queue_navigation(state,PREFIX,draft,(content,),target,'incarnation')
    assert not finish_navigation(state,PREFIX,draft,(content,),'incarnation')
    assert PREFIX+'_page_navigation_ready' not in state
    assert LOCAL+'_page_edit' in state  # Do not discard the owner’s input receipt.


def two_sources(monkeypatch,tmp_path):
    from app.monthly_report_asset_instances import new_asset_instance, with_asset_instances
    from app.monthly_report_asset_review import refresh_asset_source_context
    profile,content,block=_prepared(monkeypatch,tmp_path,pages=1)
    second=replace(content,source=replace(content.source,id='distinct-source-occurrence'))
    refs=tuple(f'{c.source.id}:1:{c.source.fingerprint}' for c in (content,second))
    block=replace(block,asset_hashes=block.asset_hashes*2,asset_captions=('First occurrence','Second occurrence'),
                  references=refs,client_asset_reviews=(),client_reviewed_fingerprint='')
    block=with_asset_instances(block,tuple(new_asset_instance(block.asset_hashes[0],(ref,)) for ref in refs))
    block=refresh_asset_source_context(block,(content.source,second.source))
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Synthetic Editor',default_sections(),(block,),
                      sources=(content.source,second.source))
    return draft,(content,second)


def test_equal_named_sources_and_bytes_keep_independent_caption_before_switch(monkeypatch,tmp_path):
    draft,contents=two_sources(monkeypatch,tmp_path)
    first,second=contents;block=draft.blocks[0]
    state={PREFIX+'_page_navigation_origin':{
        'source_id':first.source.id,'source_fingerprint':first.source.fingerprint,
        'block_key':block.key,'block_fingerprint':block.fingerprint,'number':1,
        'scope':'incarnation','caption_key':'caption','caption':block.asset_captions[0]},
        'caption':'First source only'}
    target=picture_target(draft,block,1,source=second.source,page=1)
    assert first.source.filename==second.source.filename and first.source.sha256==second.source.sha256
    assert queue_navigation(state,PREFIX,draft,contents,target,'incarnation')
    contents,changes=apply_page_request(contents,{block.key:block},state.pop(LOCAL+'_page_edit'))
    updated=replace(draft,blocks=(changes[block.key],),sources=tuple(c.source for c in contents))
    assert updated.blocks[0].asset_captions==('First source only','Second occurrence')
    assert contents[1]==second
    assert finish_navigation(state,PREFIX,updated,contents,'incarnation')
    assert consume_navigation(state,PREFIX,updated,contents,'incarnation')
    assert state[LOCAL+'_selected']==second.source.id


def test_new_navigation_retires_older_ready_packet(monkeypatch,tmp_path):
    draft,content,target,state=setup(monkeypatch,tmp_path)
    assert queue_navigation(state,PREFIX,draft,(content,),target,'incarnation')
    draft,contents=commit(draft,content,state)
    assert finish_navigation(state,PREFIX,draft,contents,'incarnation')
    old_nonce=state[PREFIX+'_page_navigation_ready']['nonce']
    state.pop(PREFIX+'_page_navigation_origin')  # No currently unsubmitted old-page field.
    newer=picture_target(draft,draft.blocks[0],0,source=draft.sources[0],page=1)
    assert queue_navigation(state,PREFIX,draft,contents,newer,'incarnation')
    assert PREFIX+'_page_navigation_ready' not in state
    assert not consume_navigation(state,PREFIX,draft,contents,'incarnation')
    assert finish_navigation(state,PREFIX,draft,contents,'incarnation')
    assert state[PREFIX+'_page_navigation_ready']['nonce'] != old_nonce
    assert consume_navigation(state,PREFIX,draft,contents,'incarnation')
    assert state[LOCAL+'_'+content.source.id+'_next_page']==1


def test_repeated_callback_reuses_caption_receipt_and_invalid_new_intent_cancels_jump(monkeypatch,tmp_path):
    draft,content,target,state=setup(monkeypatch,tmp_path)
    assert queue_navigation(state,PREFIX,draft,(content,),target,'incarnation')
    pending=state[PREFIX+'_page_navigation_pending']
    receipt=state[LOCAL+'_page_edit']
    assert queue_navigation(state,PREFIX,draft,(content,),target,'incarnation')
    assert state[PREFIX+'_page_navigation_pending'] is pending
    assert state[LOCAL+'_page_edit'] is receipt
    # Invalid newer destination cancels the jump, not the operator's caption.
    assert not queue_navigation(state,PREFIX,draft,(content,),replace(target,source_hash='missing'),'incarnation')
    assert PREFIX+'_page_navigation_pending' not in state
    assert state[LOCAL+'_page_edit'] is receipt
