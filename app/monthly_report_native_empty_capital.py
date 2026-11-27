"""Discard only an unused, source-proved priority-table prototype."""
from docx.oxml.ns import qn

from app.monthly_report_import import _text


_HEADERS = ('Equipment Description', 'End of Useful Life', 'Cost', 'Summary of deficiency')
_PLAIN = {qn('w:' + name) for name in (
    'tbl', 'tblPr', 'tblGrid', 'gridCol', 'tblStyle', 'tblW', 'tblLook',
    'tr', 'trPr', 'trHeight', 'tc', 'tcPr', 'tcW', 'gridSpan', 'vAlign',
    'p', 'pPr', 'r', 'rPr', 't', 'rFonts', 'b', 'bCs', 'i', 'iCs',
    'color', 'sz', 'szCs', 'spacing', 'ind', 'jc', 'cnfStyle', 'hideMark',
    'autoSpaceDE', 'autoSpaceDN', 'widowControl',
)}


def proved_priority_prototype(element):
    """Freeze strict source structure before old values are redacted."""
    if element.tag != qn('w:tbl') or any(n.tag not in _PLAIN for n in element.iter()):
        return False
    rows = element.findall(qn('w:tr'))
    if len(rows) != 2:
        return False
    cells = rows[0].findall(qn('w:tc'))
    return len(cells) == 4 and tuple(_text(c).strip() for c in cells) == _HEADERS


def _signature(element):
    return (element.tag, tuple(sorted(element.attrib.items())),
            (element.text or '') if element.tag == qn('w:t') else '',
            tuple(_signature(child) for child in element))


def raw_priority_prototypes(source_path):
    """Use the same bounded archive and non-networked XML parser as intake."""
    from app.monthly_report_import import _package
    from app.monthly_report_xml_parser import parse_xml
    with _package(source_path) as archive:
        root = parse_xml(archive.read('word/document.xml'))
    return {position: _signature(node)
            for position, node in enumerate(root.find(qn('w:body')), 1)
            if proved_priority_prototype(node)}


def matches_priority_prototype(element, signature):
    return signature is not None and _signature(element) == signature


def remove_unused_priority_prototypes(draft, candidates, body, pages, original, native_tables, preserved_refs):
    """Current explicit schedule is necessary; appearance alone proves nothing."""
    priority = next((b for b in draft.blocks if b.key == 'capital_renewal'), None)
    if priority is not None and priority.source != 'Omit' and any((
            priority.text.strip(), priority.rows, priority.extra_tables,
            priority.asset_hashes, priority.asset_instances, priority.org_nodes)):
        return
    schedule = next((b for b in draft.blocks if b.key == 'end_of_life' and b.source != 'Omit'), None)
    if schedule is None or not any(t.rows for t in schedule.extra_tables):
        return
    # Only an exact retained source-bound schedule, not a same-shaped table.
    retained = [native_tables[t.reference] for t in schedule.extra_tables
                if t.rows and t.reference in preserved_refs and t.reference in native_tables
                and native_tables[t.reference].suggested_slot == 'end_of_life']
    if not any(original[t.position - 1].getparent() is body for t in retained):
        return
    for table in candidates:
        if (table.getparent() is not body or table in pages.live
                or table in pages.support or table in pages.headings
                or any(n.tag not in _PLAIN for n in table.iter())):
            continue
        rows = table.findall(qn('w:tr'))
        if len(rows) != 2 or any(_text(row).strip() for row in rows[1:]):
            continue
        header = tuple(_text(c).strip() for c in rows[0].findall(qn('w:tc')))
        if header != (_HEADERS[0], _HEADERS[1], '', _HEADERS[3]):
            continue
        body.remove(table)
