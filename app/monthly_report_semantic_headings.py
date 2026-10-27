"""Add Word navigation semantics to proved native section headings only.

Direct OOXML outline metadata leaves the branded paragraph style, font, layout,
page breaks and text untouched. Never infer headings from a raster image,
floating textbox, contents entry or arbitrary bold prose.
"""
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_import import _heading


def _plain_heading_text(paragraph):
    """Accept only plain body runs; text in drawings is not a Word heading."""
    if paragraph.tag != qn("w:p"):
        return ""
    runs = []
    for child in paragraph:
        if child.tag == qn("w:pPr"):
            continue
        if child.tag != qn("w:r"):
            return ""
        for member in child:
            if member.tag == qn("w:rPr"):
                continue
            if member.tag != qn("w:t"):
                return ""
            runs.append(member.text or "")
    return "".join(runs).strip()


def _has_semantic_level(paragraph, styles):
    """Respect an existing direct level or heading style, even when inherited."""
    properties = paragraph.find(qn("w:pPr"))
    if properties is None:
        return False
    if properties.find(qn("w:outlineLvl")) is not None:
        return True
    style = properties.find(qn("w:pStyle"))
    if style is None:
        return False
    style_id = style.get(qn("w:val"), "")
    if re.fullmatch(r"Heading\s*[1-9]", style_id, re.IGNORECASE):
        return True
    seen = set()
    while style_id and style_id not in seen:
        seen.add(style_id)
        defined = styles.get(style_id)
        if defined is None:
            break
        props = defined.find(qn("w:pPr"))
        if props is not None and props.find(qn("w:outlineLvl")) is not None:
            return True
        parent = defined.find(qn("w:basedOn"))
        style_id = parent.get(qn("w:val"), "") if parent is not None else ""
    return False


def mark_native_section_headings(document, original, positions, section_by_pos, included):
    """Mark one surviving, plain heading per included section, without styling.

    Source section detection supplies the positions and section identity.
    Reflow may discard a source node; only actual live body children qualify.
    If the source already has a semantic heading for that section, retain it
    rather than creating a second navigation entry. Ambiguous artwork cannot
    be promoted to editable Word text.
    """
    included = set(included)
    body = document.element.body
    styles = {
        item.get(qn("w:styleId")): item
        for item in document.styles.element.findall(qn("w:style"))
        if item.get(qn("w:styleId"))
    }
    candidates = {}
    for position in sorted(positions):
        if type(position) is not int or not 1 <= position <= len(original):
            continue
        key = section_by_pos.get(position)
        if key not in included:
            continue
        paragraph = original[position - 1]
        if paragraph.getparent() is not body:
            continue
        title = _plain_heading_text(paragraph)
        if not title or _heading(title) != key:
            continue
        candidates.setdefault(key, []).append(paragraph)

    marked = []
    for key, paragraphs in candidates.items():
        if any(_has_semantic_level(paragraph, styles) for paragraph in paragraphs):
            continue
        # A branded divider often precedes a separate editable section
        # heading. Only the last surviving *plain* paragraph is marked.
        target = paragraphs[-1]
        properties = target.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        properties.insert_element_before(
            outline, "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")
        marked.append(key)
    return tuple(marked)
