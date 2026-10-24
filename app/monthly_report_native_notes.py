"""Conservative, source-bound removal of duplicate native foot/endnote lines.

This is an opt-in proof for deleting current text, not a general Word renderer.
Unknown markup/formatting retains the author's line, even if that duplicates a note.
"""
from collections import Counter
from lxml import etree
from docx.oxml.ns import qn

_PPR = tuple(qn('w:' + x) for x in (
    'pStyle', 'keepNext', 'keepLines', 'pageBreakBefore', 'widowControl', 'numPr',
    'suppressLineNumbers', 'pBdr', 'shd', 'tabs', 'suppressAutoHyphens', 'kinsoku',
    'wordWrap', 'overflowPunct', 'topLinePunct', 'autoSpaceDE', 'autoSpaceDN',
    'bidi', 'adjustRightInd', 'snapToGrid', 'spacing', 'ind', 'contextualSpacing',
    'mirrorIndents', 'suppressOverlap', 'jc', 'textDirection', 'textAlignment',
    'textboxTightWrap', 'outlineLvl', 'divId', 'cnfStyle', 'rPr'))
_RPR = tuple(qn('w:' + x) for x in (
    'rStyle', 'rFonts', 'b', 'bCs', 'i', 'iCs', 'caps', 'smallCaps', 'strike',
    'dstrike', 'outline', 'shadow', 'emboss', 'imprint', 'noProof', 'snapToGrid',
    'color', 'spacing', 'w', 'kern', 'position', 'sz', 'szCs', 'highlight', 'u',
    'effect', 'bdr', 'shd', 'fitText', 'vertAlign', 'rtl', 'cs', 'em', 'lang',
    'eastAsianLayout'))
_HIDDEN = {qn('w:' + x) for x in ('vanish', 'webHidden', 'specVanish')}


def _properties(node, allowed):
    if node is None:
        return True
    tags = [child.tag for child in node]
    if len(tags) != len(set(tags)) or any(tag not in allowed for tag in tags):
        return False
    if [allowed.index(tag) for tag in tags] != sorted(allowed.index(tag) for tag in tags):
        return False
    # Numbering and table-condition overrides are not plain visibility proofs.
    if any(child.tag in _HIDDEN | {qn('w:numPr'), qn('w:cnfStyle')} for child in node.iter()):
        return False
    for child in node:
        if child.tag == qn('w:rPr'):
            if not _properties(child, _RPR):
                return False
        elif len(child):
            return False
        if child.tag in (qn('w:pStyle'), qn('w:rStyle')) and not child.get(qn('w:val')):
            return False
        if child.tag == qn('w:color') and (child.get(qn('w:val')) not in ('auto', '000000')
                or any(key != qn('w:val') for key in child.attrib)):
            return False
    return True


def _one(parent, tag):
    values = parent.findall(qn('w:' + tag))
    return values[0] if len(values) == 1 else None


def plain_visible(paragraph, styles):
    """Prove a direct paragraph's note words/reference visible, failing closed."""
    if paragraph.tag != qn('w:p'):
        return False
    children = list(paragraph)
    properties = paragraph.findall(qn('w:pPr'))
    if len(properties) > 1 or (properties and children[0] is not properties[0]):
        return False
    ppr = properties[0] if properties else None
    if not _properties(ppr, _PPR) or any(c.tag not in (qn('w:pPr'), qn('w:r')) for c in children):
        return False
    entries = styles.findall(qn('w:style'))
    ids = [style.get(qn('w:styleId')) for style in entries]
    if None in ids or len(ids) != len(set(ids)):
        return False
    by_id = dict(zip(ids, entries))
    defaults = styles.findall(qn('w:docDefaults'))
    if len(defaults) > 1:
        return False
    if defaults:
        if any(c.tag not in (qn('w:rPrDefault'), qn('w:pPrDefault')) for c in defaults[0]):
            return False
        for label, prop, allowed in [('rPrDefault', 'rPr', _RPR), ('pPrDefault', 'pPr', _PPR)]:
            wrappers = defaults[0].findall(qn('w:' + label))
            if len(wrappers) > 1:
                return False
            if wrappers and (len(wrappers[0]) > 1 or
                    any(c.tag != qn('w:' + prop) for c in wrappers[0]) or
                    not _properties(_one(wrappers[0], prop), allowed)):
                return False
    implicit = {}
    for kind in ('paragraph', 'character'):
        matches = [s for s in entries if s.get(qn('w:type')) == kind and s.get(qn('w:default')) in ('1', 'true', 'on')]
        if len(matches) > 1:
            return False
        implicit[kind] = matches[0].get(qn('w:styleId')) if matches else None

    def style_visible(identity, kind):
        if identity is None:
            return kind == 'character'
        seen = set()
        while identity:
            if identity in seen or identity not in by_id:
                return False
            seen.add(identity)
            style = by_id[identity]
            if style.get(qn('w:type')) != kind:
                return False
            allowed = {qn('w:' + name) for name in (
                'name', 'aliases', 'basedOn', 'next', 'link', 'autoRedefine',
                'hidden', 'uiPriority', 'semiHidden', 'unhideWhenUsed', 'qFormat',
                'locked', 'personal', 'personalCompose', 'personalReply', 'rsid',
                'pPr', 'rPr')}
            tags = [child.tag for child in style]
            if len(tags) != len(set(tags)) or any(tag not in allowed for tag in tags):
                return False
            if any(len(child) for child in style if child.tag not in (qn('w:pPr'), qn('w:rPr'))):
                return False
            for label, allowed in [('pPr', _PPR), ('rPr', _RPR)]:
                props = style.findall(qn('w:' + label))
                if len(props) > 1 or (props and not _properties(props[0], allowed)):
                    return False
            if any(n.tag in _HIDDEN | {qn('w:tblStylePr')} for n in style.iter()):
                return False
            bases = style.findall(qn('w:basedOn'))
            if len(bases) > 1 or (bases and not bases[0].get(qn('w:val'))):
                return False
            identity = bases[0].get(qn('w:val')) if bases else None
        return True

    selector = _one(ppr, 'pStyle') if ppr is not None else None
    identity = selector.get(qn('w:val')) if selector is not None else implicit['paragraph']
    if not identity or not style_visible(identity, 'paragraph'):
        return False
    for run in paragraph.findall(qn('w:r')):
        props = run.findall(qn('w:rPr'))
        if len(props) > 1 or (props and list(run)[0] is not props[0]):
            return False
        rpr = props[0] if props else None
        if not _properties(rpr, _RPR):
            return False
        if any(c.tag not in {qn('w:' + t) for t in ('rPr', 't', 'footnoteRef', 'endnoteRef', 'footnoteReference', 'endnoteReference')} for c in run):
            return False
        selector = _one(rpr, 'rStyle') if rpr is not None else None
        identity = selector.get(qn('w:val')) if selector is not None else implicit['character']
        if selector is not None and not identity:
            return False
        if not style_visible(identity, 'character'):
            return False
    return True


def note_proofs(document, original, inspection, section_by_pos, default_slots):
    """Capture immutable single-note/single-owner evidence before any body rewrite."""
    from app.monthly_report_import import _text
    proofs = {}
    counts = Counter(i.note for i in inspection.items if i.note.startswith(('footnote:', 'endnote:')))
    for item in inspection.items:
        if counts[item.note] != 1:
            continue
        kind, identity = item.note.split(':', 1)
        refs = [(position, element, node) for position, element in enumerate(original, 1)
                for node in element.iter(qn('w:' + kind + 'Reference')) if node.get(qn('w:id')) == identity]
        if len(refs) != 1:
            continue
        position, element, reference = refs[0]
        if element.tag != qn('w:p') or not plain_visible(element, document.styles.element):
            continue
        section = section_by_pos[position]
        group = [i for i in inspection.items if i.part == 'word/document.xml' and i.position == position]
        slots = {i.suggested_slot for i in group if i.suggested_slot and not i.suggested_slot.startswith('divider_')}
        owner = next(iter(slots)) if len(slots) == 1 else default_slots.get(section) if not slots else None
        if section != item.section or not owner:
            continue
        parts = [rel.target_part for rel in document.part.rels.values()
                 if not rel.is_external and rel.reltype.endswith('/' + kind + 's')]
        if len(parts) != 1:
            continue
        root = etree.fromstring(parts[0].blob)
        notes = [n for n in root if n.tag == qn('w:' + kind) and n.get(qn('w:id')) == identity]
        if len(notes) != 1 or len(notes[0]) != 1:
            continue
        paragraph = notes[0][0]
        if not plain_visible(paragraph, document.styles.element) or _text(paragraph).strip() != item.text.strip():
            continue
        proofs[item.note] = (owner, reference)
    return proofs


def without_trailing_note(text, note):
    """Delete only the sole exact trailing line; never normalize other characters."""
    if not note or '\n' in note or '\r' in note or text.count(note) != 1:
        return None
    lines = text.splitlines(keepends=True)
    nonblank = [i for i, line in enumerate(lines) if line.strip()]
    if not nonblank:
        return None
    index = nonblank[-1]
    if lines[index].rstrip('\r\n') != note:
        return None
    return ''.join(line for i, line in enumerate(lines) if i != index)
