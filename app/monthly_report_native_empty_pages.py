"""Remove only source-proved empty explicit pages in protected scorecards."""
from dataclasses import dataclass
from docx.oxml.ns import qn

# Unknown fields, links, drawings, bookmarks and section boundaries are never
# disposable, even when their visible text happens to be empty after redaction.
_FORMATTING = {qn('w:' + name) for name in (
    'p', 'pPr', 'pStyle', 'r', 'rPr', 't', 'rFonts', 'b', 'bCs', 'i', 'iCs',
    'color', 'sz', 'szCs', 'spacing', 'ind', 'jc', 'keepNext', 'keepLines',
    'contextualSpacing', 'caps', 'smallCaps', 'u', 'lang', 'noProof',
    'widowControl', 'numPr', 'numId', 'ilvl', 'br', 'lastRenderedPageBreak',
)}


def _plain(node):
    return (node.tag == qn('w:p') and all(n.tag in _FORMATTING for n in node.iter())
            and all(n.get(qn('w:type')) == 'page' for n in node.iter(qn('w:br'))))


def _text(node):
    return ''.join(n.text or '' for n in node.iter(qn('w:t'))).strip()


def _boundary(node):
    return node.tag == qn('w:sectPr') or node.find('.//' + qn('w:sectPr')) is not None


def _physical_ending(node):
    # Paragraph section properties describe physical geometry but do not prove
    # that the following section starts on a new page. Limit tails to the
    # terminal document boundary rather than infer continuous/next-page flow.
    return node is None or node.tag == qn('w:sectPr')


@dataclass(frozen=True)
class EmptyPagePlan:
    runs: tuple

    def apply(self, body, pages, cleared):
        for nodes, previous, following, tail in self.runs:
            roots = tuple(nodes)
            if not roots or any(n.getparent() is not body or not _plain(n)
                                or _text(n) or n in pages.live or n in pages.support
                                or n in pages.headings for n in roots):
                continue
            if (not any(nodes.values())
                    or any(n not in cleared and had_text for n, had_text in nodes.items())):
                continue
            if any(a.getnext() is not b for a, b in zip(roots, roots[1:])):
                continue
            # Neither a new payload nor an unknown insertion can borrow this
            # source page's cleanup proof. Keep both exact neighboring roots.
            if roots[0].getprevious() is not previous or roots[-1].getnext() is not following:
                continue
            if tail and (not _physical_ending(following)
                         or following in pages.live or following in pages.support
                         or following in pages.headings):
                continue
            target = previous if tail else roots[-1]
            if tail and (target is None or target.getparent() is not body or not _plain(target)
                         or _text(target) or target in pages.live or target in pages.support
                         or target in pages.headings):
                continue
            breaks = list(target.iter(qn('w:br')))
            if len(breaks) == 1:
                breaks[0].getparent().remove(breaks[0])


def empty_scorecard_pages(original, sections):
    """Freeze plain page spans before redaction; retain every Word section."""
    runs, current, previous, starts_page = [], {}, None, True
    for pos, node in enumerate(original, 1):
        if sections.get(pos) != 'scorecards' or _boundary(node):
            if (_boundary(node) and _physical_ending(node) and current and starts_page
                    and previous is not None and not _boundary(previous)):
                runs.append((current, previous, node, True))
            # A logical transition or paragraph section property is not a
            # proven physical page start. Only explicit standalone breaks below
            # can restore that proof within the document.
            current, previous, starts_page = {}, node, False
            continue
        if not _plain(node):
            current, previous, starts_page = {}, node, False
            continue
        current[node] = bool(_text(node))
        breaks = list(node.iter(qn('w:br')))
        if breaks:
            # A text-bearing or multi-break paragraph is not a page delimiter.
            if _text(node) or len(breaks) != 1:
                current, previous, starts_page = {}, node, False
                continue
            if starts_page:
                runs.append((current, previous, node.getnext(), False))
            current, previous, starts_page = {}, node, True
    if current and starts_page and previous is not None and not _boundary(previous):
        runs.append((current, previous, None, True))
    return EmptyPagePlan(tuple(runs))
