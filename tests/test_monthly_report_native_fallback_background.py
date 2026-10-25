"""Neutral fallback must override inherited dark backgrounds, not hide prose."""
from dataclasses import replace

from docx import Document
from docx.oxml.ns import qn
from lxml import etree
import pytest

from app.monthly_report_native_narrative_visibility import narrative_visibility_writer
from test_monthly_report_native_note_preservation import scene, render, NOTE

TEXT = 'Current synthetic prose must remain visible.'
VARIANTS = ['document-highlight', 'character-highlight', 'document-run-shading',
            'character-run-shading', 'document-paragraph-shading']


def background(styles, variant):
    defaults = styles.find(qn('w:docDefaults'))
    if variant.startswith('character'):
        style = next(s for s in styles.findall(qn('w:style'))
                     if s.get(qn('w:type')) == 'character' and s.get(qn('w:default')) == '1')
        props = style.find(qn('w:rPr'))
        if props is None: props = etree.SubElement(style, qn('w:rPr'))
    elif variant == 'document-paragraph-shading':
        container = defaults.find(qn('w:pPrDefault'))
        props = container.find(qn('w:pPr'))
        if props is None: props = etree.SubElement(container, qn('w:pPr'))
    else:
        props = defaults.find('./' + qn('w:rPrDefault') + '/' + qn('w:rPr'))
    if variant.endswith('highlight'):
        etree.SubElement(props, qn('w:highlight'), {qn('w:val'): 'black'})
    else:
        etree.SubElement(props, qn('w:shd'), {qn('w:val'): 'clear', qn('w:fill'): '000000'})
    run_defaults = defaults.find('./' + qn('w:rPrDefault') + '/' + qn('w:rPr'))
    color = run_defaults.find(qn('w:color'))
    if color is None: color = etree.SubElement(run_defaults, qn('w:color'))
    color.set(qn('w:val'), 'FFFFFF')


def make_document(variant):
    doc = Document()
    background(doc.styles.element, variant)
    original = doc.add_paragraph('Previously readable white text on black.')
    untouched = etree.tostring(original._p, method="c14n", exclusive=True)
    result = narrative_visibility_writer(doc)(original._p)
    assert result is not original._p
    result.find('.//' + qn('w:t')).text = TEXT
    original._p.addnext(result)
    assert etree.tostring(original._p, method="c14n", exclusive=True) == untouched
    return doc, result


@pytest.mark.parametrize('variant', VARIANTS)
def test_fallback_explicitly_overrides_all_inherited_backgrounds(variant):
    doc, paragraph = make_document(variant)
    props = paragraph.find('./' + qn('w:r') + '/' + qn('w:rPr'))
    assert props.find(qn('w:highlight')).get(qn('w:val')) == 'none'
    for parent in [props, paragraph.find(qn('w:pPr'))]:
        shade = parent.find(qn('w:shd'))
        assert shade is not None and shade.get(qn('w:fill')) == 'FFFFFF'
        assert shade.get(qn('w:val')) == 'clear'


def assert_black_text_on_light_background(pdf, text):
    import pymupdf
    with pymupdf.open(pdf) as document:
        matches = [(page, rect) for page in document for rect in page.search_for(text)]
        assert len(matches) == 1
        page, rect = matches[0]
        pixels = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=rect, colorspace=pymupdf.csRGB, alpha=False)
        rgb = list(zip(*[iter(pixels.samples)] * 3))
        white = sum(min(pixel) > 220 for pixel in rgb) / len(rgb)
        black = sum(max(pixel) < 50 for pixel in rgb) / len(rgb)
        # pdftotext alone would pass even for black ink on a solid black box.
        assert white > 0.60, f'Fallback background is not light: white={white:.3f}, black={black:.3f}'
        assert 0.005 < black < 0.35, f'Expected readable dark glyphs: white={white:.3f}, black={black:.3f}'


@pytest.mark.parametrize('variant', VARIANTS)
def test_required_actual_pdf_fallback_has_visible_contrast(tmp_path, monkeypatch, variant):
    from conftest import libreoffice_can_convert
    from app import pdf_converter
    assert libreoffice_can_convert(), 'Required actual-PDF contrast gate needs LibreOffice.'
    doc, _ = make_document(variant)
    output = tmp_path / 'synthetic-background.docx'; doc.save(output)
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    assert_black_text_on_light_background(pdf_converter.convert_to_pdf(output), TEXT)


@pytest.mark.parametrize('variant', ['document-highlight', 'document-run-shading', 'document-paragraph-shading'])
def test_required_native_rewrite_pdf_clears_dark_inherited_background(tmp_path, monkeypatch, variant):
    from conftest import libreoffice_can_convert
    from app import pdf_converter
    assert libreoffice_can_convert(), 'Required actual-PDF contrast gate needs LibreOffice.'
    def mutation(parts, kind):
        styles = etree.fromstring(parts['word/styles.xml']); background(styles, variant)
        parts['word/styles.xml'] = etree.tostring(styles)
    path, block = scene(tmp_path, mutation=mutation)
    source_before = path.read_bytes()
    raw, _ = render(path, replace(block, text=TEXT + '\n' + NOTE))
    output = tmp_path / 'native-background.docx'; output.write_bytes(raw)
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    assert_black_text_on_light_background(pdf_converter.convert_to_pdf(output), TEXT)
    assert path.read_bytes() == source_before
