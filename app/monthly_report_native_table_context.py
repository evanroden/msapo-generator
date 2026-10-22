"""Keep explicitly supplied prose beside its exact retained native table."""
from docx.oxml.ns import qn

from app.monthly_report_import import _heading, _text


_PLAIN = {qn("w:" + name) for name in (
    "p", "pPr", "pStyle", "r", "rPr", "t", "rFonts", "b", "bCs", "i", "iCs",
    "color", "sz", "szCs", "spacing", "ind", "outlineLvl", "jc", "keepNext",
    "keepLines", "contextualSpacing", "caps", "smallCaps", "u", "lang", "noProof",
    "pageBreakBefore")}
_HIDDEN = {qn("w:" + name) for name in ("vanish", "webHidden", "specVanish")}
_UNPROVED_STYLE = _HIDDEN | {qn("w:numPr")}


def _visible_style(element, styles):
    # Direct paragraph markup does not reveal hidden formatting inherited from
    # a style or document default. Numbering can add source-only prefix words.
    # Unknown/cyclic style chains and inherited numbering are unproved.
    defaults = styles.find(qn("w:docDefaults"))
    if defaults is not None and any(node.tag in _UNPROVED_STYLE for node in defaults.iter()):
        return False
    by_id = {style.get(qn("w:styleId")): style for style in styles.findall(qn("w:style"))}
    implicit = {style.get(qn("w:type")): identity for identity, style in by_id.items()
                if style.get(qn("w:default")) in ("1", "true", "on")}
    selected = element.find("./" + qn("w:pPr") + "/" + qn("w:pStyle"))
    paragraph = selected.get(qn("w:val")) if selected is not None else implicit.get("paragraph")
    if not paragraph:
        return False
    for identity in (paragraph, implicit.get("character")):
        seen = set()
        while identity is not None:
            if identity in seen or identity not in by_id:
                return False
            seen.add(identity)
            style = by_id[identity]
            if any(node.tag in _UNPROVED_STYLE for node in style.iter()):
                return False
            bases = style.findall(qn("w:basedOn"))
            if len(bases) > 1:
                return False
            identity = bases[0].get(qn("w:val"), "") if bases else None
    return True


def _plain(element, styles):
    # Unknown fields, alternate branches, glyphs, hyperlinks and pictures are
    # not certified by matching their extracted visible words.
    return (element.tag == qn("w:p")
            and all(node.tag in _PLAIN for node in element.iter())
            and all(child.tag in (qn("w:pPr"), qn("w:r")) for child in element)
            and all(child.tag in (qn("w:rPr"), qn("w:t"))
                    for run in element.findall(qn("w:r")) for child in run)
            and _visible_style(element, styles))


def supplied_table_context(draft, original, items, section_by_pos, native_tables, preserved_refs, *, styles):
    """Return current context items and remaining prose for each owning block.

    Only unchanged, source-bound tables qualify. A plain adjacent source
    paragraph must also occur exactly once as a complete current-text line.
    The current author supplies the words; the table's immutable reference
    supplies their original placement. Missing/edited prose is never restored.
    """
    destinations = {spec.key: section.key for section in draft.sections for spec in section.blocks}
    result = {}
    for block in draft.blocks:
        if block.source == "Omit" or block.key not in destinations or not block.text.strip():
            continue
        section = destinations[block.key]
        source_tables = [native_tables[table.reference] for table in block.extra_tables
                         if table.reference in preserved_refs and table.reference in native_tables
                         and native_tables[table.reference].section == section]
        candidates = {}
        unproved_context = False
        for table in source_tables:
            for position in range(table.position - 1, 0, -1):
                element = original[position - 1]
                if section_by_pos[position] != section or _heading(_text(element)):
                    break
                if not _plain(element, styles):
                    # A hidden/opaque title does not make its nearer scope a
                    # complete group. Empty boundaries and tables end a group;
                    # unproved paragraph words invalidate its partial proof.
                    unproved_context = element.tag == qn("w:p") and bool(_text(element).strip())
                    break
                if not _text(element).strip():
                    # Empty paragraphs, including pageBreakBefore boundaries,
                    # separate earlier prose from this table's context.
                    break
                group = items[position]
                text_items = [item for item in group if item.kind == "text"]
                if len(group) == len(text_items) == 1:
                    item = text_items[0]
                    if item.text.strip() and "\n" not in item.text:
                        candidates[item.position] = item
                    elif item.text.strip():
                        unproved_context = True
                        break
                elif _text(element).strip():
                    unproved_context = True
                    break
            if unproved_context:
                break
        if unproved_context:
            continue
        lines = block.text.splitlines()
        consumed, selected, selected_lines = set(), [], []
        for item in (candidates[position] for position in sorted(candidates)):
            matches = [index for index, line in enumerate(lines)
                       if line.strip() == item.text.strip()]
            if len(matches) == 1 and matches[0] not in consumed:
                consumed.add(matches[0])
                selected.append(item)
                selected_lines.append(matches[0])
        if selected:
            # Only a trailing source-ordered context run can be placed back by
            # its tables. Interleaved/current notes or reordered lines retain
            # their authored flow. A partially edited group must not split its
            # corrected title/scope from the unchanged words beside its table.
            nonblank = [index for index, line in enumerate(lines) if line.strip()]
            if (len(selected) != len(candidates)
                    or selected_lines != nonblank[-len(selected_lines):]):
                continue
            result[block.key] = (tuple(selected), "\n".join(
                line for index, line in enumerate(lines) if index not in consumed).strip())
    return result
