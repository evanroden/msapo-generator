"""Report-owned omissions and renumbering on proved native body occurrences.

No original, saved design, header or footer part is edited. Native text runs
retain formatting; only section-number spans in proved headings/contents change.
"""
import re
from copy import deepcopy
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from app.monthly_report_model import included_sections


def _leaf_paragraphs(root):
    return [p for p in root.iter(qn('w:p')) if not any(True for _ in p.iterdescendants(qn('w:p')))]


def _replace_span(paragraph, start, end, value):
    offset = 0
    for node in paragraph.iter(qn('w:t')):
        text = node.text or ''
        left, right = max(start, offset), min(end, offset + len(text))
        if left < right:
            node.text = text[:left-offset] + (value if left == start else '') + text[right-offset:]
        offset += len(text)


def apply_native_section_choices(document, draft, original, headings, section_by_pos, page_plan):
    if not draft.omitted_sections:
        return
    omitted = set(draft.omitted_sections)
    body = document.element.body
    included = {s.key:s for s in included_sections(draft.sections)}
    # Freeze each original physical region's current closing properties before
    # removing a logical section. A shared physical region keeps its exact
    # chrome even when its last logical section is omitted.
    def source_owner(node):
        region = page_plan.owner.get(node)
        return page_plan.source_word_sections[region] if region is not None else None
    properties = {}
    for node in body:
        boundary = node if node.tag == qn('w:sectPr') else node.find('.//' + qn('w:sectPr'))
        if boundary is not None and hasattr(page_plan, "source_word_sections"):
            properties[source_owner(node)] = deepcopy(boundary)
    # Each emitted node inherits its origin's logical section. Physical Word
    # sections can span more than one logical section and are not an authority.
    for node in list(body):
        if node.tag != qn('w:sectPr') and page_plan.logical_owner.get(node) in omitted:
            body.remove(node)
    # A divider can have both Choice and Fallback paragraphs. Change every
    # proved copy, never an arbitrary numeral inside report prose or a table.
    for position in headings:
        node = original[position-1]
        key = section_by_pos[position]
        section = included.get(key)
        if section is None or node.getparent() is not body:
            continue
        for paragraph in _leaf_paragraphs(node):
            text = ''.join(t.text or '' for t in paragraph.iter(qn('w:t')))
            match = re.fullmatch(r'\s*(\d+)\s*', text)
            if match is None:
                match = re.match(r'\s*(?:Section\s+)?(\d+)(?=\s*[.:\-\u2013\u2014]|\s+[A-Z])', text, re.I)
            if match:
                _replace_span(paragraph, *match.span(1), section.number)
    # Recognize contents entries only in the inspected cover/contents range,
    # require their section title to be independently recognized, and never
    # infer identity from an old ordinal alone.
    from app.monthly_report_import import _heading
    for position,node in enumerate(original,1):
        if section_by_pos.get(position) != 'cover' or node.getparent() is not body:
            continue
        for paragraph in _leaf_paragraphs(node):
            text = ''.join(t.text or '' for t in paragraph.iter(qn('w:t')))
            match = re.match(r'\s*Section\s+(\d+)\s*:\s*(.+)', text, re.I)
            if not match:
                continue
            key = _heading(match.group(2))
            if key not in {s.key for s in draft.sections}:
                raise ValueError('A native contents entry has no proved report section; numbering was not changed.')
            if key in omitted:
                paragraph.getparent().remove(paragraph)
            elif key in included:
                _replace_span(paragraph, *match.span(1), included[key].number)

    # Rebuild only the remaining source-owned boundaries. This avoids empty
    # pages for removed sections and prevents a removed final section's page
    # geometry from being applied to the remaining last section.
    if properties and hasattr(page_plan, 'source_word_sections'):
        groups = []
        for node in list(body):
            if node.tag == qn('w:sectPr'):
                body.remove(node)
                continue
            owner = source_owner(node)
            for boundary in list(node.iter(qn('w:sectPr'))):
                boundary.getparent().remove(boundary)
            if not groups or groups[-1][0] != owner:
                groups.append((owner, []))
            groups[-1][1].append(node)
        for index,(owner,nodes) in enumerate(groups):
            if owner not in properties:
                raise ValueError('A remaining native section has no proved page geometry.')
            boundary = deepcopy(properties[owner])
            if index == len(groups)-1:
                body.append(boundary)
                page_plan.owner[boundary] = page_plan.owner[nodes[-1]]
                page_plan.logical_owner[boundary] = page_plan.logical_owner.get(nodes[-1])
            else:
                last = nodes[-1]
                if last.tag != qn('w:p'):
                    last = OxmlElement('w:p'); nodes[-1].addnext(last)
                    page_plan.assigned(last,nodes[-1])
                props = last.find(qn('w:pPr'))
                if props is None:
                    props = OxmlElement('w:pPr'); last.insert(0,props)
                props.append(boundary)
