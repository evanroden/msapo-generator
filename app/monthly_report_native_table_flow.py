"""Prove complete current flows for the native capacity and proposal layouts.

This supplements the generic adjacent-context proof. It never makes a partial
source group, an arbitrary sibling block, or a current-only caveat relocatable.
"""
from copy import deepcopy
from dataclasses import dataclass

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_import import _text
from app.monthly_report_native_table_context import _plain


@dataclass(frozen=True)
class SuppliedTableFlow:
    items: tuple
    remaining_text: str
    rewrites: tuple


def _word_sections(original):
    result, section = {}, 1
    for position, element in enumerate(original, 1):
        result[position] = section
        if element.tag == qn("w:sectPr") or element.find(".//" + qn("w:sectPr")) is not None:
            section += 1
    return result


def _flow_plain(element, styles):
    if _plain(element, styles):
        return True
    # A wrapping break adds only an inspected line break. Page/column breaks,
    # fields, unknown attributes and alternative representations remain opaque.
    breaks = list(element.iter(qn("w:br")))
    if not breaks or any(set(node.attrib) - {qn("w:type")}
                         or node.get(qn("w:type")) not in (None, "textWrapping")
                         or node.getparent().tag != qn("w:r")
                         or node.text or len(node) for node in breaks):
        return False
    copy = deepcopy(element)
    for node in list(copy.iter(qn("w:br"))):
        node.getparent().remove(node)
    return _plain(copy, styles)


def _spacing(element, styles):
    if _text(element).strip() or not _plain(element, styles):
        return False
    if any(node.tag == qn("w:pageBreakBefore") for node in element.iter()):
        return False
    defaults = styles.find(qn("w:docDefaults"))
    if defaults is not None and list(defaults.iter(qn("w:pageBreakBefore"))):
        return False
    by_id = {style.get(qn("w:styleId")): style for style in styles.findall(qn("w:style"))}
    selected = element.find("./" + qn("w:pPr") + "/" + qn("w:pStyle"))
    identity = selected.get(qn("w:val")) if selected is not None else next((
        key for key, style in by_id.items() if style.get(qn("w:type")) == "paragraph"
        and style.get(qn("w:default")) in ("1", "true", "on")), None)
    seen = set()
    while identity is not None:
        if identity in seen or identity not in by_id:
            return False
        seen.add(identity)
        style = by_id[identity]
        if list(style.iter(qn("w:pageBreakBefore"))):
            return False
        base = style.find(qn("w:basedOn"))
        identity = base.get(qn("w:val")) if base is not None else None
    return True


def _paragraph(position, original, items, styles, section):
    element = original[position - 1]
    group = items[position]
    if (not _flow_plain(element, styles) or len(group) != 1
            or group[0].kind != "text" or group[0].section != section
            or not group[0].text.strip() or group[0].text.strip() != _text(element).strip()):
        return None
    return group[0]


def _match(block, context, *, ignored=()):
    lines = block.text.splitlines()
    nonblank = [index for index, line in enumerate(lines) if line.strip() and index not in ignored]
    selected, consumed, rewrites = [], set(), []
    for item in context:
        expected = tuple(line.strip() for line in item.text.splitlines() if line.strip())
        matches = []
        for offset in range(len(nonblank) - len(expected) + 1):
            indices = nonblank[offset:offset + len(expected)]
            current = tuple(lines[index].strip() for index in indices)
            if current == expected or current == ("Historical context: " + expected[0], *expected[1:]):
                matches.append(indices)
        if len(matches) != 1 or any(index in consumed for index in matches[0]):
            return None
        indices = matches[0]
        selected.extend(indices)
        consumed.update(range(indices[0], indices[-1] + 1))
        value = "\n".join(lines[index] for index in range(indices[0], indices[-1] + 1))
        if value.strip() != item.text.strip():
            rewrites.append((item.position, value))
    # Every inspected paragraph is supplied, once, in order, as a complete
    # trailing body run. Native footnotes have a separate, proved attachment.
    if not selected or selected != nonblank[-len(selected):]:
        return None
    return SuppliedTableFlow(tuple(context), "\n".join(
        line for index, line in enumerate(lines) if index not in consumed and index not in ignored
        ).strip(), tuple(rewrites))


def _native_note_suffix(block, source_tables, last_flow_table, original, supplied_notes, source_ref):
    lines = block.text.splitlines()
    nonblank = [index for index, line in enumerate(lines) if line.strip()]
    if not nonblank:
        return ()
    ignored = []
    for identity, item in supplied_notes.items():
        if source_ref(item) not in block.references or item.section != "proposals" or "\n" in item.text:
            continue
        matches = [index for index, line in enumerate(lines) if line.strip() == item.text.strip()]
        if matches != [nonblank[-1]]:
            continue
        kind, note_id = identity.split(":", 1)
        anchors = [table for table in source_tables
                   for node in original[table.position - 1].iter(qn("w:" + kind + "Reference"))
                   if node.get(qn("w:id")) == note_id]
        if len(anchors) == 1 and anchors[0].position > last_flow_table.position:
            ignored.extend(matches)
    # One authored line must identify one proved native note attachment.
    return tuple(ignored) if len(ignored) == 1 else ()


def supplied_native_table_flows(draft, original, items, section_by_pos, native_tables,
                               preserved_refs, *, styles, supplied_notes, source_ref):
    """Authorize only complete known flows beside exact, uniquely owned tables."""
    destinations = {spec.key: section.key for section in draft.sections if section.included
                    for spec in section.blocks}
    active = [block for block in draft.blocks if block.source != "Omit"]
    by_key = {block.key: block for block in active}
    if len(by_key) != len(active):
        return {}
    owners = {}
    for block in active:
        for table in block.extra_tables:
            owners.setdefault(table.reference, []).append(block.key)
    physical = _word_sections(original)
    result = {}

    def tables_for(key, section):
        block = by_key.get(key)
        if block is None or destinations.get(key) != section or not block.extra_tables:
            return ()
        if any(table.reference not in preserved_refs or table.reference not in native_tables
               or owners.get(table.reference) != [key]
               or native_tables[table.reference].section != section for table in block.extra_tables):
            return ()
        tables = tuple(native_tables[table.reference] for table in block.extra_tables)
        return tables if list(t.position for t in tables) == sorted({t.position for t in tables}) else ()

    utility, capacity = by_key.get("utility_analysis"), by_key.get("thermal_capacity")
    tables = tables_for("thermal_capacity", "scorecards")
    if (utility is not None and destinations.get(utility.key) == "scorecards"
            and utility.text.strip() and not utility.extra_tables and not utility.rows and capacity is not None
            and not capacity.text.strip() and not capacity.rows and len(tables) == 2
            and physical[tables[0].position] == physical[tables[1].position]):
        region = physical[tables[0].position]
        positions = [position for position, word_section in physical.items() if word_section == region
                     and _text(original[position - 1]).strip()]
        pattern = ["table" if position in {table.position for table in tables} else "text"
                   for position in positions]
        if pattern == ["text", "text", "text", "table", "text", "table", "text"]:
            context = [_paragraph(position, original, items, styles, "scorecards")
                       for position in positions if position not in {table.position for table in tables}]
            if (all(context) and context[0].text.strip().casefold() == "thermal services requirements and capacity"
                    and all(item.suggested_slot == "utility_analysis" for item in context)
                    and all(section_by_pos[position] == "scorecards" for position in positions)
                    and all(position in positions or _spacing(original[position - 1], styles)
                            for position in range(positions[0], positions[-1] + 1))
                    and not any(block.key not in ("utility_analysis", "thermal_capacity")
                                and destinations.get(block.key) == "scorecards" and block.text.strip()
                                for block in active)):
                flow = _match(utility, context)
                if flow is not None:
                    result[utility.key] = flow

    proposals = by_key.get("proposals")
    tables = tables_for("proposals", "proposals")
    if (proposals is not None and proposals.text.strip() and not proposals.rows and len(tables) >= 2
            and not any(block.key != "proposals" and destinations.get(block.key) == "proposals"
                        and block.text.strip() for block in active)):
        labels = {}
        for table in tables:
            position = table.position - 1
            while (position > 0 and physical[position] == physical[table.position]
                   and section_by_pos[position] == "proposals"
                   and _spacing(original[position - 1], styles)):
                position -= 1
            if position < 1 or physical[position] != physical[table.position]:
                continue
            label = _paragraph(position, original, items, styles, "proposals")
            if label is not None and label.text.strip() in ("Rejected Quotes", "Pending Quotes"):
                labels.setdefault(label.text.strip(), []).append((label, table))
        if all(len(labels.get(title, ())) == 1 for title in ("Rejected Quotes", "Pending Quotes")):
            rejected, pending = labels["Rejected Quotes"][0], labels["Pending Quotes"][0]
            start, end = rejected[0].position - 1, pending[1].position
            if (start > 0 and rejected[1].position < pending[0].position
                    and physical[start] == physical[end]):
                positions = list(range(start, end + 1))
                table_positions = {rejected[1].position, pending[1].position}
                context, pattern, valid = [], [], True
                for position in positions:
                    if section_by_pos[position] != "proposals":
                        valid = False
                        break
                    if position in table_positions:
                        pattern.append("table")
                    elif _text(original[position - 1]).strip():
                        item = _paragraph(position, original, items, styles, "proposals")
                        if item is None:
                            valid = False
                            break
                        context.append(item)
                        pattern.append("text")
                    elif not _spacing(original[position - 1], styles):
                        valid = False
                        break
                if valid and pattern == ["text", "text", "table", "text", "table"]:
                    ignored = _native_note_suffix(proposals, tables, pending[1], original,
                                                  supplied_notes, source_ref)
                    flow = _match(proposals, context, ignored=ignored)
                    if flow is not None:
                        result[proposals.key] = flow
    return result


def rewrite_flow_paragraph(element, value):
    """Write exactly the supplied words at their proved source-owned anchor."""
    from app.monthly_report_native_text import write_narrative

    prototype = OxmlElement("w:p")
    properties = element.find(qn("w:pPr"))
    if properties is not None:
        prototype.append(deepcopy(properties))
    run = OxmlElement("w:r")
    source = next((run for run in element.findall(qn("w:r")) if _text(run)), None)
    properties = source.find(qn("w:rPr")) if source is not None else None
    if properties is not None:
        run.append(deepcopy(properties))
    run.append(OxmlElement("w:t"))
    prototype.append(run)
    lines = value.splitlines()
    write_narrative(element, prototype, lines[0])
    run = element.find(qn("w:r"))
    for line in lines[1:]:
        run.append(OxmlElement("w:br"))
        text = OxmlElement("w:t")
        text.text = line
        text.set(qn("xml:space"), "preserve")
        run.append(text)
