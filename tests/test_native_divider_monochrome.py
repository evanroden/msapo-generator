from copy import deepcopy
from io import BytesIO

from docx import Document
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
