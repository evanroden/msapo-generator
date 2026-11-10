from io import BytesIO
from copy import deepcopy
import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from lxml import etree
from PIL import Image
from app.monthly_report_scorecard_seam import fill_scorecard_seam, MARKER

WPS='{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}'
A='{http://schemas.openxmlformats.org/drawingml/2006/main}'


def anchor(drawing, y, *, behind, width, height):
    node=drawing.find(qn('wp:inline'));node.tag=qn('wp:anchor')
    for k,v in {'distT':'0','distB':'0','distL':'0','distR':'0','simplePos':'0','relativeHeight':'50','behindDoc':str(int(behind)),'locked':'0','layoutInCell':'1','allowOverlap':'1'}.items():node.set(k,v)
    size=node.find(qn('wp:extent'));size.set('cx',str(width));size.set('cy',str(height))
    for axis,value in (('H',0),('V',y)):
        pos=OxmlElement('wp:position'+axis);pos.set('relativeFrom','page')
        off=OxmlElement('wp:posOffset');off.text=str(value);pos.append(off);node.insert(0,pos)
    return node


def fixture():
    d=Document();p=d.add_paragraph();p.paragraph_format.space_after=Inches(0)
    raw=BytesIO();Image.new('RGB',(850,770),(150,150,150)).save(raw,'PNG')
    pic=p.add_run().add_picture(BytesIO(raw.getvalue()),width=Inches(8.5),height=Inches(7.7))._inline
    photo=anchor(pic.getparent(),0,behind=False,width=7772400,height=7040880)
    # Minimal synthetic Word shape containing both brand colors, positioned at
    # the lower band. No client image or actual report content is embedded.
    drawing=OxmlElement('w:drawing');inline=OxmlElement('wp:inline');drawing.append(inline)
    extent=OxmlElement('wp:extent');extent.set('cx','7772400');extent.set('cy','2142490');inline.append(extent)
    docpr=OxmlElement('wp:docPr');docpr.set('id','99');docpr.set('name','Synthetic band');inline.append(docpr)
    graphic=OxmlElement('a:graphic');data=OxmlElement('a:graphicData');data.set('uri',WPS[1:-1]);graphic.append(data);inline.append(graphic)
    shape=etree.SubElement(data,WPS+'wsp');props=etree.SubElement(shape,WPS+'spPr')
    geom=etree.SubElement(props,A+'prstGeom',prst='rect');etree.SubElement(geom,A+'avLst')
    fill=etree.SubElement(props,A+'solidFill');etree.SubElement(fill,A+'srgbClr',val='547E7E')
    line=etree.SubElement(props,A+'ln');linefill=etree.SubElement(line,A+'solidFill');etree.SubElement(linefill,A+'srgbClr',val='D5EE4A')
    etree.SubElement(shape,WPS+'bodyPr')
    p.add_run()._r.append(drawing)
    band=anchor(drawing,7905750,behind=True,width=7772400,height=2142490)
    return d,p._p,photo,band


def test_only_proved_divider_receives_one_underlay_and_source_is_intact():
    d,root,photo,band=fixture(); before=deepcopy(root)
    assert fill_scorecard_seam(d,root)
    assert sum(n.get('descr')==MARKER for n in root.iter(qn('wp:docPr'))) == 1
    assert photo.get('behindDoc')=='0' and band.get('behindDoc')=='1'
    assert not fill_scorecard_seam(d,root)
    assert len(list(before.iter(qn('a:blip'))))==1


@pytest.mark.parametrize('mutation', ['no_photo','two_photos','no_band','wrong_position','detached'])
def test_ambiguous_artwork_is_left_unchanged(mutation):
    d,root,photo,band=fixture()
    if mutation=='no_photo': photo.getparent().remove(photo)
    if mutation=='two_photos': photo.getparent().append(deepcopy(photo))
    if mutation=='no_band': band.getparent().remove(band)
    if mutation=='wrong_position': band.find(qn('wp:positionV')).find(qn('wp:posOffset')).text='100'
    if mutation=='detached': root.getparent().remove(root)
    before=etree.tostring(root)
    assert not fill_scorecard_seam(d,root)
    assert etree.tostring(root)==before


def test_physical_pdf_gap_is_filled_without_losing_photo(tmp_path,monkeypatch):
    import pymupdf as fitz
    from conftest import libreoffice_can_convert
    from app import pdf_converter
    if not libreoffice_can_convert(): pytest.skip('LibreOffice writer/calc unavailable')
    d,root,photo,band=fixture()
    before=tmp_path/'before.docx';d.save(before)
    assert fill_scorecard_seam(d,root)
    after=tmp_path/'after.docx';d.save(after)
    monkeypatch.setattr(pdf_converter,'OUTPUT_DIR',tmp_path)
    def pixel(path,coord):
        with fitz.open(pdf_converter.convert_to_pdf(path)) as pdf:
            page=pdf[0]; pix=page.get_pixmap(alpha=False)
            return Image.frombytes('RGB',(pix.width,pix.height),pix.samples).getpixel(coord)
    assert min(pixel(before,(500,590))) > 240
    r,g,b=pixel(after,(500,590));assert abs(r-84)<8 and abs(g-126)<8 and abs(b-126)<8
    r,g,b=pixel(after,(500,300));assert max(r,g,b)-min(r,g,b)<5 and 130<r<170


def test_native_scorecard_build_applies_underlay_only_to_scorecard(tmp_path):
    from app.monthly_report_model import Facility,ReportDraft,ReportPeriod,ReportProfile,ResolvedBlock,default_sections
    from app.monthly_report_native_layout import build_native_docx
    d,root,_,_=fixture()
    title=OxmlElement('w:r');text=OxmlElement('w:t');text.text='MONTHLY SCORECARDS';title.append(text);root.insert(0,title)
    d.add_paragraph('previous utility data')
    source=tmp_path/'source.docx';d.save(source);before=source.read_bytes()
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),))
    draft=ReportDraft(profile,ReportPeriod(2026,10),'Tester',default_sections(),(ResolvedBlock('utility_analysis','This month',text='Synthetic note'),),synthetic=True)
    result=Document(BytesIO(build_native_docx(draft,source,section_key='scorecards',master=True)))
    assert sum(x.get('descr')==MARKER for x in result.element.iter(qn('wp:docPr')))==1
    assert source.read_bytes()==before


def test_native_other_divider_is_not_recolored(tmp_path):
    from app.monthly_report_model import Facility,ReportDraft,ReportPeriod,ReportProfile,ResolvedBlock,default_sections
    from app.monthly_report_native_layout import build_native_docx
    d,root,_,_=fixture()
    title=OxmlElement('w:r');text=OxmlElement('w:t');text.text='MAINTENANCE SCHEDULE';title.append(text);root.insert(0,title)
    d.add_paragraph('previous maintenance data')
    d.add_table(rows=2,cols=5)
    source=tmp_path/'other.docx';d.save(source)
    profile=ReportProfile('Synthetic','north','North',(Facility('north','North'),))
    draft=ReportDraft(profile,ReportPeriod(2026,10),'Tester',default_sections(),(ResolvedBlock('service_calls','This month',rows=(('1','2026-10-01','Plant','Checked','T1'),)),),synthetic=True)
    result=Document(BytesIO(build_native_docx(draft,source,section_key='maintenance',master=True)))
    assert not any(x.get('descr')==MARKER for x in result.element.iter(qn('wp:docPr')))


def test_compatibility_source_view_with_scorecard_underlay(tmp_path,monkeypatch):
    from dataclasses import replace
    from app.monthly_report_compatibility_view import derive_compatibility_view
    from app.monthly_report_native_art_scope import expected_header_scope, verify_header_routing
    from app.monthly_report_model import Facility,ReportPeriod,synthetic_profiles
    from app.monthly_report_native_layout import build_native_docx
    from test_monthly_report_source_frame_logo_role import source
    from test_monthly_report_native_art_lifecycle import save_sample
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'store'))
    path=source(tmp_path,divergent=True)
    document=Document(path);_,divider,_,_=fixture();divider=deepcopy(divider)
    title=OxmlElement('w:r');text=OxmlElement('w:t');text.text='MONTHLY SCORECARDS';title.append(text);divider.insert(0,title)
    img=BytesIO();Image.new('RGB',(850,770),(150,150,150)).save(img,'PNG')
    rid,_=document.part.get_or_add_image(BytesIO(img.getvalue()))
    next(divider.iter(qn('a:blip'))).set(qn('r:embed'),rid)
    document.element.body.insert(len(document.element.body)-1,divider)
    document.add_paragraph('Synthetic utility note')
    document.save(path);view=derive_compatibility_view(path.read_bytes())
    profile=replace(synthetic_profiles()[0],imported_from=view.original_inspection.sha256,
        title='Synthetic Regional Community Health Hospital',facilities=(Facility('synthetic','Synthetic Regional Community Health Hospital'),))
    draft,loader=save_sample((path,view,profile,ReportPeriod(2026,9),None,None))
    output=build_native_docx(draft,path,asset_loader=loader,source_view=view,section_key='scorecards')
    verify_header_routing(output,expected_header_scope(view,'scorecards'))
    result=Document(BytesIO(output))
    assert any(x.get('descr')==MARKER for x in result.element.iter(qn('wp:docPr')))
