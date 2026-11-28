"""An empty old picture page may end before a proved next-page section."""

from copy import deepcopy
from dataclasses import dataclass
from docx.oxml.ns import qn


_PLAIN = {
    qn("w:" + n)
    for n in (
        "p",
        "pPr",
        "r",
        "rPr",
        "t",
        "rFonts",
        "b",
        "bCs",
        "i",
        "iCs",
        "sz",
        "szCs",
        "color",
        "spacing",
        "jc",
        "ind",
        "outlineLvl",
        "tabs",
        "tab",
        "pageBreakBefore",
        "keepNext",
        "keepLines",
        "widowControl",
        "contextualSpacing",
        "noProof",
        "lang",
        "numPr",
        "numId",
    )
}
_FORBIDDEN = {
    qn("w:" + n)
    for n in (
        "fldSimple",
        "fldChar",
        "instrText",
        "hyperlink",
        "bookmarkStart",
        "bookmarkEnd",
        "ins",
        "del",
        "object",
        "sdt",
        "commentReference",
        "altChunk",
    )
}


def _section_properties(node):
    """Only body-level section properties define physical section flow."""
    if node.tag == qn("w:sectPr"):
        return node
    if node.tag == qn("w:p"):
        return node.find("./" + qn("w:pPr") + "/" + qn("w:sectPr"))
    return None


def _signature(n):
    return (
        n.tag,
        tuple(sorted(n.attrib.items())),
        (n.text or "") if n.tag == qn("w:t") else "",
        tuple(_signature(c) for c in n),
    )


def _plain(n, boundary=False):
    clone = deepcopy(n)
    if boundary:
        props = clone.find("./" + qn("w:pPr") + "/" + qn("w:sectPr"))
        if props is None:
            return False
        props.getparent().remove(props)
    return (
        clone.tag == qn("w:p")
        and all(x.tag in _PLAIN for x in clone.iter())
        and not any((x.text or "").strip() for x in clone.iter(qn("w:t")))
    )


def _picture_signature(n):
    if n.tag != qn("w:p") or any(x.tag in _FORBIDDEN for x in n.iter()):
        return None
    clone = deepcopy(n)
    drawings = list(clone.iter(qn("w:drawing")))
    if len(drawings) != 1:
        return None
    drawings[0].getparent().remove(drawings[0])
    # Line breaks are old caption structure, not page boundaries.
    for br in list(clone.iter(qn("w:br"))):
        if br.get(qn("w:type"), "textWrapping") != "textWrapping":
            return None
        br.getparent().remove(br)
    if any(x.tag not in _PLAIN for x in clone.iter()):
        return None
    return _signature(clone)


@dataclass(frozen=True)
class InteriorTail:
    nodes: tuple
    following: object
    boundary_xml: object
    next_section: object
    next_section_xml: object

    def apply(self, body, pages):
        if any(
            n.getparent() is not body
            or n in pages.live
            or n in pages.support
            or n in pages.headings
            for n in self.nodes
        ):
            return
        if any(a.getnext() is not b for a, b in zip(self.nodes, self.nodes[1:])):
            return
        if self.nodes[-1].getnext() is not self.following:
            return
        if not all(
            _plain(n, boundary=i == len(self.nodes) - 1)
            for i, n in enumerate(self.nodes)
        ):
            return
        next_props = next(
            (
                _section_properties(n)
                for n in self.nodes[-1].itersiblings()
                if _section_properties(n) is not None
            ),
            None,
        )
        if (
            next_props is not self.next_section
            or _signature(next_props) != self.next_section_xml
        ):
            return
        props = self.nodes[-1].find("./" + qn("w:pPr") + "/" + qn("w:sectPr"))
        if _signature(props) != self.boundary_xml:
            return
        pr = self.nodes[0].find(qn("w:pPr"))
        if pr is None:
            return
        for br in list(pr.findall(qn("w:pageBreakBefore"))):
            if br.get(qn("w:val"), "true").lower() not in {"0", "false", "off"}:
                pr.remove(br)


def interior_picture_tails(path, original, sections):
    from app.monthly_report_import import _package
    from app.monthly_report_xml_parser import parse_xml

    with _package(path) as z:
        raw = list(parse_xml(z.read("word/document.xml")).find(qn("w:body")))
    if len(raw) != len(original):
        return ()
    plans = []
    for i, node in enumerate(original):
        if sections.get(i + 1) != "subcontractors":
            continue
        signature = _picture_signature(raw[i])
        if signature is None or _picture_signature(node) != signature:
            continue
        br = raw[i].find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore"))
        if br is None or br.get(qn("w:val"), "true").lower() in {"0", "false", "off"}:
            continue
        for j in range(i + 1, len(raw)):
            if sections.get(j + 1) != "subcontractors":
                break
            boundary = raw[j].find("./" + qn("w:pPr") + "/" + qn("w:sectPr"))
            if boundary is not None:
                if not _plain(raw[j], True) or _signature(raw[j]) != _signature(
                    original[j]
                ):
                    break
                # The next section, not the ending section, owns transition type.
                next_props = next(
                    (
                        _section_properties(n)
                        for n in raw[j + 1 :]
                        if _section_properties(n) is not None
                    ),
                    None,
                )
                if next_props is None:
                    break
                typ = next_props.find(qn("w:type"))
                if typ is not None and typ.get(qn("w:val")) != "nextPage":
                    break
                next_index = next(
                    k
                    for k in range(j + 1, len(raw))
                    if _section_properties(raw[k]) is next_props
                )
                live_next = _section_properties(original[next_index])
                if live_next is None or _signature(live_next) != _signature(next_props):
                    break
                if j + 1 < len(original):
                    plans.append(
                        InteriorTail(
                            tuple(original[i : j + 1]),
                            original[j + 1],
                            _signature(boundary),
                            live_next,
                            _signature(next_props),
                        )
                    )
                break
            if not _plain(raw[j]) or _signature(raw[j]) != _signature(original[j]):
                break
    return tuple(plans)
