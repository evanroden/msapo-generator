"""Synthetic immutable-page financial admission; other routes stay conservative."""
from dataclasses import asdict, replace
from io import BytesIO
import importlib
import fitz
import pytest
from docx import Document
from app import monthly_report_sources as sources, monthly_report_library as library
from app.monthly_report_model import synthetic_profiles, ReportDraft, ReportPeriod, SectionSpec, BlockSpec
from app.monthly_report_content_policy import page_allowed


def setup(monkeypatch,tmp_path,text='ENFRA client commissioning report. Verified annual savings: $125. Performance findings reviewed for this facility.'):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    profile=synthetic_profiles()[0]
    pdf=fitz.open();page=pdf.new_page();page.insert_text((40,80),text);raw=pdf.tobytes();pdf.close()
    content,_=sources.ingest(profile,'synthetic-enfra.pdf',raw)
    content=replace(content,source=replace(content.source,classification='MBCx',facility=profile.facilities[0].title,service_date='2026-09-01'))
    return profile,content,raw


def api():return importlib.import_module('app.monthly_report_mbcx_financial_pages')


def reviewed(p,c):
    m=api();return m.review_pages(p,c,(1,),source_confirmed=True,visual_fingerprints=((1,m.page_review_fingerprint(c.source,1)),),financial_semantics='client_enfra_no_vendor_totals')


def test_review_persists_and_prepares_only_mbcx(monkeypatch,tmp_path):
    p,c,raw=setup(monkeypatch,tmp_path);r=reviewed(p,c)
    assert library.source_from_dict(asdict(r.source))==r.source
    assert sources.source_bytes(p,r.source)==raw
    assert not page_allowed(r.source,1)
    assert page_allowed(r.source,1,profile=p,destination='mbcx_report')
    block,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    assert block.asset_hashes
    with pytest.raises(ValueError):sources.prepare_pages(p,(r,),((r.source.id,'water_reports'),))
    assert not c.source.client_page_reviews


@pytest.mark.parametrize('change',['source','site','caption','page','semantics','visual','unreviewed'])
def test_changed_or_unknown_review_denied(monkeypatch,tmp_path,change):
    p,c,_=setup(monkeypatch,tmp_path);m=api();r=reviewed(p,c)
    if change=='source':r=replace(r,source=replace(r.source,sha256='b'*64))
    if change=='site':p=replace(p,key='another-site')
    if change=='caption':r=replace(r,source=replace(r.source,captions=((1,'changed'),)))
    if change=='page':r=replace(r,source=replace(r.source,page_texts=('changed $126',)))
    if change=='semantics':r=replace(r,source=replace(r.source,financial_page_reviews=(replace(r.source.financial_page_reviews[0],semantics='unknown'),)))
    if change=='visual':
        with pytest.raises(ValueError):m.review_pages(p,c,(1,),source_confirmed=True,visual_fingerprints=((1,'bad'),),financial_semantics='client_enfra_no_vendor_totals')
        return
    if change=='unreviewed':r=c
    assert not page_allowed(r.source,1,profile=p,destination='mbcx_report')


@pytest.mark.parametrize('text',['ENFRA report. Vendor invoice total: $125. Client savings $500.', 'Vendor invoice amount due: 125.00', 'Supplier invoice total: $125', 'ENFRA client report.\nVendor invoice\nTotal: $125', 'Supplier Invoice\nAmount Due: $125', 'Subcontractor invoice\nBalance Due: $125'])
def test_vendor_total_veto(monkeypatch,tmp_path,text):
    p,c,_=setup(monkeypatch,tmp_path,text)
    with pytest.raises(ValueError,match='vendor'):reviewed(p,c)


def test_unknown_financial_semantics_rejected(monkeypatch,tmp_path):
    p,c,_=setup(monkeypatch,tmp_path);m=api()
    with pytest.raises(ValueError):m.review_pages(p,c,(1,),source_confirmed=True,visual_fingerprints=((1,m.page_review_fingerprint(c.source,1)),),financial_semantics='unknown')


@pytest.mark.parametrize("native", [False, True])
def test_actual_word_and_section_preview_use_same_gate(monkeypatch,tmp_path,native):
    p,c,_=setup(monkeypatch,tmp_path);r=reviewed(p,c)
    block,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    section=SectionSpec('mbcx','4','MBCx Reports',(BlockSpec('mbcx_report','pdf_pages'),))
    draft=ReportDraft(p,ReportPeriod(2026,9),'Synthetic Editor',(section,),(block,),sources=(r.source,))
    reopened=library.draft_from_dict(asdict(draft))
    assert reopened==draft
    library.save_snapshot(draft,expected_revision=0)
    assert library.load_snapshot(p.contract,p.key,draft.period).draft == draft
    if native:
        doc=Document();doc.add_paragraph('Synthetic Site');doc.add_heading('MBCx Reports',1);doc.add_paragraph('Old content')
        path=tmp_path/'synthetic-native.docx';doc.save(path)
        from app import monthly_report_designs
        monkeypatch.setattr(monthly_report_designs,'source_for',lambda profile:path)
    loader=lambda ref:library.read_asset(p.contract,p.key,ref)
    from app.monthly_report_docx import assemble_docx
    from app.monthly_report_preview import section_preview_docx
    word=assemble_docx(reopened,acknowledged_fingerprint=reopened.fingerprint,asset_loader=loader)
    assert len(Document(BytesIO(word)).inline_shapes)>0
    assert section_preview_docx(reopened,'mbcx',asset_loader=loader)
    bad=replace(reopened,profile=replace(p,key='other-site'))
    with pytest.raises(ValueError):assemble_docx(bad,acknowledged_fingerprint=bad.fingerprint,asset_loader=loader)
    with pytest.raises(ValueError):section_preview_docx(bad,'mbcx',asset_loader=loader)
    stripped_source=replace(reopened.sources[0],financial_source_review=None,financial_page_reviews=())
    stripped=replace(reopened,sources=(stripped_source,))
    from app.monthly_report_checks import preflight
    assert any(check.code=='financial_page' and check.blocking for check in preflight(stripped))
    with pytest.raises(ValueError):assemble_docx(stripped,acknowledged_fingerprint=stripped.fingerprint,asset_loader=loader)
    with pytest.raises(ValueError):section_preview_docx(stripped,'mbcx',asset_loader=loader)



def test_last_page_preparation_failure_has_no_accepted_batch(monkeypatch,tmp_path):
    p,c,_=setup(monkeypatch,tmp_path);m=api()
    doc=fitz.open();[doc.new_page().insert_text((40,80),'ENFRA savings: $125. Synthetic client-facing report.') for _ in range(2)]
    c,_=sources.ingest(p,'two-pages.pdf',doc.tobytes());doc.close()
    before=asdict(c);original=sources.page_image
    def fail_last(profile,content,number,**kwargs):
        if number==2:raise ValueError('Synthetic last-page failure')
        return original(profile,content,number,**kwargs)
    monkeypatch.setattr(sources,'page_image',fail_last)
    with pytest.raises(ValueError,match='last-page'):
        m.include_reviewed_batch(p,c,(1,2),{},source_confirmed=True,
            visual_fingerprints=tuple((n,m.page_review_fingerprint(c.source,n)) for n in (1,2)),financial_semantics=m.SEMANTICS)
    assert asdict(c)==before


@pytest.mark.parametrize('field,value',[('financial_source_review',{'version':True}),('financial_page_reviews',[{'number':True}]),('financial_page_reviews','invalid')])
def test_malformed_saved_review_is_rejected(monkeypatch,tmp_path,field,value):
    p,c,_=setup(monkeypatch,tmp_path);record=asdict(reviewed(p,c).source);record[field]=value
    with pytest.raises(library.LibraryError):library.source_from_dict(record)


def test_legacy_empty_financial_fields_preserve_source_fingerprint(monkeypatch,tmp_path):
    import hashlib,json
    p,c,_=setup(monkeypatch,tmp_path);record=asdict(c.source)
    for field in ('financial_source_review','financial_page_reviews','scope_review','pdf_text_blocks'):
        if not record.get(field):record.pop(field,None)
    # Existing model's digest uses compact JSON only through its established helper.
    from app.monthly_report_model import _digest
    assert library.source_from_dict(record).fingerprint==c.source.fingerprint
    assert hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()==c.source.fingerprint


APP='''
import streamlit as st
import fitz
from dataclasses import replace
from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_mbcx_financial_pages import render_reviewed_batch
p=synthetic_profiles()[0]
if 'content' not in st.session_state:
    pdf=fitz.open();pdf.new_page().insert_text((40,80),'ENFRA commissioning savings: $125. Synthetic client report.')
    c,_=sources.ingest(p,'synthetic-review.pdf',pdf.tobytes());pdf.close()
    st.session_state.content=replace(c,source=replace(c.source,classification='MBCx',facility=p.facilities[0].title,service_date='2026-09-01'))
from app.monthly_report_model import ReportDraft,ReportPeriod,SectionSpec,BlockSpec
from app.monthly_report_mbcx_financial_pages import apply_financial_batch
period=ReportPeriod(2026,9)
blocks=st.session_state.get('blocks',{})
section=SectionSpec('mbcx','4','MBCx Reports',(BlockSpec('mbcx_report','pdf_pages'),))
handled,c,batch=render_reviewed_batch(p,st.session_state.content,blocks,{},'test',period=period,editor_scope='test-editor',sections=(section,))
if batch:
    section=SectionSpec('mbcx','4','MBCx Reports',(BlockSpec('mbcx_report','pdf_pages'),))
    draft=ReportDraft(p,period,'Synthetic Editor',(section,),tuple(blocks.values()),sources=(c.source,))
    draft,updated=apply_financial_batch(draft,blocks,(c.source,),batch,editor_scope='test-editor',consumed=st.session_state.get('consumed',()))
    st.session_state.content=batch.revised_content
    st.session_state.blocks=updated
    st.session_state.consumed=(*st.session_state.get('consumed',()),batch.token)
st.write('Included',len(st.session_state.get('blocks',{})))
'''


def test_explicit_visual_batch_ui(monkeypatch,tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    app=AppTest.from_string(APP).run()
    app.checkbox[0].check().run()
    app.checkbox[1].check().run()
    app.multiselect[0].select(1).run()
    assert not app.exception
    assert len(app.get('image')) == 1
    assert app.button[0].disabled
    app.checkbox[-1].check().run()
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state['blocks']['mbcx_report'].asset_hashes
    app.run()
    assert all(c.label!='This is an ENFRA report intended for the client' for c in app.checkbox)


from tests.conftest import requires_libreoffice

@requires_libreoffice
@pytest.mark.parametrize('native',[False,True])
def test_actual_rendered_pdf_retains_reviewed_page(monkeypatch,tmp_path,native):
    """Required renderer gate: saved original pixels remain in real Word/PDF."""
    from zipfile import ZipFile
    from hashlib import sha256
    from app.monthly_report_docx import generate_report
    p,c,_=setup(monkeypatch,tmp_path)
    pdf=fitz.open();page=pdf.new_page();page.insert_text((40,80),'ENFRA client savings $125. Synthetic report.')
    page.draw_rect(fitz.Rect(40,110,90,160),fill=(1,0,1),color=(1,0,1))
    c,_=sources.ingest(p,'synthetic-visible-money.pdf',pdf.tobytes());pdf.close()
    c=replace(c,source=replace(c.source,classification='MBCx',facility=p.facilities[0].title,service_date='2026-09-01'))
    r=reviewed(p,c);block,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    section=SectionSpec('mbcx','4','MBCx Reports',(BlockSpec('mbcx_report','pdf_pages'),))
    draft=ReportDraft(p,ReportPeriod(2026,9),'Synthetic Editor',(section,),(block,),sources=(r.source,))
    if native:
        from app import monthly_report_designs
        doc=Document();doc.add_heading('MBCx Reports',1);doc.add_paragraph('Old content')
        path=tmp_path/'native-financial.docx';doc.save(path)
        monkeypatch.setattr(monthly_report_designs,'source_for',lambda profile:path)
    loader=lambda ref:library.read_asset(p.contract,p.key,ref)
    package=generate_report(draft,acknowledged_fingerprint=draft.fingerprint,asset_loader=loader)
    assert package.pdf, package.pdf_error
    # The reviewed amount is part of this exact unchanged source-page raster.
    with ZipFile(BytesIO(package.docx)) as z:
        media=[z.read(name) for name in z.namelist() if name.startswith('word/media/')]
        from PIL import Image
        expected=Image.open(BytesIO(loader(block.asset_hashes[0]))).convert('RGB')
        assert any(Image.open(BytesIO(data)).convert('RGB').size==expected.size
                   and Image.open(BytesIO(data)).convert('RGB').tobytes()==expected.tobytes() for data in media)
    with fitz.open(stream=package.pdf,filetype='pdf') as output:
        magenta=0
        for page in output:
            pix=page.get_pixmap(colorspace=fitz.csRGB)
            pixels=pix.samples
            magenta+=sum(pixels[i]>200 and pixels[i+1]<80 and pixels[i+2]>200 for i in range(0,len(pixels),3))
        assert magenta>100


def test_financial_review_preserves_site_review_but_site_change_invalidates_financial(monkeypatch,tmp_path):
    from app.monthly_report_source_scope import correct_scope,reviewed_scope
    p,c,_=setup(monkeypatch,tmp_path)
    c=replace(c,source=correct_scope(c.source,p,(p.facilities[0].key,)))
    r=reviewed(p,c)
    assert reviewed_scope(r.source,p)==reviewed_scope(c.source,p)
    assert page_allowed(r.source,1,profile=p,destination='mbcx_report')
    changed=replace(r.source,scope_review='changed-site-review')
    assert not page_allowed(changed,1,profile=p,destination='mbcx_report')


def test_visual_preview_failure_never_authorizes_include(monkeypatch,tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    app=AppTest.from_string(APP).run()
    app.checkbox[0].check().run()
    app.checkbox[1].check().run()
    def unavailable(*args,**kwargs):raise ValueError('Synthetic preview unavailable')
    monkeypatch.setattr(sources,'page_image',unavailable)
    app.multiselect[0].select(1).run()
    assert not app.exception
    assert app.button[0].disabled and app.checkbox[-1].disabled
    assert not app.get('image')
    assert app.session_state['content'].source.financial_source_review is None


def test_invoice_header_and_far_away_total_are_still_known_vendor_evidence(monkeypatch,tmp_path):
    text='Vendor invoice\n'+('Synthetic line item. '*30)+'\nTotal: $125'
    p,c,_=setup(monkeypatch,tmp_path)
    c=replace(c,source=replace(c.source,page_texts=(text,)))
    assert api().known_vendor_total(c.source,1)


def test_first_financial_page_preserves_existing_nonfinancial_page_and_omissions(monkeypatch,tmp_path):
    from app.monthly_report_content_policy import page_fingerprint
    from app.monthly_report_asset_review import pending_asset_indexes
    from app.monthly_report_source_status import source_manager_status
    p,c,_=setup(monkeypatch,tmp_path);pdf=fitz.open()
    for text in ('Technical observations: pump pressure 125 psi and stable performance.', 'ENFRA client savings: $125.', 'Deliberately omitted technical page.'):
        pdf.new_page().insert_text((40,80),text)
    c,_=sources.ingest(p,'mixed-enfra.pdf',pdf.tobytes());pdf.close()
    s=replace(c.source,classification='MBCx',facility=p.facilities[0].title,service_date='2026-09-01',selected_pages=(1,))
    s=replace(s,client_page_reviews=((1,page_fingerprint(s,1)),),client_page_exclusions=((3,page_fingerprint(s,3)),))
    c=replace(c,source=s);existing,=sources.prepare_pages(p,(c,),((s.id,'mbcx_report'),))
    m=api();r,additions,replacements=m.include_reviewed_batch(p,c,(2,),{existing.key:existing},source_confirmed=True,
        visual_fingerprints=((2,m.page_review_fingerprint(s,2)),),financial_semantics=m.SEMANTICS)
    assert page_allowed(r.source,1) and not pending_asset_indexes(existing,(r.source,))
    assert additions['mbcx_report'].references==(sources.source_reference(r.source,2),)
    assert r.source.client_page_exclusions==s.client_page_exclusions and 3 not in r.source.selected_pages
    # Removing financial metadata cannot reuse the generic old visual approval.
    stripped=replace(r.source,financial_source_review=None,financial_page_reviews=())
    assert not page_allowed(stripped,2,profile=p,destination='mbcx_report')
    assert page_allowed(stripped,1)


def test_in_place_financial_rereview_keeps_picture_identity_caption_and_manual_content(monkeypatch,tmp_path):
    from app.monthly_report_asset_review import pending_asset_indexes
    p,c,_=setup(monkeypatch,tmp_path);m=api();r=reviewed(p,c)
    block,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    block=replace(block,text='Keep my manually entered context.',asset_captions=('My retained caption',))
    stale=replace(r,source=replace(r.source,financial_source_review=None,financial_page_reviews=()))
    before=asdict(block)
    renewed,additions,replacements=m.include_reviewed_batch(p,stale,(1,),{block.key:block},source_confirmed=True,
        visual_fingerprints=((1,m.page_review_fingerprint(stale.source,1)),),financial_semantics=m.SEMANTICS)
    assert not additions and asdict(block)==before
    fixed=replacements['mbcx_report']
    assert fixed.asset_hashes==block.asset_hashes and fixed.asset_captions==block.asset_captions
    assert fixed.text==block.text and [i.key for i in fixed.asset_instances]==[i.key for i in block.asset_instances]
    assert page_allowed(renewed.source,1,profile=p,destination=block.key)
    assert not pending_asset_indexes(fixed,(renewed.source,))


@pytest.mark.parametrize("edited", [False, True])
def test_mixed_existing_new_batch_failure_keeps_existing_review_and_content(monkeypatch,tmp_path,edited):
    p,c,_=setup(monkeypatch,tmp_path);m=api();pdf=fitz.open()
    for text in ('ENFRA savings $125.','ENFRA savings $250.'):
        pdf.new_page().insert_text((40,80),text)
    c,_=sources.ingest(p,'mixed-review.pdf',pdf.tobytes());pdf.close();r=reviewed(p,c)
    block,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    if edited:block=edited_picture(p,block)
    before=(asdict(r),asdict(block));original=sources.page_image
    def fail_new(profile,content,number,**kwargs):
        if number==2:raise ValueError('Synthetic new-page preparation failure')
        return original(profile,content,number,**kwargs)
    monkeypatch.setattr(sources,'page_image',fail_new)
    with pytest.raises(ValueError,match='new-page'):
        m.include_reviewed_batch(p,r,(1,2),{block.key:block},replace_edited=edited,source_confirmed=False,
            visual_fingerprints=tuple((n,m.page_review_fingerprint(r.source,n)) for n in (1,2)),financial_semantics=m.SEMANTICS)
    assert before==(asdict(r),asdict(block))


def test_in_place_batch_never_revives_deliberate_exclusion(monkeypatch,tmp_path):
    from app.monthly_report_content_policy import page_fingerprint
    p,c,_=setup(monkeypatch,tmp_path);m=api();r=reviewed(p,c)
    block,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    excluded=replace(r,source=replace(r.source,client_page_exclusions=((1,page_fingerprint(r.source,1)),)))
    before=(asdict(excluded),asdict(block))
    with pytest.raises(ValueError,match='excluded'):
        m.include_reviewed_batch(p,excluded,(1,),{block.key:block},source_confirmed=False,
            visual_fingerprints=((1,m.page_review_fingerprint(excluded.source,1)),),financial_semantics=m.SEMANTICS)
    assert before==(asdict(excluded),asdict(block))


def edited_picture(profile,block):
    from PIL import Image
    from app.monthly_report_asset_instances import asset_instances,with_asset_instances
    raw=BytesIO();Image.new('RGB',(20,30),'navy').save(raw,format='PNG');data=raw.getvalue()
    ref=library.asset_reference(data,'png')
    library._atomic_write(library._profile_path(profile.contract,profile.key)/'assets'/ref,data)
    items=list(asset_instances(block));items[0]=replace(items[0],asset=ref)
    return with_asset_instances(replace(block,asset_hashes=(ref,*block.asset_hashes[1:])),items)


def test_edited_art_requires_explicit_in_place_replacement_and_keeps_history(monkeypatch,tmp_path):
    p,c,_=setup(monkeypatch,tmp_path);m=api();r=reviewed(p,c)
    original,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    edited=edited_picture(p,replace(original,asset_captions=('Keep caption',),text='Keep entered context'))
    before=asdict(edited);retained=library.read_asset(p.contract,p.key,edited.asset_hashes[0])
    args=dict(source_confirmed=False,visual_fingerprints=((1,m.page_review_fingerprint(r.source,1)),),financial_semantics=m.SEMANTICS)
    with pytest.raises(ValueError,match='replacement in place'):
        m.include_reviewed_batch(p,r,(1,),{edited.key:edited},**args)
    renewed,additions,replacements=m.include_reviewed_batch(p,r,(1,),{edited.key:edited},replace_edited=True,**args)
    result=replacements[edited.key]
    assert not additions and result.asset_hashes==original.asset_hashes
    assert result.asset_captions==edited.asset_captions and result.text==edited.text
    assert result.asset_instances[0].key==edited.asset_instances[0].key
    assert asdict(edited)==before and library.read_asset(p.contract,p.key,edited.asset_hashes[0])==retained


def test_identical_picture_bytes_do_not_transfer_occurrence_review(monkeypatch,tmp_path):
    from app.monthly_report_asset_review import asset_fingerprint,pending_asset_indexes
    p,c,_=setup(monkeypatch,tmp_path);m=api();pdf=fitz.open()
    for _ in range(2):pdf.new_page().insert_text((40,80),'ENFRA savings $125.')
    c,_=sources.ingest(p,'identical-pages.pdf',pdf.tobytes());pdf.close()
    r=m.review_pages(p,c,(1,2),source_confirmed=True,
        visual_fingerprints=tuple((n,m.page_review_fingerprint(c.source,n)) for n in (1,2)),financial_semantics=m.SEMANTICS)
    block,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    assert block.asset_hashes[0]==block.asset_hashes[1]
    assert block.asset_instances[0].key!=block.asset_instances[1].key
    block=replace(block,client_reviewed_fingerprint='',client_asset_reviews=(asset_fingerprint(block,0),))
    renewed,additions,replacements=m.include_reviewed_batch(p,r,(1,),{block.key:block},source_confirmed=False,
        visual_fingerprints=((1,m.page_review_fingerprint(r.source,1)),),financial_semantics=m.SEMANTICS)
    fixed=replacements[block.key]
    assert not additions and fixed.asset_hashes==block.asset_hashes
    assert [i.key for i in fixed.asset_instances]==[i.key for i in block.asset_instances]
    assert pending_asset_indexes(fixed,(renewed.source,))==(1,)


def test_edited_picture_ui_shows_both_and_requires_explicit_replacement(monkeypatch,tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    app=AppTest.from_string(APP).run();app.checkbox[0].check().run();app.checkbox[1].check().run()
    app.multiselect[0].select(1).run();app.checkbox[-1].check().run();app.button[0].click().run()
    p=synthetic_profiles()[0];original=app.session_state['blocks']['mbcx_report']
    edited=edited_picture(p,replace(original,asset_captions=('Keep my caption',)))
    app.session_state['blocks']={'mbcx_report':edited}
    app.run();app.multiselect[0].select(1).run()
    assert not app.exception and len(app.get('image'))==2
    checks={c.label:c for c in app.checkbox}
    visual=next(c for label,c in checks.items() if label.startswith('I reviewed'))
    visual.check().run()
    assert app.button[0].disabled
    replacement=next(c for c in app.checkbox if c.label.startswith('Replace the edited'))
    replacement.check().run();app.button[0].click().run()
    assert not app.exception
    final=app.session_state['blocks']['mbcx_report']
    assert final.asset_hashes==original.asset_hashes and final.asset_captions==edited.asset_captions
    assert final.asset_instances[0].key==edited.asset_instances[0].key


def test_retained_caption_cannot_relabel_approved_amount_as_vendor_total(monkeypatch,tmp_path):
    p,c,_=setup(monkeypatch,tmp_path);m=api();r=reviewed(p,c)
    block,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    block=replace(block,asset_captions=('Vendor invoice total',))
    before=asdict(block)
    with pytest.raises(ValueError,match='vendor-invoice total'):
        m.include_reviewed_batch(p,r,(1,),{block.key:block},source_confirmed=False,
            visual_fingerprints=((1,m.page_review_fingerprint(r.source,1)),),financial_semantics=m.SEMANTICS)
    assert asdict(block)==before


def test_final_gate_checks_vendor_semantics_of_retained_caption(monkeypatch,tmp_path):
    from app.monthly_report_asset_review import approve_all_assets
    from app.monthly_report_checks import preflight
    p,c,_=setup(monkeypatch,tmp_path);r=reviewed(p,c)
    block,=sources.prepare_pages(p,(r,),((r.source.id,'mbcx_report'),))
    block=approve_all_assets(replace(block,asset_captions=('Vendor invoice total',)))
    section=SectionSpec('mbcx','4','MBCx Reports',(BlockSpec('mbcx_report','pdf_pages'),))
    draft=ReportDraft(p,ReportPeriod(2026,9),'Synthetic Editor',(section,),(block,),sources=(r.source,))
    assert any(c.code=='financial_page' and c.blocking for c in preflight(draft))
    from app.monthly_report_preview import section_preview_docx
    with pytest.raises(ValueError):section_preview_docx(draft,'mbcx',asset_loader=lambda ref:library.read_asset(p.contract,p.key,ref))


@pytest.mark.parametrize('populated',[True,False])
def test_omitted_retained_target_cannot_be_overwritten_by_new_page(monkeypatch,tmp_path,populated):
    from app.monthly_report_model import ResolvedBlock
    from app.monthly_report_setup import merge_report_block
    p,c,_=setup(monkeypatch,tmp_path);m=api();pdf=fitz.open()
    for text in ('ENFRA savings $125.', 'ENFRA savings $250.'):
        pdf.new_page().insert_text((40,80),text)
    c,_=sources.ingest(p,'omitted-retained.pdf',pdf.tobytes());pdf.close();c=reviewed(p,c)
    original,=sources.prepare_pages(p,(c,),((c.source.id,'mbcx_report'),))
    existing=(replace(original,source='Omit',text='Keep omitted manual note',asset_captions=('Keep omitted caption',))
              if populated else ResolvedBlock('mbcx_report','Omit'))
    before=(asdict(c),asdict(existing));blocks={existing.key:existing}
    args=dict(source_confirmed=False,visual_fingerprints=((2,m.page_review_fingerprint(c.source,2)),),financial_semantics=m.SEMANTICS)
    if populated:
        with pytest.raises(ValueError,match='deliberately left out'):
            # The same production outer merge is reached only on full success.
            revised,additions,replacements=m.include_reviewed_batch(p,c,(2,),blocks,**args)
            blocks.update(replacements)
            for key,incoming in additions.items():blocks[key]=merge_report_block(blocks.get(key),incoming,None,None)
        assert (asdict(c),asdict(blocks[existing.key]))==before
    else:
        revised,additions,replacements=m.include_reviewed_batch(p,c,(2,),blocks,**args)
        assert additions['mbcx_report'].asset_hashes and not replacements
        assert (asdict(c),asdict(existing))==before


@pytest.mark.parametrize('change',['source','profile','period','block','editor','replay','section_omitted','section_changed'])
def test_pending_batch_rejects_stale_report_and_replay_without_mutation(monkeypatch,tmp_path,change):
    from app.monthly_report_model import ResolvedBlock
    p,c,_=setup(monkeypatch,tmp_path);m=api();period=ReportPeriod(2026,9)
    section=SectionSpec('mbcx','4','MBCx Reports',(BlockSpec('mbcx_report','pdf_pages'),))
    batch=m.stage_financial_batch(p,period,c,(1,),{},editor_scope='editor-a',sections=(section,),source_confirmed=True,
        visual_fingerprints=((1,m.page_review_fingerprint(c.source,1)),),financial_semantics=m.SEMANTICS)
    section=SectionSpec('mbcx','4','MBCx Reports',(BlockSpec('mbcx_report','pdf_pages'),))
    draft=ReportDraft(p,period,'Synthetic Editor',(section,),(),sources=(c.source,));blocks={};current=(c.source,)
    editor='editor-a';consumed=()
    if change=='source':current=(replace(c.source,captions=((1,'new caption'),)),)
    if change=='profile':draft=replace(draft,profile=replace(p,key='another'))
    if change=='period':draft=replace(draft,period=ReportPeriod(2026,10))
    if change=='section_omitted':draft=replace(draft,sections=(replace(section,included=False),))
    if change=='section_changed':draft=replace(draft,sections=(replace(section,title='Changed section title'),))
    if change=='block':blocks={'mbcx_report':ResolvedBlock('mbcx_report','This month',text='new human edit')}
    if change=='editor':editor='editor-b'
    if change=='replay':consumed=(batch.token,)
    before=(asdict(draft),{k:asdict(v) for k,v in blocks.items()},tuple(asdict(s) for s in current))
    with pytest.raises(ValueError):m.apply_financial_batch(draft,blocks,current,batch,editor_scope=editor,consumed=consumed)
    assert before==(asdict(draft),{k:asdict(v) for k,v in blocks.items()},tuple(asdict(s) for s in current))


def test_ui_mixed_batch_production_merge_failure_then_success_is_atomic(monkeypatch,tmp_path):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_setup
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    original_line="pdf=fitz.open();pdf.new_page().insert_text((40,80),'ENFRA commissioning savings: $125. Synthetic client report.')"
    two_pages=APP.replace(original_line,original_line+";pdf.new_page().insert_text((40,80),'ENFRA commissioning savings: $250. Synthetic client report.')")
    app=AppTest.from_string(two_pages).run();app.checkbox[0].check().run();app.checkbox[1].check().run()
    app.multiselect[0].select(1).run();app.checkbox[-1].check().run();app.button[0].click().run()
    old=app.session_state['blocks']['mbcx_report']
    before=(asdict(app.session_state['content']),asdict(old),tuple(app.session_state['consumed']))
    app.multiselect[0].set_value([1,2]).run();app.checkbox[-1].check().run()
    original_merge=monthly_report_setup.merge_report_block
    def reject(*args,**kwargs):raise ValueError('Synthetic production merge conflict')
    monkeypatch.setattr(monthly_report_setup,'merge_report_block',reject)
    app.button[0].click().run()
    assert not app.exception and any('production merge conflict' in e.value for e in app.error)
    assert before==(asdict(app.session_state['content']),asdict(app.session_state['blocks']['mbcx_report']),tuple(app.session_state['consumed']))
    monkeypatch.setattr(monthly_report_setup,'merge_report_block',original_merge)
    app.button[0].click().run()
    assert not app.exception
    updated=app.session_state['blocks']['mbcx_report']
    assert len(updated.asset_hashes)==2 and updated.asset_instances[0].key==old.asset_instances[0].key
    assert updated.asset_captions[0]==old.asset_captions[0]
    assert app.session_state['content'].source.selected_pages==(1,2)
    assert len(app.session_state['consumed'])==len(before[2])+1


@pytest.mark.parametrize('change',['month','editor'])
def test_visual_consent_does_not_replay_into_new_month_or_editor(monkeypatch,tmp_path,change):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    scoped_app=APP.replace('period=ReportPeriod(2026,9)',"period=ReportPeriod(2026,st.session_state.get('month',9))")
    scoped_app=scoped_app.replace("editor_scope='test-editor'","editor_scope=st.session_state.get('editor','test-editor')")
    app=AppTest.from_string(scoped_app).run();app.checkbox[0].check().run();app.checkbox[1].check().run()
    app.multiselect[0].select(1).run();app.checkbox[-1].check().run()
    assert not app.button[0].disabled
    app.session_state[change]=10 if change=='month' else 'new-editor'
    app.run()
    assert not app.exception and app.button[0].disabled and not app.checkbox[-1].value
    assert app.session_state['content'].source.financial_source_review is None
