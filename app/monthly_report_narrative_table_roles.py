"""Conservative source table roles, used only to select rewritten prose styling."""
import re
from collections import defaultdict

from docx.oxml.ns import qn

from app.monthly_report_import import _text
from app.monthly_report_native_text import _outline, narrative_prototype
from app.monthly_report_native_table_context import _plain, _PLAIN, _visible_style


def table_body_roles(original, styles, style_root, scopes, *, static_labels=()):
    """Exclude structurally proved captions/totals, not emphasized prose generally.

    A short uniformly bold-underlined title must immediately introduce a table
    under an outlined heading in the same mapped role. Ambiguous captions keep
    their old behavior. A role with no other prose uses document body defaults;
    it must not borrow an unrelated role's footnote or a tab-aligned total.
    """
    def neighbor(element, forward=False):
        node = element.getnext() if forward else element.getprevious()
        while node is not None and scopes.get(node) == scopes[element]:
            if node.tag != qn('w:p') or _text(node).strip():
                return node
            if (node.find('.//' + qn('w:sectPr')) is not None
                    or node.find('.//' + qn('w:br')) is not None
                    or node.find('.//' + qn('w:pageBreakBefore')) is not None):
                return None
            node = node.getnext() if forward else node.getprevious()
        return None

    captions, excluded = set(), set()
    for element in original:
        if element.tag != qn('w:p') or not _plain(element, style_root):
            continue
        text = _text(element).strip()
        words = re.findall(r'[^\W\d_]+', text)
        runs = [r for r in element.iter(qn('w:r')) if _text(r).strip()]
        connectors = {'a', 'an', 'and', 'at', 'for', 'in', 'of', 'on', 'or', 'the', 'to'}
        if (len(words) < 2 or len(text) > 90 or text[-1:] in '.?!:;…'
                or not all(w[0].isupper() or w in connectors for w in words)
                or not runs or _outline(element, styles)):
            continue
        def marked(run, tag):
            marker = run.find('./' + qn('w:rPr') + '/' + qn('w:' + tag))
            return marker is not None and marker.get(qn('w:val')) not in ('0', 'false', 'off', 'none')
        if not all(marked(run, 'b') and marked(run, 'u') for run in runs):
            continue
        following = element.getnext()
        previous = neighbor(element)
        if (following is not None and following.tag == qn('w:tbl')
                and scopes.get(following) == scopes[element]
                and previous is not None and previous.tag == qn('w:p')
                and _outline(previous, styles)):
            captions.add(element)
    excluded.update(captions)
    caption_tables = {element.getnext() for element in captions}
    for element in original:
        if (element.tag != qn('w:p') or neighbor(element) not in caption_tables
                or len(element.findall('./' + qn('w:r') + '/' + qn('w:tab'))) != 1
                or not re.match(r'^total\b', _text(element).strip(), re.I)
                or not _visible_style(element, style_root)
                or not all(node.tag in _PLAIN | {qn('w:tab'), qn('w:tabs')}
                           for node in element.iter())):
            continue
        excluded.add(element)
    candidates = defaultdict(list)
    for element in original:
        if (element.tag == qn('w:p') and element not in excluded
                and narrative_prototype(element, styles, static_labels, scopes=scopes) is not None):
            candidates[scopes[element]].append(element)
    neutral = {scopes[element] for element in captions if not candidates[scopes[element]]}
    return excluded, neutral
