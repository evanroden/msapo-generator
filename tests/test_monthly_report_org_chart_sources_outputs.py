from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile
import pytest
from PIL import Image
from app import monthly_report_org_chart_defaults as charts, monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import ReportSource, SectionSpec, BlockSpec, ResolvedBlock
from app.monthly_report_docx import assemble_docx
from app.monthly_report_preview import section_preview_docx
from test_monthly_report_org_chart_defaults import scopes, fresh, picture, with_chart, publish, chart

@pytest.mark.parametrize('revoked',[None,'selection','review','stale'])
def test_source_page_current_consent_is_required(scopes,revoked):
    a1,_,_,_=scopes
    source=ReportSource('a'*64,'synthetic-chart.pdf','b'*64,'.pdf',page_texts=('Synthetic reporting chart.',),selected_pages=(1,))
    source=replace(source,client_page_reviews=((1,page_fingerprint(source,1)),))
    b,a=picture('red');ref=f'{source.id}:1:{source.fingerprint}'
    b=replace(b,references=(ref,),asset_provenance=((b.asset_hashes[0],(ref,)),))
    b=approve_all_assets(refresh_asset_source_context(b,(source,)))
    if revoked=='selection':source=replace(source,selected_pages=())
    if revoked=='review':source=replace(source,client_page_reviews=())
    if revoked=='stale':source=replace(source,client_page_reviews=((1,'old'),))
    d=replace(with_chart(fresh(a1),b),sources=(source,))
    kwargs=dict(scope='contract',expected_revision=0,expected_fingerprint=b.fingerprint,confirmed=True)
    if revoked:
        with pytest.raises(library.LibraryError):charts.save_default(d,b,a,**kwargs)
        assert charts.load_defaults(a1.contract).revision==0
    else:
        assert charts.save_default(d,b,a,**kwargs).revision==1

@pytest.mark.parametrize('which',[0,2])
def test_saved_and_preview_word_contain_only_selected_contract_chart(scopes,which):
    a1,a2,b1,_=scopes
    publish(a1,'red');publish(b1,'blue')
    p=(a2,a2,b1)[which];assets={};d=charts.apply_defaults(fresh(p),assets)
    section=SectionSpec('organization','1','Organizational Chart',(BlockSpec('org_chart','image_page'),BlockSpec('contact_matrix','image_page')))
    d=replace(d,sections=(section,),blocks=(chart(d),ResolvedBlock('contact_matrix','This month',text='Synthetic contact note retained.')))
    library.save_snapshot(d,expected_revision=0,assets=tuple(assets.items()))
    d=library.load_snapshot(p.contract,p.key,d.period).draft
    for raw in (assemble_docx(d,acknowledged_fingerprint=d.fingerprint,asset_loader=assets.__getitem__),section_preview_docx(d,'organization',asset_loader=assets.__getitem__)):
        with ZipFile(BytesIO(raw)) as package:
            images=[package.read(n) for n in package.namelist() if n.startswith('word/media/')]
        colors=[]
        for value in images:
            with Image.open(BytesIO(value)) as im:colors.extend(zip(*[iter(im.convert('RGB').tobytes())]*3))
        expected=(255,0,0) if which==0 else (0,0,255)
        foreign=(0,0,255) if which==0 else (255,0,0)
        assert expected in colors and foreign not in colors

from tests.conftest import requires_libreoffice

@requires_libreoffice
@pytest.mark.parametrize('which',[0,2])
def test_pdf_contains_only_selected_contract_chart(scopes,which):
    import pymupdf
    from app.monthly_report_docx import generate_report
    a1,a2,b1,_=scopes;publish(a1,'red');publish(b1,'blue')
    p=a2 if which==0 else b1;assets={};d=charts.apply_defaults(fresh(p),assets)
    section=SectionSpec('organization','1','Organizational Chart',(BlockSpec('org_chart','image_page'),))
    d=replace(d,sections=(section,),blocks=(chart(d),))
    generated=generate_report(d,acknowledged_fingerprint=d.fingerprint,asset_loader=assets.__getitem__)
    assert generated.pdf,generated.pdf_error
    expected=bytes((255,0,0) if which==0 else (0,0,255));foreign=bytes((0,0,255) if which==0 else (255,0,0))
    selected=other=0
    with pymupdf.open(stream=generated.pdf,filetype='pdf') as pdf:
        for page in pdf:
            data=page.get_pixmap(alpha=False).samples
            pixels=[data[i:i+3] for i in range(0,len(data),3)]
            selected+=pixels.count(expected);other+=pixels.count(foreign)
    assert selected>0 and other==0
