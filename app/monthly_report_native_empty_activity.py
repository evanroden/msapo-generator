"""Remove a proved empty Activity picture panel without reflowing its tables."""
from copy import deepcopy
from dataclasses import dataclass

from docx.oxml.ns import qn

from app.monthly_report_import import _text


_TITLE = "improvement highlights and pics"
_FORMATTING = {qn("w:" + name) for name in (
    "p", "pPr", "pStyle", "r", "rPr", "t", "rFonts", "b", "bCs", "i", "iCs",
    "color", "sz", "szCs", "spacing", "ind", "outlineLvl", "jc", "keepNext",
    "keepLines", "contextualSpacing", "caps", "smallCaps", "u", "lang", "noProof",
    "autoSpaceDE", "autoSpaceDN", "widowControl", "numPr", "numId", "ilvl",
    "pageBreakBefore", "lastRenderedPageBreak",
)}


def _plain(element):
    # Freeze this proof before redaction: a cleared drawing, field, bookmark or
    # alternate branch must never become permission to discard native geometry.
    return (element.tag == qn("w:p")
            and all(node.tag in _FORMATTING for node in element.iter()))


def _empty_boundary(element):
    if element.tag == qn("w:sectPr"):
        return True
    if _text(element).strip():
        return False
    plain = deepcopy(element)
    for section in list(plain.iter(qn("w:sectPr"))):
        section.getparent().remove(section)
    return _plain(plain)


@dataclass(frozen=True)
class EmptyActivityPanel:
    heading: object
    tail: tuple
    boundary: object
    preceding: tuple

    def remove_if_empty(self, body, pages, cleared):
        """Recheck final payloads and remove only source-proved empty roots."""
        panel = (self.heading, *self.tail)
        if any(node.getparent() is not body or node in pages.live
               or node in pages.support or node in pages.headings for node in panel):
            return
        if (self.boundary.getparent() is not body or not _empty_boundary(self.boundary)
                or self.boundary in pages.live):
            return
        current = self.heading
        for expected in (*self.tail, self.boundary):
            current = current.getnext()
            if current is not expected:
                return  # A newly inserted picture, caption or other payload owns the space.
        if (_text(self.heading).casefold().strip() != _TITLE
                or not _plain(self.heading)
                or any(_text(node).strip() or not _plain(node) for node in self.tail)):
            return
        # Replaced narrative can leave many empty paragraphs before the panel
        # in a section pinned by an unchanged work-order table. Only paragraphs
        # actually cleared in this build are eligible; authored blank spacing,
        # live narrative and native section boundaries stop the backwards scan.
        remove = list(panel)
        previous = self.heading.getprevious()
        for candidate in reversed(self.preceding):
            if (previous is not candidate or candidate not in cleared
                    or candidate in pages.live or candidate in pages.support
                    or candidate in pages.headings or _text(candidate).strip()
                    or not _plain(candidate)):
                break
            remove.append(candidate)
            previous = candidate.getprevious()
        for node in remove:
            body.remove(node)


def empty_activity_panels(draft, original, sections, unchanged, headings):
    """Prove plain, trailing Activity panels before any source text is cleared."""
    if any(block.key == "improvements" and block.source != "Omit"
           and any((block.text.strip(), block.rows, block.extra_tables,
                    block.asset_hashes, block.asset_instances, block.org_nodes))
           for block in draft.blocks):
        return ()
    plans = []
    for index, heading in enumerate(original):
        if (sections.get(index + 1) != "activity" or index + 1 in unchanged
                or index + 1 in headings or not _plain(heading)
                or _text(heading).casefold().strip() != _TITLE):
            continue
        tail, boundary = [], None
        for position in range(index + 1, len(original)):
            node = original[position]
            properties = (node if node.tag == qn("w:sectPr")
                          else node.find(".//" + qn("w:sectPr")))
            if properties is not None:
                # Keep the complete boundary paragraph, including its header
                # routes. A heading/artwork sharing it is not an empty panel.
                if _empty_boundary(node):
                    boundary = node
                break
            if (sections.get(position + 1) != "activity" or position + 1 in unchanged
                    or position + 1 in headings or not _plain(node)
                    or _text(node).casefold().strip() == _TITLE):
                break
            tail.append(node)
        if boundary is None:
            continue
        preceding = []
        for position in range(index - 1, -1, -1):
            node = original[position]
            if (sections.get(position + 1) != "activity" or position + 1 in unchanged
                    or position + 1 in headings or not _plain(node)
                    or not _text(node).strip()):
                break
            preceding.append(node)
        plans.append(EmptyActivityPanel(heading, tuple(tail), boundary,
                                        tuple(reversed(preceding))))
    return tuple(plans)
