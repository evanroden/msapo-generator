"""Typed body paragraphs and bounded clearance for current native narratives."""
from copy import deepcopy
import math
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

_V = '{urn:schemas-microsoft-com:vml}'


def _outline(paragraph, styles):
    properties = paragraph.find(qn('w:pPr'))
    level = properties.find(qn('w:outlineLvl')) if properties is not None else None
    if level is not None:
        return level.get(qn('w:val')) not in (None, '9')
    link = properties.find(qn('w:pStyle')) if properties is not None else None
    visited = set()
    while link is not None:
        identity = link.get(qn('w:val'))
        if identity in visited or identity not in styles:
            break
        visited.add(identity)
        style = styles[identity]
        properties = style.find(qn('w:pPr'))
        level = properties.find(qn('w:outlineLvl')) if properties is not None else None
        if level is not None:
            return level.get(qn('w:val')) not in (None, '9')
        # A derived style need not have pPr of its own to inherit an outline.
        link = style.find(qn('w:basedOn'))
    return False


def narrative_prototype(element, styles, static_labels):
    """Borrow one body paragraph's formatting, never its enclosing text canvas.

    Only rewritten content reaches this helper. Proven unchanged text boxes,
    alternate representations and their geometry bypass it entirely.
    """
    from app.monthly_report_import import _text
    candidates = [p for p in element.iter(qn('w:p'))
                  if _text(p) and not list(p.iter(qn('w:txbxContent')))
                  and not _outline(p, styles)
                  and _text(p).strip().casefold() not in static_labels]
    if not candidates:
        return None
    # A canvas commonly begins with a label/site line and then its actual notes.
    # Prefer the substantive paragraph over that label, using no client names.
    original = max(candidates, key=lambda p: len(_text(p)))
    result = OxmlElement('w:p')
    properties = original.find(qn('w:pPr'))
    if properties is not None:
        properties = deepcopy(properties)
        for tag in ('sectPr', 'framePr'):
            for node in list(properties.findall(qn('w:' + tag))):
                properties.remove(node)
        result.append(properties)
    if original is not element:
        # The old canvas's numbered rows are not the new author's list. Explicit
        # bullets/numbers in current text remain; empty source rows never return.
        properties = result.get_or_add_pPr()
        numbering = properties.get_or_add_numPr()
        numbering.get_or_add_numId().val = 0
    run = OxmlElement('w:r')
    source_run = next((r for r in original.iter(qn('w:r')) if _text(r)), None)
    rpr = source_run.find(qn('w:rPr')) if source_run is not None else None
    if rpr is None and properties is not None:
        rpr = properties.find(qn('w:rPr'))
    if rpr is not None:
        run.append(deepcopy(rpr))
    text = OxmlElement('w:t'); run.append(text); result.append(run)
    return result


def write_narrative(anchor, prototype, value):
    """Replace this payload, retaining a source section boundary on its anchor."""
    boundary = anchor.find('./' + qn('w:pPr') + '/' + qn('w:sectPr'))
    boundary = deepcopy(boundary) if boundary is not None else None
    anchor[:] = [deepcopy(child) for child in prototype]
    if boundary is not None:
        anchor.get_or_add_pPr().append(boundary)
    if not value.strip():
        anchor.get_or_add_pPr().get_or_add_numPr().get_or_add_numId().val = 0
    text = next(anchor.iter(qn('w:t')), None)
    if text is None:
        run = OxmlElement('w:r'); text = OxmlElement('w:t')
        run.append(text); anchor.append(run)
    text.text = value; text.set(qn('xml:space'), 'preserve')


def header_parts(document, properties):
    for reference in properties.findall(qn('w:headerReference')):
        relationship = document.part.rels.get(reference.get(qn('r:id')))
        if relationship is not None and not relationship.is_external:
            part = relationship.target_part
            if hasattr(part, 'element'):
                yield part.element


def header_contains_label(document, properties, label):
    from app.monthly_report_import import _text
    expected = ' '.join(label.casefold().split())
    return any(expected in ' '.join(_text(part).casefold().split()) for part in header_parts(document, properties))


def _points(value):
    match = re.fullmatch(r'(-?\d+(?:\.\d+)?)(pt|in)', value.strip())
    return float(match[1]) * (72 if match[2] == 'in' else 1) if match else None


def reserve_running_header(document, properties):
    """Reserve only measured, page-anchored header content on rewritten pages.

    Source-replay/divider regions never call this. Paragraph-relative shapes,
    grouped coordinate spaces and full-page watermark/background canvases are
    not evidence of a running header and do not authorize a margin correction.
    """
    from app.monthly_report_import import _text
    margin = properties.find(qn('w:pgMar'))
    size = properties.find(qn('w:pgSz'))
    if margin is None or size is None:
        return
    try:
        top = int(margin.get(qn('w:top'), '1440')) / 20
        page_height = int(size.get(qn('w:h'), '15840')) / 20
    except (TypeError, ValueError):
        return
    if not 0 <= top < page_height:
        return
    bottoms = []
    for part in header_parts(document, properties):
        for anchor in part.iter(qn('wp:anchor')):
            position = anchor.find(qn('wp:positionV'))
            extent = anchor.find(qn('wp:extent'))
            offset = position.find(qn('wp:posOffset')) if position is not None else None
            hidden = any(node.get('hidden') in ('1', 'true', 'on')
                         for tag in ('wp:docPr', 'a:cNvPr') for node in anchor.iter(qn(tag)))
            if (hidden or position is None or position.get('relativeFrom') != 'page'
                    or offset is None or extent is None
                    or not (_text(anchor) or list(anchor.iter(qn('a:blip'))))):
                continue
            try:
                y = int(offset.text) / 12700
                height = int(extent.get('cy')) / 12700
                effect = anchor.find(qn('wp:effectExtent'))
                below = int(effect.get('b', '0')) / 12700 if effect is not None else 0
            except (TypeError, ValueError):
                continue
            if 0 <= y < y + height <= page_height / 4 and below >= 0:
                bottoms.append(y + height + below)
        for shape in part.iter(_V + 'shape'):
            if any(parent.tag == _V + 'group' for parent in shape.iterancestors()):
                continue
            style = dict(re.findall(r'([\w-]+)\s*:\s*([^;]+)', shape.get('style', '')))
            if (style.get('mso-position-vertical-relative') != 'page'
                    or style.get('visibility') == 'hidden'
                    or not (_text(shape) or list(shape.iter(_V + 'imagedata')))):
                continue
            y, height = _points(style.get('margin-top', '')), _points(style.get('height', ''))
            if y is not None and height is not None and 0 <= y < y + height <= page_height / 4:
                bottoms.append(y + height)
    if bottoms:
        corrected = max(top, max(bottoms) + 6)
        if corrected < page_height / 3:
            margin.set(qn('w:top'), str(math.ceil(corrected * 20)))
