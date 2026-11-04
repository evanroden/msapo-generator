import pytest
from copy import deepcopy
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from lxml import etree
from PIL import Image

from app.monthly_report_divider_monochrome import monochrome_divider_photos, R, A, MC


def jpeg():
    stream = BytesIO(); Image.new('RGB', (1200, 800), (200, 40, 10)).save(stream, 'JPEG')
    return stream.getvalue()


def picture(document, data, width=8, height=8):
    paragraph = document.add_paragraph()
    inline = paragraph.add_run().add_picture(BytesIO(data), width=Inches(width), height=Inches(height))._inline
    inline.tag = qn('wp:anchor')
    return paragraph._p, next(inline.iter(A + 'blip'))


def pixel(document, blip):
    rel = document.part.rels[blip.get(R + 'embed')]
    with Image.open(BytesIO(rel.target_part.blob)) as image:
        return image.convert('RGB').getpixel((10, 10))


def test_only_selected_divider_occurrence_is_gray_even_when_source_is_shared():
    document = Document(); raw = jpeg()
    root, selected = picture(document, raw)
    _, elsewhere = picture(document, raw)
    _, small = picture(document, raw, width=2, height=2)
    assert selected.get(R + 'embed') == elsewhere.get(R + 'embed')
    monochrome_divider_photos(document, [root])
    assert len(set(pixel(document, selected))) == 1
    assert len(set(pixel(document, elsewhere))) > 1
    assert len(set(pixel(document, small))) > 1
    assert document.part.rels[elsewhere.get(R + 'embed')].target_part.blob == raw


def test_ambiguous_alternate_content_is_not_modified():
    document = Document(); root, selected = picture(document, jpeg())
    drawing = selected.getparent().getparent().getparent().getparent().getparent()
    # Wrap the drawing itself in a choice so both renderings remain untouched.
    parent = drawing.getparent(); parent.remove(drawing)
    alternate = etree.SubElement(parent, MC + 'AlternateContent')
    choice = etree.SubElement(alternate, MC + 'Choice'); choice.append(drawing)
    fallback = etree.SubElement(alternate, MC + 'Fallback'); fallback.append(deepcopy(drawing))
    old = selected.get(R + 'embed')
    monochrome_divider_photos(document, [root])
    assert selected.get(R + 'embed') == old
    assert len(set(pixel(document, selected))) > 1


def test_imported_native_divider_render_is_gray_and_original_is_retained(tmp_path):
    from app.monthly_report_import import inspect_docx, imported_draft
    from app.monthly_report_model import synthetic_profiles, ReportPeriod
    from app.monthly_report_native_layout import build_native_docx
    from app.monthly_report_start_import import build_starting_import
    from test_monthly_report_native_design_import import mint_report, plans

    source = mint_report(tmp_path)
    document = Document(source)
    selected = next(document.element.iter(A + 'blip'))
    rid, _ = document.part.get_or_add_image(BytesIO(jpeg()))
    selected.set(R + 'embed', rid)
    document.save(source)
    before = source.read_bytes()
    inspection = inspect_docx(source)
    mapped, _ = build_starting_import(source, inspection, plans(inspection).values())
    draft = imported_draft(synthetic_profiles()[0], ReportPeriod(2026, 10), 'Current Editor', mapped)
    output = Document(BytesIO(build_native_docx(draft, source, asset_loader=dict(mapped.assets).__getitem__)))
    selected_output = next(output.element.iter(A + 'blip'))
    assert len(set(pixel(output, selected_output))) == 1
    assert source.read_bytes() == before


def test_obvious_flattened_brand_bands_are_not_desaturated():
    document = Document()
    image = Image.new('RGB', (1200, 800), (214, 239, 75))
    from PIL import ImageDraw
    ImageDraw.Draw(image).rectangle((0, 400, 1199, 799), fill=(84, 126, 126))
    stream = BytesIO(); image.save(stream, 'JPEG', quality=95)
    root, selected = picture(document, stream.getvalue())
    old = selected.get(R + 'embed')
    monochrome_divider_photos(document, [root])
    assert selected.get(R + 'embed') == old


@pytest.mark.parametrize('fallback_gray', [True, False])
def test_alternate_choice_changes_only_with_an_already_gray_fallback(fallback_gray):
    from docx.oxml import OxmlElement
    document=Document();root,selected=picture(document,jpeg())
    drawing=selected.getparent().getparent().getparent().getparent().getparent()
    parent=drawing.getparent();parent.remove(drawing)
    alternate=etree.SubElement(parent,MC+'AlternateContent')
    choice=etree.SubElement(alternate,MC+'Choice');choice.append(drawing)
    fallback=etree.SubElement(alternate,MC+'Fallback')
    pict=OxmlElement('w:pict');fallback.append(pict)
    shape=etree.SubElement(pict,'{urn:schemas-microsoft-com:vml}shape')
    image=etree.SubElement(shape,'{urn:schemas-microsoft-com:vml}imagedata')
    out=BytesIO();Image.new('RGB',(1200,800),(90,90,90) if fallback_gray else (180,20,10)).save(out,'PNG')
    fallback_rid,_=document.part.get_or_add_image(BytesIO(out.getvalue()));image.set(qn('r:id'),fallback_rid)
    old=selected.get(R+'embed');monochrome_divider_photos(document,[root])
    assert image.get(qn('r:id'))==fallback_rid
    assert (selected.get(R+'embed')!=old) == fallback_gray
    assert (len(set(pixel(document,selected)))==1) == fallback_gray


def test_gray_fallback_screen_checks_every_pixel():
    from app.monthly_report_divider_monochrome import _has_already_gray_fallback
    document=Document();root,selected=picture(document,jpeg())
    drawing=selected.getparent().getparent().getparent().getparent().getparent(); anchor=next(root.iter(qn('wp:anchor')))
    parent=drawing.getparent();parent.remove(drawing)
    alternate=etree.SubElement(parent,MC+'AlternateContent');choice=etree.SubElement(alternate,MC+'Choice');choice.append(drawing)
    fallback=etree.SubElement(alternate,MC+'Fallback');pict=etree.SubElement(fallback,qn('w:pict'))
    shape=etree.SubElement(pict,'{urn:schemas-microsoft-com:vml}shape');image=etree.SubElement(shape,'{urn:schemas-microsoft-com:vml}imagedata')
    pixels=Image.new('RGB',(1200,800),(90,90,90));pixels.putpixel((1,1),(255,0,0));out=BytesIO();pixels.save(out,'PNG')
    rid,_=document.part.get_or_add_image(BytesIO(out.getvalue()));image.set(qn('r:id'),rid)
    assert not _has_already_gray_fallback(document,anchor,alternate)


def test_edit_layer_is_updated_only_when_it_matches_selected_photo():
    d=Document();root,selected=picture(d,jpeg())
    layer=etree.SubElement(selected,'{http://schemas.microsoft.com/office/drawing/2010/main}imgLayer')
    layer.set(R+'embed',selected.get(R+'embed'))
    monochrome_divider_photos(d,[root])
    assert layer.get(R+'embed') == selected.get(R+'embed')
    assert len(set(pixel(d,selected)))==1


def test_different_edit_layer_causes_safe_skip():
    d=Document();root,selected=picture(d,jpeg()); old=selected.get(R+'embed')
    other=BytesIO();Image.new('RGB',(1200,800),'green').save(other,'JPEG');rid,_=d.part.get_or_add_image(BytesIO(other.getvalue()))
    layer=etree.SubElement(selected,'{http://schemas.microsoft.com/office/drawing/2010/main}imgLayer');layer.set(R+'embed',rid)
    monochrome_divider_photos(d,[root])
    assert selected.get(R+'embed')==old and layer.get(R+'embed')==rid


def test_grayscale_native_photo_in_compatibility_source_view(tmp_path,monkeypatch):
    from dataclasses import replace
    from app.monthly_report_compatibility_view import derive_compatibility_view
    from app.monthly_report_native_art_scope import expected_header_scope, verify_header_routing
    from app.monthly_report_model import Facility,ReportPeriod,synthetic_profiles
    from app.monthly_report_native_layout import build_native_docx
    from test_monthly_report_source_frame_logo_role import source
    from test_monthly_report_native_art_lifecycle import save_sample
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'store'))
    path=source(tmp_path,divergent=True); document=Document(path)
    fixture_document=Document()
    divider,fixture_blip=picture(fixture_document,jpeg())
    # Synthetic palette/geometry marks this independent picture as a divider.
    photo_anchor=next(divider.iter(qn('wp:anchor')))
    for axis in ('H','V'):
        pos=OxmlElement('wp:position'+axis);pos.set('relativeFrom','page')
        offset=OxmlElement('wp:posOffset');offset.text='0';pos.append(offset);photo_anchor.insert(0,pos)
    synthetic_band=OxmlElement('w:r');drawing=OxmlElement('w:drawing');synthetic_band.append(drawing)
    for color in ('D6EF4B','547E7E'):
        fill=OxmlElement('a:solidFill');color_node=OxmlElement('a:srgbClr');color_node.set('val',color);fill.append(color_node);drawing.append(fill)
    divider.append(synthetic_band)
    divider=deepcopy(divider)
    title=OxmlElement('w:r');text=OxmlElement('w:t');text.text='MONTHLY SCORECARDS';title.append(text);divider.insert(0,title)
    rid,_=document.part.get_or_add_image(BytesIO(jpeg()));next(divider.iter(A+'blip')).set(R+'embed',rid)
    document.element.body.insert(len(document.element.body)-1,divider);document.add_paragraph('Synthetic utility note');document.save(path)
    before=path.read_bytes();view=derive_compatibility_view(before)
    profile=replace(synthetic_profiles()[0],imported_from=view.original_inspection.sha256,title='Synthetic Regional Community Health Hospital',facilities=(Facility('synthetic','Synthetic Regional Community Health Hospital'),))
    draft,loader=save_sample((path,view,profile,ReportPeriod(2026,9),None,None))
    output=build_native_docx(draft,path,asset_loader=loader,source_view=view,section_key='scorecards')
    verify_header_routing(output,expected_header_scope(view,'scorecards'))
    result=Document(BytesIO(output));matching=[]
    for blip in result.element.iter(A+'blip'):
        rel=result.part.rels.get(blip.get(R+'embed'))
        if rel and not rel.is_external:
            try:
                with Image.open(BytesIO(rel.target_part.blob)) as decoded:
                    if decoded.size==(1200,800): matching.append(decoded.convert('RGB').getpixel((10,10)))
            except OSError: pass
    assert matching and all(len(set(p))==1 for p in matching)
    assert path.read_bytes()==before
