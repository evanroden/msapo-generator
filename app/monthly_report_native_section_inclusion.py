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
    # A chart/contact split inserts a page-break-only paragraph after native
    # reflow. It is a derivative node, not in the original region accounting.
    # Attribute ONLY that exact separator to the next proven organization
    # node; never guess ownership for content or unrelated page boundaries.
    def region_owner(node):
        region = page_plan.owner.get(node)
        if region is not None:
            return region
        if node.tag != qn('w:p') or len(node) != 1:
            return None
        ppr = node.find(qn('w:pPr'))
        next_node = node.getnext()
        if (ppr is None or len(ppr) != 1 or ppr[0].tag != qn('w:pageBreakBefore')
                or next_node is None or page_plan.logical_owner.get(next_node) != 'organization'):
            return None
        region = page_plan.owner.get(next_node)
        if region is not None:
            page_plan.owner[node] = region
            page_plan.logical_owner[node] = 'organization'
        return region

    def effective_properties(region, boundary):
        # The raw closing sectPr may inherit its header/footer from an
        # omitted earlier section. Preserve the proved effective references
        # for this exact physical region, without changing other properties.
        result = deepcopy(boundary)
        keys = {(ref.tag, ref.get(qn('w:type'), 'default')) for ref in result
                if ref.tag in (qn('w:headerReference'), qn('w:footerReference'))}
        for ref in page_plan.regions[region].properties:
            key = (ref.tag, ref.get(qn('w:type'), 'default'))
            if ref.tag in (qn('w:headerReference'), qn('w:footerReference')) and key not in keys:
                result.insert(0, deepcopy(ref))
                keys.add(key)
        return result

    # Reflow can split one source Word section into several independently
    # paginated regions. Preserve each region's boundary rather than merging
    # merely because its source_word_sections number happens to match.
    properties = {}
    proven_boundaries = set()
    if hasattr(page_plan, 'source_word_sections') and hasattr(page_plan, 'regions'):
        properties = {region: deepcopy(item.properties)
                      for region, item in enumerate(page_plan.regions)}
        for node in body:
            boundary = node if node.tag == qn('w:sectPr') else node.find('.//' + qn('w:sectPr'))
            if boundary is not None:
                region = region_owner(node)
                if region is not None:
                    proven_boundaries.add(region)
                    properties[region] = effective_properties(region, boundary)
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

    # Rebuild the remaining *region*-owned boundaries. Both original Word
    # boundaries and independently proved reflow splits must survive; only
    # boundaries whose logical content was removed may disappear.
    if properties and hasattr(page_plan, 'source_word_sections'):
        groups = []
        previous_region = None
        for node in list(body):
            if node.tag == qn('w:sectPr'):
                body.remove(node)
                continue
            owner = region_owner(node)
            for boundary in list(node.iter(qn('w:sectPr'))):
                boundary.getparent().remove(boundary)
            # Distinct source Word sections always have distinct geometry.
            # For multiple logical regions within the SAME source section,
            # split only at a boundary actually emitted by the current
            # derivative. Constructor-only reflow candidates do not justify
            # inventing a new blank page in otherwise protected source text.
            if (not groups or (owner != previous_region and
                    (page_plan.source_word_sections[previous_region]
                     != page_plan.source_word_sections[owner]
                     or previous_region in proven_boundaries))):
                groups.append([owner, []])
            else:
                groups[-1][0] = owner
            groups[-1][1].append(node)
            previous_region = owner
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
