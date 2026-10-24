"""Benign complex-script toggles must not erase ordinary narrative typography."""
from copy import deepcopy

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from lxml import etree
import pytest

from app.monthly_report_native_narrative_visibility import narrative_visibility_writer
from app.monthly_report_native_notes import plain_visible


def scene(marker, value=None, location='run'):
    document = Document()
    paragraph = document.add_paragraph('Synthetic ordinary body text.')
    paragraph.paragraph_format.left_indent = Pt(6)
    run = paragraph.runs[0]
    run.font.size = Pt(12)
    run.underline = True
    if location == 'run':
        props = run._r.get_or_add_rPr()
    elif location == 'mark':
        props = deepcopy(run._r.get_or_add_rPr())
        paragraph._p.get_or_add_pPr().append(props)
    else:
        props = document.styles['Normal'].element.get_or_add_rPr()
        size = OxmlElement('w:sz'); size.set(qn('w:val'), '24'); props.append(size)
        underline = OxmlElement('w:u'); underline.set(qn('w:val'), 'single'); props.append(underline)
    toggle = OxmlElement('w:' + marker)
    if value is not None:
        toggle.set(qn('w:val'), value)
    props.append(toggle)  # Imported writer ordering after size/underline.
    return document, paragraph, props, toggle


@pytest.mark.parametrize('marker', ['bCs', 'iCs'])
@pytest.mark.parametrize('value', [None, '1', 'true', 'on', '0', 'false', 'off'])
def test_unique_complex_script_toggle_preserves_exact_source_typography(marker, value):
    document, paragraph, _, _ = scene(marker, value)
    before = etree.tostring(paragraph._p)
    styles = etree.tostring(document.styles.element)
    # Rendering compatibility must not broaden permission to delete note text.
    assert not plain_visible(paragraph._p, document.styles.element)
    result = narrative_visibility_writer(document)(paragraph._p)
    assert result is paragraph._p
    assert etree.tostring(result) == before
    assert etree.tostring(document.styles.element) == styles
    assert paragraph.runs[0].underline is True
    assert paragraph.runs[0].font.size == Pt(12)


@pytest.mark.parametrize('marker', ['bCs', 'iCs'])
@pytest.mark.parametrize('location', ['mark', 'style'])
def test_complex_script_mark_or_style_does_not_reset_visible_typography(marker, location):
    document, paragraph, _, _ = scene(marker, location=location)
    before, styles = etree.tostring(paragraph._p), etree.tostring(document.styles.element)
    result = narrative_visibility_writer(document)(paragraph._p)
    assert result is paragraph._p
    assert etree.tostring(result) == before
    assert etree.tostring(document.styles.element) == styles


@pytest.mark.parametrize('marker', ['bCs', 'iCs'])
@pytest.mark.parametrize('invalid', ['duplicate', 'child', 'attribute', 'value', 'text', 'hidden', 'duplicate-selector'])
def test_complex_script_exception_does_not_authorize_ambiguous_or_hidden_input(marker, invalid):
    document, paragraph, props, toggle = scene(marker)
    if invalid == 'duplicate':
        props.append(deepcopy(toggle))
    elif invalid == 'child':
        toggle.append(OxmlElement('w:vanish'))
    elif invalid == 'attribute':
        toggle.set(qn('w:unexpected'), '1')
    elif invalid == 'value':
        toggle.set(qn('w:val'), 'invalid')
    elif invalid == 'text':
        toggle.text = 'Unexpected scalar text'
    elif invalid == 'hidden':
        paragraph.runs[0].font.hidden = True
    else:
        ppr = paragraph._p.get_or_add_pPr()
        for _ in range(2):
            selector = OxmlElement('w:pStyle'); selector.set(qn('w:val'), 'Normal'); ppr.insert(0, selector)
    before = etree.tostring(paragraph._p)
    result = narrative_visibility_writer(document)(paragraph._p)
    assert result is not paragraph._p
    assert result.find('./' + qn('w:pPr') + '/' + qn('w:pStyle')).get(qn('w:val')).startswith('ENFRACurrentVisibleNarrative')
    assert etree.tostring(paragraph._p) == before
