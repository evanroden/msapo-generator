"""Reconcile only proved, passive native contents on the report derivative."""
import re
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from app.monthly_report_contents_pagination import PREFIX, add_entry, anchor_for, mark_target
from app.monthly_report_contents_review import contents_kind
from app.monthly_report_xml_parser import parse_xml

NOTICE = ("Contents not updated. Do not rely on source contents titles, order or page numbers. "
          "Use the section headings in this report.")


def _source_root(path):
    from app.monthly_report_import import _package
    with _package(path) as package:
        return parse_xml(package.read("word/document.xml"))


def source_kind(path):
    if path is None:
        return ""
    try:
        return contents_kind(_source_root(path)) or "absent"
    except (OSError, ValueError, BadZipFile, etree.XMLSyntaxError):
        return "unknown"


def _text(node):
    return " ".join("".join("\t" if n.tag == qn("w:tab") else (n.text or "")
                            for n in node.iter() if n.tag in (qn("w:t"), qn("w:tab"))).split())


def _contents_heading(node):
    return node.tag == qn("w:p") and bool(re.fullmatch(r"(?:table of )?contents\s*:?", _text(node), re.I))


def _semantic(node):
    if node.tag != qn("w:p"):
        return False
    properties = node.find(qn("w:pPr"))
    if properties is None:
        return False
    level = properties.find(qn("w:outlineLvl"))
    if level is not None:
        return level.get(qn("w:val")) == "0"
    style = properties.find(qn("w:pStyle"))
    return style is not None and style.get(qn("w:val")) == "Heading1"


def _plain(node):
    if node.tag != qn("w:p") or any(True for _ in node.iter(qn("w:sectPr"))):
        return False
    return all(child.tag == qn("w:pPr") or
               (child.tag == qn("w:r") and all(n.tag in (qn("w:rPr"), qn("w:t"), qn("w:tab")) for n in child))
               for child in node)


def _entry(node):
    from app.monthly_report_import import _heading
    match = re.fullmatch(r"(.+?)\s*[.\s]+(\d+)", _text(node))
    if not match or node.tag != qn("w:p"):
        return False
    key = _heading(match.group(1).strip(" ."))
    return key not in (None, "unmatched")


def _old_rows(root):
    """Accept only an entire contiguous, ordinary contents block before a heading."""
    body = root.find(qn("w:body"))
    nodes = list(body)
    headings = [i for i, node in enumerate(nodes) if _contents_heading(node)]
    if len(headings) != 1:
        return None
    i = headings[0]
    end = next((j for j in range(i + 1, len(nodes)) if _semantic(nodes[j])), None)
    if end is None or end == i + 1:
        return None
    rows = nodes[i + 1:end]
    if not all(_entry(node) for node in rows):
        return None
    return tuple(_text(node) for node in rows)


def _replace_xml(raw, document):
    output = BytesIO()
    xml = etree.tostring(document.element, encoding="UTF-8", xml_declaration=True, standalone=True)
    with ZipFile(BytesIO(raw)) as original, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for info in original.infolist():
            target.writestr(info, xml if info.filename == "word/document.xml" else original.read(info.filename))
    return output.getvalue()


def _notice(document, before):
    paragraph = document.add_paragraph(NOTICE)
    paragraph.runs[0].bold = True
    before.addprevious(paragraph._p)


def prepare_imported_contents(source, raw, sections):
    """Use fresh app-owned references only after the native passive boundary.

    Complex or ambiguous layouts remain explicitly unverified. Never delete a
    source/manual paragraph merely because it happens to end in a number.
    """
    original = _source_root(source)
    kind = contents_kind(original) or "absent"
    document = Document(BytesIO(raw))
    body = document.element.body
    nodes = list(body)
    headings = [node for node in nodes if _contents_heading(node)]
    matching = []
    if kind != "absent" and len(headings) == 1:
        expected = _old_rows(original)
        actual = _old_rows(document.element)
        if expected is not None and actual == expected:
            i = nodes.index(headings[0])
            candidates = nodes[i + 1:i + 1 + len(expected)]
            if all(_plain(node) for node in candidates):
                matching = candidates
    targets = []
    for section in sections:
        title = f"{section.number}. {section.title}"
        candidates = [p for p in document.paragraphs if _semantic(p._p) and _plain(p._p) and _text(p._p) == title]
        if len(candidates) != 1:
            break
        targets.append(candidates[0])
    positions = [nodes.index(p._p) for p in targets]
    existing_names = {n.get(qn("w:name"), "") for n in body.iter(qn("w:bookmarkStart"))}
    existing_ids = {n.get(qn("w:id")) for tag in ("w:bookmarkStart", "w:bookmarkEnd") for n in body.iter(qn(tag))}
    proved = (bool(sections) and len(targets) == len(sections) and positions == sorted(set(positions))
              and not any(name.startswith(PREFIX) for name in existing_names)
              and not any(str(i + 1000) in existing_ids for i in range(len(sections)))
              and len({anchor_for(s.key) for s in sections}) == len(sections))
    if kind == "absent":
        if not proved or contents_kind(document.element):
            return raw
        before = targets[0]._p
        title = document.add_paragraph("Table of contents")
        before.addprevious(title._p)
    elif proved and matching and nodes.index(matching[-1]) < positions[0]:
        before = matching[0]
    else:
        before = headings[0] if len(headings) == 1 else nodes[0]
        _notice(document, before)
        for node in matching:
            body.remove(node)
        return _replace_xml(raw, document)
    for i, (section, target) in enumerate(zip(sections, targets)):
        add_entry(document, section)
        before.addprevious(document.paragraphs[-1]._p)
        mark_target(target, section.key, i)
        # Keep paragraph properties first in native headings.
        ppr = target._p.find(qn("w:pPr"))
        if ppr is not None:
            target._p.insert(0, ppr)
    for node in matching:
        body.remove(node)
    return _replace_xml(raw, document)


def has_generated_contents(raw):
    with ZipFile(BytesIO(raw)) as package:
        xml = package.read("word/document.xml")
    # Only prepare_imported_contents writes these field instructions; a body
    # without the prefix cannot hold one, so skip a second full parse.
    if ("PAGEREF " + PREFIX).encode() not in xml:
        return False
    root = parse_xml(xml)
    return any(n.get(qn("w:instr"), "").strip().startswith("PAGEREF " + PREFIX)
               for n in root.iter(qn("w:fldSimple")))


def withdraw_generated_contents(raw):
    """Remove only our new entries and bookmarks when final PDF proof fails."""
    document = Document(BytesIO(raw))
    body = document.element.body
    rows = [p._p for p in document.paragraphs if any(
        n.get(qn("w:instr"), "").strip().startswith("PAGEREF " + PREFIX)
        for n in p._p.iter(qn("w:fldSimple")))]
    if not rows:
        return raw
    _notice(document, rows[0])
    for row in rows:
        body.remove(row)
    ids = set()
    for start in list(body.iter(qn("w:bookmarkStart"))):
        if start.get(qn("w:name"), "").startswith(PREFIX):
            ids.add(start.get(qn("w:id")))
            start.getparent().remove(start)
    for end in list(body.iter(qn("w:bookmarkEnd"))):
        if end.get(qn("w:id")) in ids:
            end.getparent().remove(end)
    return _replace_xml(raw, document)
