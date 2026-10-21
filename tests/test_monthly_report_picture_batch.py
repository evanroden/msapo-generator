"""Explicit group consent covers only this displayed, exact pending set."""
from dataclasses import replace
from io import BytesIO
from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest
from app import monthly_report_picture_batch_ui as batch
from app.monthly_report_asset_review import pending_asset_indexes, asset_fingerprint
from app.monthly_report_library import asset_reference
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec, BlockSpec, synthetic_profiles


def sample(count=7):
    assets={}
    for i in range(count):
        out=BytesIO();Image.new('RGB',(20,20),(i,30,40)).save(out,format='PNG')
        raw=out.getvalue();assets[asset_reference(raw,'png')]=raw
    block=ResolvedBlock('vendor_reports','This month',asset_hashes=tuple(assets),asset_captions=tuple(f'Inspection {i}' for i in range(count)))
    section=SectionSpec('subcontractors','6','Vendor reports',(BlockSpec('vendor_reports','pdf_pages'),))
    draft=ReportDraft(synthetic_profiles()[0],ReportPeriod(2026,10),'Synthetic operator',(section,),(block,))
    return draft,assets


def request(draft,assets):
    draft,entries,identity=batch._manifest(draft,'epoch')
    selected,images,fallback=batch._choose(draft,assets,entries,())
    assert selected and not fallback
    return {'identity':identity,'entries':selected,'left':()},draft


def test_six_exact_reviews_leave_unseen_seventh_pending():
    draft,assets=sample()
    req,draft=request(draft,assets)
    assert len(req['entries'])==6
    result=batch._apply(draft,assets,'epoch',req)
    assert pending_asset_indexes(result.blocks[0])==(6,)
    assert len(result.blocks[0].client_asset_reviews)==6
    assert not draft.blocks[0].client_asset_reviews


def test_opt_out_remains_pending_and_does_not_remove_content():
    draft,assets=sample();req,draft=request(draft,assets)
    req['left']=(req['entries'][2],)
    result=batch._apply(draft,assets,'epoch',req)
    assert pending_asset_indexes(result.blocks[0])==(2,6)
    assert result.blocks[0].asset_hashes==draft.blocks[0].asset_hashes


@pytest.mark.parametrize('change',['actor','month','incarnation','caption','reorder','replacement','provenance','missing','corrupt'])
def test_stale_or_invalid_batch_grants_no_partial_receipts(change):
    draft,assets=sample();req,draft=request(draft,assets);epoch='epoch';block=draft.blocks[0]
    if change=='actor':draft=replace(draft,prepared_by='Other operator')
    elif change=='month':draft=replace(draft,period=ReportPeriod(2026,11))
    elif change=='incarnation':epoch='new epoch'
    elif change=='caption':draft=replace(draft,blocks=(replace(block,asset_captions=('Changed',*block.asset_captions[1:])),))
    elif change=='reorder':draft=replace(draft,blocks=(replace(block,asset_hashes=block.asset_hashes[::-1]),))
    elif change=='replacement':draft=replace(draft,blocks=(replace(block,asset_hashes=(*block.asset_hashes[:-1],'new.png')),))
    elif change=='provenance':draft=replace(draft,blocks=(replace(block,references=('other-source',),asset_provenance=tuple((ref,('other-source',)) for ref in block.asset_hashes)),))
    elif change=='missing':assets.pop(block.asset_hashes[4])
    else:assets[block.asset_hashes[4]]=b'bad image'
    with pytest.raises((ValueError,OSError)):batch._apply(draft,assets,epoch,req)
    assert not draft.blocks[0].client_asset_reviews


def test_duplicate_fingerprint_occurrences_use_individual_fallback():
    draft,assets=sample(1);b=draft.blocks[0]
    draft=replace(draft,blocks=(replace(b,asset_hashes=b.asset_hashes*2,asset_captions=b.asset_captions*2),))
    draft,entries,_=batch._manifest(draft,'epoch')
    selected,_,fallback=batch._choose(draft,assets,entries,())
    assert not selected and fallback=={'vendor_reports'}


def test_pixels_and_bytes_are_bounded_without_decoding_huge_images(monkeypatch):
    draft,assets=sample();draft,entries,_=batch._manifest(draft,'epoch')
    monkeypatch.setattr(batch,'MAX_BATCH_PIXELS',800)
    selected,images,_=batch._choose(draft,assets,entries,())
    assert len(selected)==2 and sum(pixels for _,pixels in images)==800


APP='''
import streamlit as st
from test_monthly_report_picture_batch import sample
from app.monthly_report_picture_batch_ui import review_picture_batch
from picture_batch_test_adapter import install
if 'draft' not in st.session_state:
 st.session_state.draft,st.session_state.assets=sample(21)
with install():
 st.session_state.draft=review_picture_batch(st.session_state.draft,st.session_state.assets,'synthetic',lambda k,v:k,incarnation='epoch')
'''


def submit(app):
    return next(b for b in app.button if b.label.startswith('Confirm these'))


def test_frontend_emulator_does_not_escape_each_apptest_rerun():
    production = batch._render_group
    app = AppTest.from_string(APP).run()
    assert not app.exception
    assert batch._render_group is production
    submit(app).click().run()
    assert not app.exception
    assert batch._render_group is production


def test_frontend_emulator_restores_production_after_failure():
    from picture_batch_test_adapter import install
    production = batch._render_group
    with pytest.raises(RuntimeError, match='Synthetic test failure'):
        with install():
            assert batch._render_group is not production
            raise RuntimeError('Synthetic test failure')
    assert batch._render_group is production


def test_server_receipts_for_21_pictures_take_four_emulated_submissions_not_21():
    app=AppTest.from_string(APP).run()
    for count in (6,6,6,3):
        assert not app.exception
        assert str(count) in submit(app).label
        assert len(app.checkbox)==count
        assert len(app.get('image'))==count
        submit(app).click().run()
    assert not app.exception
    assert not pending_asset_indexes(app.session_state.draft.blocks[0])
    assert not any(b.label.startswith('Confirm these') for b in app.button)


def test_deferred_form_switch_has_no_approval_until_submit():
    app=AppTest.from_string(APP).run()
    app.checkbox[0].check()
    assert len(pending_asset_indexes(app.session_state.draft.blocks[0]))==21
    submit(app).click().run()
    assert not app.exception
    assert 0 in pending_asset_indexes(app.session_state.draft.blocks[0])
    assert len(pending_asset_indexes(app.session_state.draft.blocks[0]))==16


def test_old_individual_session_cache_cannot_approve_new_batch():
    app=AppTest.from_string(APP).run()
    block=app.session_state.draft.blocks[0]
    app.session_state['synthetic_client_vendor_reports_approved_pictures']=tuple(asset_fingerprint(block,i) for i in range(21))
    app.run()
    assert len(pending_asset_indexes(app.session_state.draft.blocks[0]))==21


def test_hidden_or_removed_source_cannot_be_approved():
    from app.monthly_report_model import ReportSource
    draft,assets=sample();block=draft.blocks[0]
    source=ReportSource('source','Synthetic vendor.pdf','source-hash','pdf',page_texts=('Inspection',)*7,selected_pages=tuple(range(1,8)),facility=draft.profile.facilities[0].title)
    from app.monthly_report_content_policy import page_fingerprint
    source=replace(source,client_page_reviews=tuple((i,page_fingerprint(source,i)) for i in range(1,8)))
    refs=tuple(f'source:{i+1}:{source.fingerprint}' for i in range(7))
    block=replace(block,references=refs)
    draft=replace(draft,blocks=(block,),sources=(source,))
    req,draft=request(draft,assets)
    with pytest.raises(ValueError):batch._apply(replace(draft,sources=()),assets,'epoch',req)
    with pytest.raises(ValueError):batch._apply(replace(draft,sources=(replace(source,selected_pages=()),)),assets,'epoch',req)
    with pytest.raises(ValueError):batch._apply(replace(draft,sources=(replace(source,facility='Other facility'),)),assets,'epoch',req)


def test_deferred_picture_ignores_legacy_cache():
    app=AppTest.from_string(APP).run()
    block=app.session_state.draft.blocks[0]
    app.session_state['synthetic_client_vendor_reports_approved_pictures']=(asset_fingerprint(block,0),)
    app.checkbox[0].check();submit(app).click().run()
    assert not app.exception
    assert 0 in pending_asset_indexes(app.session_state.draft.blocks[0])
    assert len(app.get('image'))==6


def test_truncated_raster_is_not_approvable_by_group_or_fallback():
    app=AppTest.from_string(APP).run()
    out=BytesIO();Image.new('RGB',(20,20),'red').save(out,format='JPEG')
    raw=out.getvalue()[:-20];ref=asset_reference(raw,'jpg')
    draft=app.session_state.draft
    draft=replace(draft,blocks=(replace(draft.blocks[0],asset_hashes=(ref,),asset_captions=('Broken raster',)),))
    _,entries,_=batch._manifest(draft,'epoch')
    with pytest.raises(OSError):batch._read_picture(draft,{ref:raw},entries[0])
    app.session_state.draft=draft;app.session_state.assets={ref:raw};app.run()
    assert not app.exception
    assert pending_asset_indexes(app.session_state.draft.blocks[0])==(0,)
    assert not any(b.label.startswith('Confirm these') for b in app.button)
    assert any(b.label.startswith('Remove picture') for b in app.button)
    assert any('cannot be safely displayed' in w.value for w in app.warning)


def test_current_individual_fallback_click_still_records_only_visible_picture():
    app=AppTest.from_string(APP).run()
    app.checkbox[0].check();submit(app).click().run()
    assert not app.exception
    for _ in range(3):
        submit(app).click().run()
    before=pending_asset_indexes(app.session_state.draft.blocks[0])
    assert before==(0,)
    submit(app).click().run()
    assert not app.exception
    assert pending_asset_indexes(app.session_state.draft.blocks[0])==before[1:]


@pytest.mark.parametrize('change',['missing','short','not_loaded','nonboolean','nonce','identity'])
def test_component_submission_requires_complete_loaded_exact_context(monkeypatch,change):
    draft,assets=sample();req,_=request(draft,assets)
    envelope={k:req[k] for k in ('identity','entries')}|{'nonce':'shown'}
    value={'identity':envelope['identity'],'nonce':'shown','loaded':[True]*6,'left':[False]*6}
    if change=='missing':value.pop('left')
    if change=='short':value['left'].pop()
    if change=='not_loaded':value['loaded'][0]=False
    if change=='nonboolean':value['left'][0]=0
    if change in ('nonce','identity'):value[change]='obsolete'
    state={'x_picture_batch_active':envelope,'component':{'submission':value}}
    monkeypatch.setattr(batch.st,'session_state',state)
    batch._queue_component('x',envelope,'component')
    assert 'x_picture_batch_request' not in state


def test_fallback_reads_only_one_current_picture_not_60_or_approved(monkeypatch):
    app=AppTest.from_string(APP.replace('sample(21)','sample(60)')).run()
    app.checkbox[0].check();submit(app).click().run()
    while len(pending_asset_indexes(app.session_state.draft.blocks[0])) > 1:
        submit(app).click().run()
    reads=[];original=batch._read_picture
    def count(*args):
        reads.append(args[2]);return original(*args)
    monkeypatch.setattr(batch,'_read_picture',count)
    app.run()
    assert not app.exception
    assert len(reads)==1 and reads[0][1]==0
    assert len(app.get('image'))==1


def test_oversized_cover_logo_remains_explicitly_removable(monkeypatch):
    app=AppTest.from_string(APP).run()
    draft,assets=sample(1)
    block=replace(draft.blocks[0],key='client_logo')
    section=SectionSpec('cover','1','Cover',(BlockSpec('client_logo','image'),))
    app.session_state.draft=replace(draft,blocks=(block,),sections=(section,))
    app.session_state.assets=assets
    monkeypatch.setattr(batch,'MAX_IMAGE_BYTES',20)
    app.run()
    assert not app.exception
    assert pending_asset_indexes(app.session_state.draft.blocks[0])==(0,)
    next(b for b in app.button if b.label=='Remove picture 1 from client logo').click().run()
    assert not app.exception
    assert app.session_state.draft.blocks[0].asset_hashes==()
    assert assets # Saved original payload was not deleted.


def test_stale_removal_callback_cannot_remove_reopened_picture(monkeypatch):
    draft,assets=sample();req,_=request(draft,assets)
    old={'identity':req['identity'],'entries':req['entries'],'nonce':'old'}
    state={'x_picture_remove_active':{**old,'nonce':'reopened'}}
    monkeypatch.setattr(batch.st,'session_state',state)
    batch._queue_remove('x',old,req['entries'][0])
    assert 'x_picture_remove_request' not in state


def test_component_callback_is_single_use_and_rejects_reopened_envelope(monkeypatch):
    draft,assets=sample();req,_=request(draft,assets)
    envelope={k:req[k] for k in ('identity','entries')}|{'nonce':'shown'}
    value={'identity':envelope['identity'],'nonce':'shown','loaded':[True]*6,'left':[False]*6}
    state={'x_picture_batch_active':envelope,'component':{'submission':value}}
    monkeypatch.setattr(batch.st,'session_state',state)
    batch._queue_component('x',envelope,'component')
    assert state.pop('x_picture_batch_request')['left']==()
    batch._queue_component('x',envelope,'component')
    assert 'x_picture_batch_request' not in state
    state['x_picture_batch_active']={**envelope,'nonce':'reopened'}
    batch._queue_component('x',envelope,'component')
    assert 'x_picture_batch_request' not in state


def test_deferred_occurrence_does_not_block_later_groups():
    app=AppTest.from_string(APP).run()
    app.checkbox[0].check();submit(app).click().run()
    for expected in (tuple(range(6,12)),tuple(range(12,18)),tuple(range(18,21))):
        active=app.session_state['synthetic_picture_batch_active']
        assert tuple(e[1] for e in active['entries'])==expected
        assert 0 in pending_asset_indexes(app.session_state.draft.blocks[0])
        submit(app).click().run()
    assert pending_asset_indexes(app.session_state.draft.blocks[0])==(0,)
    assert len(app.get('image'))==1
    assert app.session_state.draft.blocks[0].asset_hashes==sample(21)[0].blocks[0].asset_hashes


@pytest.mark.parametrize('difference',['same','caption','provenance','different_assets'])
def test_duplicate_block_keys_reject_apply_and_selection_without_mutation(difference):
    draft,assets=sample();req,draft=request(draft,assets)
    other=draft.blocks[0]
    if difference=='caption':other=replace(other,asset_captions=('Unseen caption',*other.asset_captions[1:]))
    if difference=='provenance':other=replace(other,references=('unseen-source',))
    if difference=='different_assets':other=replace(other,asset_hashes=other.asset_hashes[::-1])
    ambiguous=replace(draft,blocks=(*draft.blocks,other))
    for candidate in (ambiguous,replace(ambiguous,blocks=ambiguous.blocks[::-1])):
        with pytest.raises(ValueError,match='Repeated section'):
            batch._apply(candidate,assets,'epoch',req)
        _,entries,_=batch._manifest(candidate,'epoch')
        with pytest.raises(ValueError,match='Repeated section'):
            batch._choose(candidate,assets,entries,())
        assert all(not b.client_asset_reviews for b in candidate.blocks)


def test_duplicate_keys_revoke_queued_review_and_removal_preserving_original_draft(monkeypatch):
    draft,assets=sample();req,draft=request(draft,assets)
    envelope={k:req[k] for k in ('identity','entries')}|{'nonce':'shown'}
    state={'x_picture_batch_active':envelope,'x_picture_batch_request':req,
           'x_picture_remove_active':envelope,'x_picture_remove_request':(envelope,req['entries'][0]),
           'x_picture_correction_active':envelope,'x_picture_correction_cursor':(req['identity'],req['entries'][0])}
    monkeypatch.setattr(batch.st,'session_state',state)
    warnings=[];monkeypatch.setattr(batch.st,'warning',warnings.append)
    ambiguous=replace(draft,blocks=(*draft.blocks,replace(draft.blocks[0],text='Unseen block retained')))
    result=batch.review_picture_batch(ambiguous,assets,'x',lambda k,v:k,incarnation='epoch')
    assert result is ambiguous and not state and warnings
    batch._queue_remove('x',envelope,req['entries'][0])
    state['component']={'submission':{'identity':req['identity'],'nonce':'shown','loaded':[True]*6,'left':[False]*6}}
    batch._queue_component('x',envelope,'component')
    assert 'x_picture_batch_request' not in state and 'x_picture_remove_request' not in state


def test_all_deferred_occurrences_remain_navigable_without_approval_or_removal():
    app=AppTest.from_string(APP.replace('sample(21)','sample(7)')).run()
    for checkbox in app.checkbox:checkbox.check()
    submit(app).click().run()
    assert tuple(e[1] for e in app.session_state['synthetic_picture_batch_active']['entries'])==(6,)
    app.checkbox[0].check();submit(app).click().run()
    first_nonce=app.session_state['synthetic_picture_batch_active']['nonce']
    original_hashes=app.session_state.draft.blocks[0].asset_hashes
    for expected in range(7):
        assert tuple(e[1] for e in app.session_state['synthetic_picture_batch_active']['entries'])==(expected,)
        app.checkbox[0].check();submit(app).click().run()
        assert pending_asset_indexes(app.session_state.draft.blocks[0])==tuple(range(7))
    assert tuple(e[1] for e in app.session_state['synthetic_picture_batch_active']['entries'])==(0,)
    assert app.session_state['synthetic_picture_batch_active']['nonce']!=first_nonce
    assert app.session_state.draft.blocks[0].asset_hashes==original_hashes


def test_unsafe_first_correction_can_be_skipped_without_consent_and_cycles(monkeypatch):
    app=AppTest.from_string(APP.replace('sample(21)','sample(2)')).run()
    for checkbox in app.checkbox:checkbox.check()
    submit(app).click().run()
    draft=app.session_state.draft
    refs=draft.blocks[0].asset_hashes
    assets=dict(app.session_state.assets);assets[refs[0]]=b'corrupt synthetic picture'
    app.session_state.assets=assets
    app.run()
    assert not app.exception
    assert not any(b.label.startswith('Confirm these') for b in app.button)
    original_navigation=app.session_state['synthetic_picture_correction_active']
    next(b for b in app.button if b.label=='Next picture to correct').click().run()
    assert not app.exception
    assert tuple(e[1] for e in app.session_state['synthetic_picture_batch_active']['entries'])==(1,)
    visible=app.session_state['synthetic_picture_batch_active']
    removal=app.session_state['synthetic_picture_remove_active']
    next(b for b in app.button if b.label=='Next picture to correct').click().run()
    assert not app.exception
    assert app.session_state['synthetic_picture_correction_active']['nonce']!=original_navigation['nonce']
    assert pending_asset_indexes(app.session_state.draft.blocks[0])==(0,1)
    assert app.session_state.draft.blocks[0].asset_hashes==refs
    # Delayed events from either prior view cannot navigate, approve, or remove.
    state=dict(app.session_state.filtered_state)
    monkeypatch.setattr(batch.st,'session_state',state)
    cursor=state.get('synthetic_picture_correction_cursor')
    batch._next_correction('synthetic',original_navigation,original_navigation['entries'][1])
    assert state.get('synthetic_picture_correction_cursor')==cursor
    batch._queue_remove('synthetic',removal,removal['entries'][0])
    state['old_component']={'submission':{'identity':visible['identity'],'nonce':visible['nonce'],'loaded':[True],'left':[False]}}
    batch._queue_component('synthetic',visible,'old_component')
    assert 'synthetic_picture_batch_request' not in state
    assert 'synthetic_picture_remove_request' not in state
