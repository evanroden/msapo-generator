"""Bounded reflow of replaced content; unchanged source pages are not a template.

A Word section is the geometry boundary, not necessarily one page. Only pages
whose old payload was entirely replaced can lose their old empty scaffolding.
Native dividers and independently proved current source payloads are protected.
"""
from copy import deepcopy
from dataclasses import dataclass

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph


@dataclass(frozen=True)
class PageRegion:
    properties: object
    original_properties: object
    protected: bool
    split: bool = False


def _boundary(element):
    return element if element.tag == qn('w:sectPr') else element.find('.//' + qn('w:sectPr'))


def _effective(properties, inherited):
    result = deepcopy(properties)
    present = {(n.tag, n.get(qn('w:type'), 'default')) for n in result
               if n.tag in (qn('w:headerReference'), qn('w:footerReference'))}
    for key, node in inherited.items():
        if key not in present:
            result.insert(0, deepcopy(node))
    for node in result:
        if node.tag in (qn('w:headerReference'), qn('w:footerReference')):
            inherited[(node.tag, node.get(qn('w:type'), 'default'))] = deepcopy(node)
    return result


class NativePages:
    """Keep emission accounting beside the original physical section geometry."""

    def __init__(self, body, original, section_by_pos, headings, unchanged_positions, *, fresh=False):
        from app.monthly_report_import import _is_native_divider_background, _text
        self.body, self.fresh = body, fresh
        self.owner, self.live, self.kinds, self.regions = {}, set(), {}, []
        self.support = set()
        self.headings = {original[p - 1] for p in headings}
        divider_sections = {section_by_pos.get(p) for p in headings
                            if _is_native_divider_background(original[p - 1], _text(original[p - 1]))}
        self.redundant_headings = {original[p - 1] for p in headings
                                  if section_by_pos.get(p) in divider_sections
                                  and not _is_native_divider_background(original[p - 1], _text(original[p - 1]))}
        inherited, start = {}, 0
        for end, element in enumerate(original):
            properties = _boundary(element)
            if properties is None:
                continue
            original_properties = deepcopy(properties)
            properties = _effective(properties, inherited)
            indices = list(range(start, end + 1))
            unchanged = any(i + 1 in unchanged_positions for i in indices)
            cover = any(section_by_pos.get(i + 1) == 'cover' for i in indices)
            art_positions = [i for i in indices if _is_native_divider_background(original[i], _text(original[i]))]
            cuts = art_positions + [i for i in indices if i > start and i + 1 in headings
                                    and section_by_pos.get(i + 1) != section_by_pos.get(i)]
            # Splitting source art is forbidden when any adjacent payload is
            # being replayed at its source position. Fresh content is different.
            boundaries = sorted(set([start, end + 1] + ([] if unchanged or cover else cuts)))
            for left, right in zip(boundaries, boundaries[1:]):
                nodes = original[left:right]
                logical = {section_by_pos.get(i + 1) for i in range(left, right) if original[i].tag != qn('w:sectPr')}
                divider = any(i in art_positions for i in range(left, right))
                region = len(self.regions)
                self.regions.append(PageRegion(properties, original_properties, unchanged or cover or divider or len(logical) > 1,
                                               split=len(boundaries) > 2))
                for node in nodes:
                    self.owner[node] = region
            start = end + 1

    def _root(self, element):
        while element is not None and element.getparent() is not self.body:
            element = element.getparent()
        return element

    def emitted(self, element, origin=None, *, kind='text'):
        root = self._root(element)
        source = self._root(origin) if origin is not None else root
        if root is None:
            return
        if root not in self.owner and source in self.owner:
            self.owner[root] = self.owner[source]
        self.live.add(root)
        self.kinds[root] = kind

    def assigned(self, element, origin):
        root, source = self._root(element), self._root(origin)
        if root is not None and source in self.owner:
            self.owner[root] = self.owner[source]

    def technical_picture(self, document, origin, raw, *, new_page=False, caption=False):
        """New chart/evidence pages contain all pixels, never a photo's crop."""
        from app.monthly_report_docx import _fit_picture
        root = self._root(origin)
        region = self.owner.get(root)
        properties = self.regions[region].properties if region is not None else document.sections[-1]._sectPr
        size = properties.find(qn('w:pgSz'))
        margin = properties.find(qn('w:pgMar'))
        def value(node, key, default):
            return int(node.get(qn('w:' + key), str(default))) if node is not None else default
        width = value(size, 'w', 12240) - value(margin, 'left', 720) - value(margin, 'right', 720)
        top, bottom = value(margin, 'top', 720), value(margin, 'bottom', 720)
        clearance = max(0, value(margin, 'header', 0) + 280 - top)
        height = value(size, 'h', 15840) - top - max(bottom, value(margin, 'footer', 0) + 200) - clearance - 60
        if caption:
            height -= 480
        if min(width, height) <= 0:
            raise ValueError('The native page has no usable picture area. Check the master page margins.')
        element = OxmlElement('w:p')
        paragraph = Paragraph(element, document._body)
        paragraph.paragraph_format.alignment = 1
        paragraph.paragraph_format.space_before = Pt(clearance / 20)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1
        paragraph.paragraph_format.page_break_before = new_page
        _fit_picture(paragraph.add_run(), raw, width / 1440, height / 1440)
        return element

    def finish(self, *, document=None):
        """Remove obsolete scaffolding only with positive replacement evidence."""
        from app.monthly_report_import import _text
        contents = [[] for _ in self.regions]
        for node in self.body:
            if node.tag == qn('w:sectPr'):
                continue
            region = self.owner.get(node)
            if region is None:
                # Unknown insertion must not be silently discarded or relocated.
                return
            contents[region].append(node)
        output, changed = [], False
        for region, nodes in zip(self.regions, contents):
            if not nodes:
                continue
            rewrite = not region.protected and (self.fresh or any(node in self.live for node in nodes))
            if rewrite:
                current = any(node in self.live for node in nodes)
                kept = [node for node in nodes if node in self.live or (node in self.headings and (current or node not in self.redundant_headings))
                        or (current and node in self.support)]
                changed = True
                for node in kept:
                    for properties in list(node.iter(qn('w:sectPr'))):
                        properties.getparent().remove(properties)
                    if self.kinds.get(node) != 'picture':
                        # These breaks/spacing belonged to the discarded payload,
                        # not the new text. Picture page breaks are authored here.
                        for br in list(node.iter(qn('w:br'))):
                            if br.get(qn('w:type')) in ('page', 'column'):
                                br.getparent().remove(br)
                        if node.tag == qn('w:p'):
                            properties = node.get_or_add_pPr()
                            for tag in ('pageBreakBefore', 'keepNext', 'spacing'):
                                for item in list(properties.findall(qn('w:' + tag))):
                                    properties.remove(item)
                            spacing = OxmlElement('w:spacing')
                            spacing.set(qn('w:before'), '0'); spacing.set(qn('w:after'), '80')
                            properties.append(spacing)
                nodes = kept
            if nodes:
                output.append((region, nodes, rewrite))
        if not changed or not output:
            return
        for node in list(self.body):
            self.body.remove(node)
        inherited = {}
        for index, (region, nodes, rewrite) in enumerate(output):
            terminal = index == len(output) - 1
            properties = deepcopy(region.original_properties)
            present = {(n.tag, n.get(qn('w:type'), 'default')) for n in properties}
            for node in region.properties:
                if node.tag not in (qn('w:headerReference'), qn('w:footerReference')):
                    continue
                key = (node.tag, node.get(qn('w:type'), 'default'))
                if key not in present and inherited.get(key) != node.get(qn('r:id')):
                    properties.insert(0, deepcopy(node))
                inherited[key] = node.get(qn('r:id'))
            if document is not None and rewrite and any(self.kinds.get(node) == 'text' for node in nodes):
                from app.monthly_report_native_text import reserve_running_header
                reserve_running_header(document, properties)
            # At an artificial split, the retained divider still starts a page.
            if region.split:
                kind = properties.find(qn('w:type'))
                if kind is not None:
                    kind.set(qn('w:val'), 'nextPage')
            boundaries = [boundary for node in nodes if (boundary := _boundary(node)) is not None]
            if rewrite or terminal:
                for boundary in boundaries:
                    boundary.getparent().remove(boundary)
            for node in nodes:
                self.body.append(node)
            if terminal:
                self.body.append(properties)
            elif not rewrite and boundaries:
                # Only newly adjacent inherited chrome needs materializing.
                actual = boundaries[-1]
                present = {(n.tag, n.get(qn('w:type'), 'default')) for n in actual}
                for node in properties:
                    key = (node.tag, node.get(qn('w:type'), 'default'))
                    if node.tag in (qn('w:headerReference'), qn('w:footerReference')) and key not in present:
                        actual.insert(0, deepcopy(node))
            else:
                paragraph = OxmlElement('w:p'); ppr = OxmlElement('w:pPr')
                spacing = OxmlElement('w:spacing')
                for key, value in {'before':'0', 'after':'0', 'line':'20', 'lineRule':'exact'}.items():
                    spacing.set(qn('w:' + key), value)
                ppr.append(spacing); ppr.append(properties); paragraph.append(ppr)
                self.body.append(paragraph)
