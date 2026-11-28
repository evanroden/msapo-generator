"""An unused utility block must not print a source-only Rate trend label."""
from dataclasses import dataclass

from docx.oxml.ns import qn

# No styles, fields, bookmarks, links, revisions or geometry-bearing content.
# This proof intentionally covers only directly formatted source paragraphs.
_PLAIN = {qn('w:' + name) for name in (
    'p', 'pPr', 'r', 'rPr', 't', 'rFonts', 'b', 'bCs', 'i', 'iCs',
    'color', 'sz', 'szCs', 'spacing', 'ind', 'jc', 'outlineLvl',
    'keepNext', 'keepLines', 'widowControl', 'contextualSpacing', 'noProof', 'lang',
)}


def _signature(node):
    return (node.tag, tuple(sorted(node.attrib.items())), (node.text or '') if node.tag == qn('w:t') else '',
            tuple(_signature(child) for child in node))


def _label(node):
    if (node.tag != qn('w:p') or any(n.tag not in _PLAIN for n in node.iter())
            or ''.join(n.text or '' for n in node.iter(qn('w:t'))).strip().casefold() != 'rate trend'):
        return False
    if any(n.tag not in (qn('w:pPr'), qn('w:r')) for n in node):
        return False
    properties = node.findall(qn('w:pPr'))
    if len(properties) > 1 or (properties and node[0] is not properties[0]):
        return False
    for parent in node.iter():
        if parent.tag in (qn('w:pPr'), qn('w:rPr')):
            tags = [n.tag for n in parent]
            if len(tags) != len(set(tags)) or any(tag in (qn('w:p'), qn('w:r'), qn('w:t')) for tag in tags):
                return False
            if any(len(n) and n.tag != qn('w:rPr') for n in parent):
                return False
        elif parent.tag == qn('w:r'):
            if any(n.tag not in (qn('w:rPr'), qn('w:t')) for n in parent):
                return False
            props = parent.findall(qn('w:rPr'))
            if len(props) > 1 or (props and parent[0] is not props[0]):
                return False
        elif parent.tag == qn('w:t') and len(parent):
            return False
    return True


@dataclass(frozen=True)
class UnusedRateLabel:
    node: object
    signature: tuple

    def apply(self, body, pages):
        node = self.node
        if (node.getparent() is not body or node in pages.live
                or node in pages.support or node in pages.headings
                or _signature(node) != self.signature or not _label(node)):
            return
        # Keep the complete paragraph, formatting and neighboring geometry.
        for text in node.iter(qn('w:t')):
            text.text = ''


def unused_rate_labels(path, draft, original, sections, unchanged):
    """Freeze exact raw-source proof before redaction or field normalization."""
    utility = [block for block in draft.blocks if block.key == 'utility_analysis']
    if len(utility) > 1 or any(block.source != 'Omit' and any((
            block.text.strip(), block.rows, block.extra_tables, block.asset_hashes,
            block.asset_instances, block.org_nodes)) for block in utility):
        return ()
    from app.monthly_report_import import _package
    from app.monthly_report_xml_parser import parse_xml
    with _package(path) as archive:
        raw = list(parse_xml(archive.read('word/document.xml')).find(qn('w:body')))
    if len(raw) != len(original):
        return ()
    return tuple(UnusedRateLabel(node, _signature(node))
                 for position, (source, node) in enumerate(zip(raw, original), 1)
                 if sections.get(position) == 'scorecards' and position not in unchanged
                 and _label(source) and _signature(source) == _signature(node))
