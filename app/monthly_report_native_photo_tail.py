"""Retire only a proved unused Activity photo-label page break."""
from copy import deepcopy
from dataclasses import dataclass
from docx.oxml.ns import qn
from app.monthly_report_native_interior_tail import (
    _signature, _plain, _picture_signature, _section_properties,
)

_TITLE = 'improvement highlights and pics'


def _label_signature(node):
    if node.tag != qn('w:p'):
        return None
    clone = deepcopy(node)
    if not ''.join(n.text or '' for n in clone.iter(qn('w:t'))).strip():
        return None
    for text in clone.iter(qn('w:t')):
        text.text = ''
    if not _plain(clone):
        return None
    if (any(n.tag not in (qn('w:pPr'), qn('w:r')) for n in node)
            or len(node.findall(qn('w:pPr'))) > 1):
        return None
    for parent in node.iter():
        if parent.tag in (qn('w:pPr'), qn('w:rPr')):
            tags = [n.tag for n in parent]
            if len(tags) != len(set(tags)):
                return None
            if any(n.tag in (qn('w:p'), qn('w:r'), qn('w:t')) for n in parent):
                return None
            if any(len(n) and n.tag != qn('w:rPr') for n in parent):
                return None
        elif parent.tag == qn('w:r'):
            if any(n.tag not in (qn('w:rPr'), qn('w:t')) for n in parent):
                return None
            if len(parent.findall(qn('w:rPr'))) > 1:
                return None
        elif parent.tag == qn('w:t') and len(parent):
            return None
    return _signature(node)


def _normalized_label(node):
    clone = deepcopy(node)
    # The builder suppresses Word's inherited numbering on static labels.
    pr = clone.find(qn('w:pPr'))
    if pr is not None:
        numbering = pr.findall(qn('w:numPr'))
        if len(numbering) > 1:
            return None
        for num in numbering:
            if (len(num) == 1 and num[0].tag == qn('w:numId')
                    and dict(num[0].attrib) == {qn('w:val'): '0'}
                    and not num.attrib and not len(num[0])):
                pr.remove(num)
    return _signature(clone) if _plain(clone) else None


@dataclass(frozen=True)
class EmptyPhotoTail:
    label: object
    label_signature: tuple
    picture: object
    picture_signature: tuple
    boundary: object
    boundary_signature: tuple
    following: object
    next_section: object
    next_signature: tuple

    def apply(self, body, pages, cleared):
        if self.label not in cleared:
            return
        nodes = (self.label, self.picture, self.boundary)
        if any(n.getparent() is not body or n in pages.live or n in pages.support
               or n in pages.headings for n in nodes):
            return
        if (self.label.getnext() is not self.picture
                or self.picture.getnext() is not self.boundary
                or self.boundary.getnext() is not self.following
                or _normalized_label(self.label) != self.label_signature
                or not _plain(self.picture)
                or _signature(self.picture) != self.picture_signature
                or not _plain(self.boundary, boundary=True)
                or _signature(self.boundary) != self.boundary_signature):
            return
        next_props = next((_section_properties(n) for n in self.boundary.itersiblings()
                           if _section_properties(n) is not None), None)
        if next_props is not self.next_section or _signature(next_props) != self.next_signature:
            return
        pr = self.label.find(qn('w:pPr'))
        if pr is not None:
            for br in list(pr.findall(qn('w:pageBreakBefore'))):
                if br.get(qn('w:val'), 'true').lower() not in {'0', 'false', 'off'}:
                    pr.remove(br)


def empty_photo_tails(path, draft, original, sections, unchanged):
    improvements = [b for b in draft.blocks if b.key == 'improvements']
    if len(improvements) > 1 or any(b.source != 'Omit' and any((b.text.strip(), b.rows,
            b.extra_tables, b.asset_hashes, b.asset_instances, b.org_nodes)) for b in improvements):
        return ()
    from app.monthly_report_import import _package
    from app.monthly_report_xml_parser import parse_xml
    with _package(path) as archive:
        raw = list(parse_xml(archive.read('word/document.xml')).find(qn('w:body')))
    if len(raw) != len(original):
        return ()
    plans = []
    for i in range(1, len(raw) - 3):
        title = deepcopy(raw[i-1])
        # This untouched preceding heading establishes context only. Its style
        # never supplies permission to change the following direct break.
        for style in list(title.iter(qn('w:pStyle'))):
            style.getparent().remove(style)
        for marker in list(title.iter(qn('w:lastRenderedPageBreak'))):
            marker.getparent().remove(marker)
        if (''.join(n.text or '' for n in title.iter(qn('w:t'))).strip().casefold() != _TITLE
                or _label_signature(title) is None):
            continue
        if any(sections.get(j + 1) != 'activity' or j + 1 in unchanged for j in range(i, i + 3)):
            continue
        label, picture, boundary = raw[i:i + 3]
        label_sig = _label_signature(label)
        # Raw source numbering is not a licence for normalization-based proof.
        if label_sig is None or label.find('.//' + qn('w:numPr')) is not None:
            continue
        br = label.find('./' + qn('w:pPr') + '/' + qn('w:pageBreakBefore'))
        picture_sig = _picture_signature(picture)
        if (br is None or br.get(qn('w:val'), 'true').lower() in {'0', 'false', 'off'}
                or picture_sig is None or not _plain(boundary, boundary=True)
                or _signature(label) != _signature(original[i])
                or picture_sig != _picture_signature(original[i+1])
                or _signature(boundary) != _signature(original[i+2])):
            continue
        next_index = next((j for j in range(i + 3, len(raw))
                           if _section_properties(raw[j]) is not None), None)
        if next_index is None:
            continue
        props = _section_properties(raw[next_index])
        typ = props.find(qn('w:type'))
        if typ is not None and typ.get(qn('w:val')) != 'nextPage':
            continue
        live = _section_properties(original[next_index])
        if live is None or _signature(live) != _signature(props):
            continue
        cleared_label = deepcopy(label)
        from app.monthly_report_native_layout import _set_text
        _set_text(cleared_label, '')
        plans.append(EmptyPhotoTail(original[i], _signature(cleared_label), original[i+1], picture_sig,
            original[i+2], _signature(boundary), original[i+3], live, _signature(props)))
    return tuple(plans)
