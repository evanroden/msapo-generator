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
if 'draft' not in st.session_state:
 st.session_state.draft,st.session_state.assets=sample(21)
st.session_state.draft=review_picture_batch(st.session_state.draft,st.session_state.assets,'synthetic',lambda k,v:k,incarnation='epoch')
'''


def submit(app):
    return next(b for b in app.button if b.label.startswith('Confirm these'))


def test_native_form_21_pictures_take_four_submissions_not_21():
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


def test_callback_rejects_unrendered_and_repeated_submissions(monkeypatch):
    draft,assets=sample();req,_=request(draft,assets)
    state={};monkeypatch.setattr(batch.st,'session_state',state)
    envelope={k:req[k] for k in ('identity','entries')}|{'nonce':'shown'}
    keys=tuple('leave'+str(i) for i in range(6))
    batch._queue('x',envelope,keys)
    assert 'x_picture_batch_request' not in state
    state['x_picture_batch_active']=envelope
    state.update({key: False for key in keys})
    batch._queue('x',envelope,keys)
    assert state['x_picture_batch_request']['entries']==envelope['entries']
    state.pop('x_picture_batch_request')
    batch._queue('x',envelope,keys)
    assert 'x_picture_batch_request' not in state
    # Old callback cannot act on a reopened identical set with a new incarnation.
    state['x_picture_batch_active']={**envelope,'nonce':'reopened'}
    batch._queue('x',envelope,keys)
    assert 'x_picture_batch_request' not in state


def test_failed_image_display_disables_entire_group(monkeypatch):
    real=batch.st.image
    calls=[]
    def broken(*a,**kw):
        calls.append(1)
        if len(calls)==3:raise ValueError('Synthetic image display failure')
        return real(*a,**kw)
    monkeypatch.setattr(batch.st,'image',broken)
    app=AppTest.from_string(APP).run()
    assert not app.exception
    assert submit(app).disabled
    assert len(pending_asset_indexes(app.session_state.draft.blocks[0]))==21
    assert 'synthetic_picture_batch_active' not in app.session_state.filtered_state


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


def test_deferred_picture_ignores_legacy_cache_and_rotates_reopened_fallback():
    app=AppTest.from_string(APP).run()
    block=app.session_state.draft.blocks[0]
    app.session_state['synthetic_client_vendor_reports_approved_pictures']=(asset_fingerprint(block,0),)
    app.checkbox[0].check();submit(app).click().run()
    assert not app.exception
    assert 0 in pending_asset_indexes(app.session_state.draft.blocks[0])
    old_scope=app.session_state['synthetic_picture_individual_scope']
    old_key='synthetic_picture_individual_'+old_scope[1]+'_client_vendor_reports_approved_pictures'
    # Leave and reopen the same report; a late compatibility callback can only
    # write its obsolete namespace, never confer current consent.
    app.session_state['synthetic_picture_batch_deferred']=()
    app.run()
    app.session_state['synthetic_picture_batch_deferred']=(asset_fingerprint(block,0),)
    app.session_state[old_key]=(asset_fingerprint(block,0),)
    app.run()
    assert not app.exception
    assert app.session_state['synthetic_picture_individual_scope'][1]!=old_scope[1]
    assert 0 in pending_asset_indexes(app.session_state.draft.blocks[0])


@pytest.mark.parametrize('kind', ['missing','short','duplicate','nonboolean'])
def test_callback_requires_complete_exact_boolean_form(monkeypatch,kind):
    draft,assets=sample();req,_=request(draft,assets)
    envelope={k:req[k] for k in ('identity','entries')}|{'nonce':'shown'}
    keys=tuple('leave'+str(i) for i in range(6))
    state={'x_picture_batch_active':envelope,**{k:False for k in keys}}
    if kind=='missing':state.pop(keys[-1])
    if kind=='short':keys=keys[:-1]
    if kind=='duplicate':keys=keys[:-1]+(keys[0],)
    if kind=='nonboolean':state[keys[0]]=None
    monkeypatch.setattr(batch.st,'session_state',state)
    batch._queue('x',envelope,keys)
    assert 'x_picture_batch_request' not in state


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
    assert not app.button
    assert any('cannot be safely displayed' in w.value for w in app.warning)


def test_current_individual_fallback_click_still_records_only_visible_picture():
    app=AppTest.from_string(APP).run()
    app.checkbox[0].check();submit(app).click().run()
    assert not app.exception
    before=pending_asset_indexes(app.session_state.draft.blocks[0])
    assert before[0]==0
    next(b for b in app.button if b.label=='This page is ready to include').click().run()
    assert not app.exception
    assert pending_asset_indexes(app.session_state.draft.blocks[0])==before[1:]
