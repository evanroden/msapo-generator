"""Shared source review is not authority to overwrite report occurrences."""
from dataclasses import replace
import pytest
from app.monthly_report_model import ReportDraft,ReportPeriod,default_sections
from app.monthly_report_correction_targets import picture_target
from app.monthly_report_manager_page_navigation import (
    manager_target,queue_navigation,finish_navigation,consume_navigation)
from app.monthly_report_page_captions import synchronize_source_captions
from app.monthly_report_asset_review import refresh_asset_source_context
from test_monthly_report_page_manager import _prepared

P='manager'


def setup(monkeypatch,tmp_path,*,duplicate=False):
    profile,content,block=_prepared(monkeypatch,tmp_path)
    block=replace(block,key='improvements')
    blocks=(block,)
    if duplicate:
        sibling=replace(block,key='vendor_reports',asset_captions=('Independent caption A','Independent caption B'))
        blocks=(*blocks,sibling)
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Synthetic Editor',default_sections(),blocks,sources=(content.source,))
    target=picture_target(draft,block,1,source=content.source,page=2)
    return draft,content,target


def test_caption_and_review_ownership_are_distinct(monkeypatch,tmp_path):
    draft,content,target=setup(monkeypatch,tmp_path,duplicate=True)
    assert manager_target(draft,(content,),target) is None
    assert manager_target(draft,(content,),target,source_review=True) is not None
    before=draft
    state={}
    assert queue_navigation(state,P,draft,(content,),target,'scope',source_review=True)
    assert P+'_evidence_selected' not in state
    assert finish_navigation(state,P,draft,(content,),'scope')
    assert P+'_evidence_selected' not in state
    assert consume_navigation(state,P,draft,(content,),'scope')
    assert state[P+'_evidence_selected']==content.source.id
    assert state[P+'_evidence_'+content.source.id+'_page']==2
    assert draft==before
    assert draft.blocks[1].asset_captions==('Independent caption A','Independent caption B')
    snapshot=dict(state)
    assert not consume_navigation(state,P,draft,(content,),'scope')
    assert not finish_navigation(state,P,draft,(content,),'scope')
    assert state==snapshot


@pytest.mark.parametrize('duplicate',[False,True])
def test_exact_caption_only_journal_can_renew_source_review_without_overwriting_independent_caption(monkeypatch,tmp_path,duplicate):
    draft,content,target=setup(monkeypatch,tmp_path,duplicate=duplicate)
    state={}
    assert queue_navigation(state,P,draft,(content,),target,'scope',source_review=True)
    source=replace(content.source,captions=tuple(sorted({**dict(content.source.captions),1:'Delivered old-page caption'}.items())))
    blocks,conflicts=synchronize_source_captions({b.key:b for b in draft.blocks},draft.sources,(source,))
    updated=replace(draft,sources=(source,),blocks=tuple(refresh_asset_source_context(b,(source,)) for b in blocks.values()))
    state[P+'_source_native_changes']={source.id:(content.source,source)}
    contents=(replace(content,source=source),)
    assert finish_navigation(state,P,updated,contents,'scope')
    assert consume_navigation(state,P,updated,contents,'scope')
    if duplicate:
        assert updated.blocks[0].asset_captions==draft.blocks[0].asset_captions
        assert updated.blocks[1].asset_captions==draft.blocks[1].asset_captions
    else:
        assert updated.blocks[0].asset_captions[0]=='Delivered old-page caption'
    assert source.client_page_reviews==content.source.client_page_reviews


@pytest.mark.parametrize('phase',['queued','ready'])
@pytest.mark.parametrize('change',['scope','bytes','removed','duplicate_source','duplicate_block','metadata','caption_without_journal'])
def test_stale_or_ambiguous_receipt_never_changes_selection(monkeypatch,tmp_path,phase,change):
    draft,content,target=setup(monkeypatch,tmp_path)
    state={P+'_evidence_selected':'old-owner'}
    assert queue_navigation(state,P,draft,(content,),target,'scope',source_review=True)
    if phase=='ready':assert finish_navigation(state,P,draft,(content,),'scope')
    scope='scope';contents=(content,)
    if change=='scope':scope='replacement'
    elif change=='removed':draft=replace(draft,blocks=())
    elif change=='duplicate_source':draft=replace(draft,sources=(*draft.sources,*draft.sources))
    elif change=='duplicate_block':draft=replace(draft,blocks=(*draft.blocks,*draft.blocks))
    else:
        source=replace(content.source,**({'sha256':'replacement'} if change=='bytes' else
            {'vendor':'Changed vendor'} if change=='metadata' else {'captions':((1,'Unrelated revision'),)}))
        draft=replace(draft,sources=(source,));contents=(replace(content,source=source),)
    action=finish_navigation if phase=='queued' else consume_navigation
    assert not action(state,P,draft,contents,scope)
    assert state[P+'_evidence_selected']=='old-owner'
    assert 'page' not in state


def test_same_page_twice_within_one_block_is_source_global_not_caption_authority(monkeypatch,tmp_path):
    from app.monthly_report_asset_instances import asset_instances,new_asset_instance,with_asset_instances
    from app.monthly_report_manager_page_navigation import unavailable_reason
    draft,content,_=setup(monkeypatch,tmp_path)
    block=draft.blocks[0];original=asset_instances(block)[1]
    block=replace(block,asset_hashes=(*block.asset_hashes,original.asset),
                  asset_captions=(*block.asset_captions,'Distinct duplicate caption'))
    block=with_asset_instances(block,(*asset_instances(draft.blocks[0]),new_asset_instance(original.asset,original.references)))
    draft=replace(draft,blocks=(block,))
    target=picture_target(draft,block,2,source=content.source,page=2)
    assert manager_target(draft,(content,),target) is None
    assert 'independent captions' in unavailable_reason(draft,(content,),target)
    assert manager_target(draft,(content,),target,source_review=True) is not None
    state={}
    assert queue_navigation(state,P,draft,(content,),target,'scope',source_review=True)
    assert finish_navigation(state,P,draft,(content,),'scope')
    assert consume_navigation(state,P,draft,(content,),'scope')
    assert draft.blocks[0].asset_captions[-1]=='Distinct duplicate caption'
    assert draft.blocks[0].asset_captions[1]!=draft.blocks[0].asset_captions[-1]


def test_latest_repeated_display_request_has_one_commit_and_no_passive_focus_replay(monkeypatch,tmp_path):
    draft,content,target=setup(monkeypatch,tmp_path)
    state={P+'_evidence_selected':'old-owner'}
    assert queue_navigation(state,P,draft,(content,),target,'scope',source_review=True)
    first=state[P+'_manager_page_navigation_pending']['nonce']
    assert queue_navigation(state,P,draft,(content,),target,'scope',source_review=True)
    assert state[P+'_manager_page_navigation_pending']['nonce']!=first
    assert state[P+'_evidence_selected']=='old-owner'
    assert finish_navigation(state,P,draft,(content,),'scope')
    assert consume_navigation(state,P,draft,(content,),'scope')
    from app.monthly_report_manager_page_navigation import page_markup
    mark=page_markup(state,P,content.source,2,'exact-native-page-key','scope',source_review=True)
    assert 'data-field-kind="combobox"' in mark and 'exact-native-page-key' in mark
    assert not page_markup(state,P,content.source,2,'exact-native-page-key','scope',source_review=True)
    assert not finish_navigation(state,P,draft,(content,),'scope')
    assert not consume_navigation(state,P,draft,(content,),'scope')
