"""Identical saved cover reuse never certifies unknown source artwork."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
import pytest
from app.monthly_report_import import ImportItem, DocxInspection
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_sections import ImportSection
from app.monthly_report_start_import import reuse_identical_saved_cover


def fixture(tmp_path, monkeypatch):
    source=tmp_path/'synthetic.docx';source.write_bytes(b'synthetic source bytes')
    digest=sha256(source.read_bytes()).hexdigest()
    photo=ImportItem('photo','image','word/document.xml',1,1,section='cover',suggested_slot='cover_photo',image_part='word/media/photo.jpg',image_width=1000,image_height=700)
    logo=ImportItem('logo','image','word/document.xml',2,1,section='cover',suggested_slot='client_logo',image_part='word/media/logo.png',image_width=200,image_height=80,image_role='client_logo')
    footer=ImportItem('footer','text','word/document.xml',3,1,section='cover',suggested_slot='footer_text',text='Synthetic footer')
    header=ImportItem('unknown','image','word/header1.xml',1,1,section='cover',image_part='word/media/unknown.png',image_width=200,image_height=200,image_role='header_artwork')
    section=ImportSection('cover','Cover',(photo,logo,footer,header));inspection=DocxInspection(digest,section.items,(),(),1)
    data={'photo':SimpleNamespace(data=b'photo',extension='jpg'),'logo':SimpleNamespace(data=b'logo',extension='png'),'body-unknown':SimpleNamespace(data=b'unclassified',extension='png')}
    import app.monthly_report_import as mod
    monkeypatch.setattr(mod,'read_import_image',lambda path,item,**kw:data[item.id])
    blocks={'cover_photo':ResolvedBlock('cover_photo','This month',asset_hashes=(sha256(b'photo').hexdigest()+'.jpg',)),
            'client_logo':ResolvedBlock('client_logo','This month',asset_hashes=(sha256(b'logo').hexdigest()+'.png',)),
            'footer_text':ResolvedBlock('footer_text','This month',text='Synthetic footer')}
    plan={'automatic':True,'omit':False,'source_sha256':digest,'source_site_relation':'same','selected':['photo','logo','footer'],'destinations':{'photo':'cover_photo','logo':'client_logo','footer':'footer_text'},'texts':{'footer':'Synthetic footer'},'questions':('Other cover artwork has no confirmed photograph or logo role.',),'approved':False}
    return source,section,inspection,blocks,plan


def test_identical_cover_reuses_existing_without_mutating_source_or_old_choices(tmp_path, monkeypatch):
    source,section,inspection,blocks,plan=fixture(tmp_path,monkeypatch);before=source.read_bytes();saved=deepcopy(plan);old=deepcopy(blocks)
    result=reuse_identical_saved_cover(plan,section,inspection,source,blocks)
    assert result['omit'] and result['approved'] and not result['selected'] and not result['questions']
    assert plan==saved and blocks==old and source.read_bytes()==before


@pytest.mark.parametrize('change',['photo','logo','footer','omitted','foreign','changed_source','extra_question','unclassified_body','unsupported','not_automatic','source_view','missing'])
def test_uncertain_or_changed_cover_keeps_existing_review(tmp_path, monkeypatch, change):
    source,section,inspection,blocks,plan=fixture(tmp_path,monkeypatch);view=None
    if change=='photo':blocks['cover_photo']=replace(blocks['cover_photo'],asset_hashes=('different.jpg',))
    if change=='logo':blocks['client_logo']=replace(blocks['client_logo'],asset_hashes=('different.png',))
    if change=='footer':blocks['footer_text']=replace(blocks['footer_text'],text='Another footer')
    if change=='omitted':blocks['cover_photo']=replace(blocks['cover_photo'],source='Omit')
    if change=='foreign':plan['source_site_relation']='other'
    if change=='changed_source':source.write_bytes(b'changed source')
    if change=='extra_question':plan['questions']+=('Another review required',)
    if change=='unclassified_body':
        extra=ImportItem('body-unknown','image','word/document.xml',4,1,section='cover',image_part='word/media/unknown.png',image_width=200,image_height=200)
        section=replace(section,items=section.items+(extra,))
    if change=='unsupported':section=replace(section,items=section.items+(ImportItem('unread','unsupported','word/document.xml',4,1,section='cover'),))
    if change=='not_automatic':plan['automatic']=False
    if change=='source_view':view=object()
    if change=='missing':blocks.pop('client_logo')
    assert reuse_identical_saved_cover(plan,section,inspection,source,blocks,source_view=view)==plan


def test_extra_body_image_is_only_ignored_if_exact_current_logo(tmp_path, monkeypatch):
    source,section,inspection,blocks,plan=fixture(tmp_path,monkeypatch)
    extra=ImportItem('extra-logo','image','word/document.xml',4,1,section='cover',image_part='word/media/extra.png',image_width=497,image_height=80)
    section=replace(section,items=section.items+(extra,))
    import app.monthly_report_import as mod
    old=mod.read_import_image
    monkeypatch.setattr(mod,'read_import_image',lambda path,item,**kw: SimpleNamespace(data=b'logo',extension='png') if item.id=='extra-logo' else old(path,item,**kw))
    assert reuse_identical_saved_cover(plan,section,inspection,source,blocks)['omit']
    blocks['client_logo']=replace(blocks['client_logo'],asset_hashes=('different.png',))
    assert reuse_identical_saved_cover(plan,section,inspection,source,blocks)==plan


def test_auto_reuse_does_not_force_cover_review_but_manual_omit_stays_reachable():
    from app.monthly_report_section_ui import _starting_review_sections
    section=ImportSection('cover','Cover',())
    automatic={'cover':{'approved':True,'questions':(),'omit':True,'automatic_identical_cover_reuse':True}}
    manual={'cover':{'approved':True,'questions':(),'omit':True}}
    assert _starting_review_sections((section,),automatic,{})==()
    assert _starting_review_sections((section,),manual,{})==(section,)


def test_real_synthetic_docx_auto_plan_reuses_matching_cover(tmp_path):
    from io import BytesIO
    from docx import Document
    from docx.shared import Inches
    from PIL import Image
    from app.monthly_report_import import inspect_docx, read_import_image
    from app.monthly_report_model import Facility,ReportProfile,ReportPeriod
    from app.monthly_report_sections import section_reviews
    from app.monthly_report_start_import import analyze_starting_report,automatic_section_plans
    d=Document();photo=BytesIO();Image.new('RGB',(600,400),(20,80,140)).save(photo,'PNG')
    d.add_picture(BytesIO(photo.getvalue()),width=Inches(5))
    header=BytesIO();Image.new('RGB',(200,200),(235,245,255)).save(header,'PNG')
    d.sections[0].header.paragraphs[0].add_run().add_picture(BytesIO(header.getvalue()),width=Inches(1))
    p=tmp_path/'invented-cover.docx';d.save(p);original=p.read_bytes()
    inspection=inspect_docx(p);site=Facility('site','Synthetic Site');profile=ReportProfile('Test','site','Synthetic Site',(site,));period=ReportPeriod(2026,10)
    analysis=analyze_starting_report(inspection,profile,period,confirmed_sites=(site,))
    section=next(s for s in section_reviews(inspection) if s.key=='cover')
    plan=automatic_section_plans(inspection,analysis,profile=profile,period=period)['cover']
    assert not plan['approved'] and plan['questions']
    item=next(i for i in section.items if i.id in plan['selected'] and plan['destinations'].get(i.id)=='cover_photo')
    image=read_import_image(p,item,line_art=False,preserve_transparency=False)
    reference=sha256(image.data).hexdigest()+'.'+image.extension
    existing={'cover_photo':ResolvedBlock('cover_photo','This month',asset_hashes=(reference,))}
    result=reuse_identical_saved_cover(plan,section,inspection,p,existing)
    assert result['approved'] and result['omit'] and result['automatic_identical_cover_reuse']
    assert p.read_bytes()==original


@pytest.mark.parametrize("action", ("continue", "restore"))
def test_actual_reentry_auto_reuses_identical_cover_and_offers_restore(monkeypatch,tmp_path,action):
    from io import BytesIO
    from docx import Document
    from docx.shared import Inches
    from PIL import Image
    from app import monthly_report_library as library
    from app.monthly_report_import import inspect_docx,read_import_image
    from app.monthly_report_sections import section_reviews
    from app.monthly_report_start_import import cover_photo_candidates
    from app.monthly_report_model import synthetic_profiles
    from test_monthly_report_cover_art_recovery import existing_app,continue_button
    d=Document();d.add_heading(synthetic_profiles()[0].facilities[0].title,0);d.add_paragraph('September 2026')
    data=BytesIO();Image.new('RGB',(600,400),'purple').save(data,'PNG');d.add_picture(BytesIO(data.getvalue()),width=Inches(5))
    h=BytesIO();Image.new('RGB',(200,200),'blue').save(h,'PNG');d.sections[0].header.paragraphs[0].add_run().add_picture(BytesIO(h.getvalue()),width=Inches(1))
    d.add_heading('Monthly Activity Summary',1);d.add_paragraph('Synthetic service completed.')
    d.add_heading('Sub-Contractor Status',1)
    table=d.add_table(rows=2,cols=3)
    for index,value in enumerate(('Discipline','Synthetic Site','MSA')):table.cell(0,index).text=value
    for index,value in enumerate(('Synthetic trade','Synthetic vendor','Active')):table.cell(1,index).text=value
    source=tmp_path/'invented-existing-cover.docx';d.save(source);raw=source.read_bytes()
    app,working,saved,_,assets=existing_app(monkeypatch,tmp_path,source)
    inspection=inspect_docx(source);section=next(s for s in section_reviews(inspection) if s.key=='cover');item=cover_photo_candidates(section.items)[0]
    normalized=read_import_image(source,item,line_art=False,preserve_transparency=False);ref=library.asset_reference(normalized.data,normalized.extension);assets[ref]=normalized.data
    blocks=tuple(replace(b,asset_hashes=(ref,)) if b.key=='cover_photo' else b for b in working.blocks)
    working=replace(working,blocks=blocks);app.session_state['working']=working;app.session_state['assets']=assets
    for k in list(app.session_state.filtered_state):
        if k.endswith(('_analysis_signature','_section_plans')):del app.session_state[k]
    app.run()
    assert not app.exception
    state=next(v for k,v in app.session_state.filtered_state.items() if k.endswith('_section_plans'))
    assert state['cover'].get('automatic_identical_cover_reuse')
    from app.monthly_report_start_import import build_starting_import
    mapped,_=build_starting_import(source,inspection,tuple(state.values()),profile=working.profile,period=working.period)
    vendor=next(block for block in mapped.blocks if block.key=='subcontractor_matrix')
    assert any('Active' in row for table in vendor.extra_tables for row in table.rows)
    assert any(b.label=='Review uploaded cover instead' for b in app.button)
    assert not any('no confirmed photograph or logo role' in x.value for x in app.error)
    if action=='continue':
        assert not continue_button(app).disabled
        continue_button(app).click().run()
        assert not app.exception and not app.error
        imported=library.load_imported_draft(working.profile.contract,working.profile.key)
        vendor=next(block for block in imported.blocks if block.key=='subcontractor_matrix')
        assert any('Active' in row for table in vendor.extra_tables for row in table.rows)
        assert next(block for block in imported.blocks if block.key=='cover_photo').asset_hashes==(ref,)
        assert library.imported_original(working.profile.contract,working.profile.key).read_bytes()==raw
        return
    next(b for b in app.button if b.label=='Review uploaded cover instead').click().run()
    state=next(v for k,v in app.session_state.filtered_state.items() if k.endswith('_section_plans'))
    assert not state['cover'].get('automatic_identical_cover_reuse') and not state['cover']['approved']
    assert source.read_bytes()==raw and library.load_profile(working.profile.contract,working.profile.key)==saved
