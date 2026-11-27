"""Describe native contents limits without changing sources or enabling fields.

The passive native clone deliberately flattens TOC fields. Neither that clone
nor PDF conversion proves a fresh index. Report this on the finished package
instead of letting a cached source index appear to have been recalculated.
"""
import re
from zipfile import BadZipFile

from lxml import etree

from app.monthly_report_xml_parser import parse_xml

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


def contents_kind(root):
    """Recognize actual TOC instructions separately from literal contents.

    Word can split a complex instruction across runs or paragraphs. Only its
    instruction region counts; nested PAGE/PAGEREF fields and cached result
    text cannot accidentally become part of that command.
    """
    stack = []
    for node in root.iter():
        if node.tag == W + "fldSimple":
            if re.match(r"^\s*TOC(?:\s|$)", node.get(W + "instr", ""), re.I):
                return "field"
        elif node.tag == W + "fldChar":
            kind = node.get(W + "fldCharType")
            if kind == "begin":
                stack.append([[], False])
            elif stack and kind in {"separate", "end"}:
                if re.match(r"^\s*TOC(?:\s|$)", "".join(stack[-1][0]), re.I):
                    return "field"
                if kind == "end":
                    stack.pop()
                else:
                    stack[-1][1] = True
        elif node.tag == W + "instrText" and stack and not stack[-1][1]:
            stack[-1][0].append(node.text or "")

    for paragraph in root.iter(W + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(W + "t"))
        # A prose reference such as "See the table of contents" is not a TOC.
        if re.fullmatch(r"(?:table\s*of\s*)?contents\s*:?[\s.]*", text.strip(), re.I):
            return "static"
        style = paragraph.find(W + "pPr/" + W + "pStyle")
        if style is not None and re.fullmatch(r"TOC(?:Heading|[1-9])", style.get(W + "val", ""), re.I):
            return "static"
    return ""


# The contents heading itself, as contents_kind() recognizes a static list.
CONTENTS_HEADING = re.compile(r"\s*(?:table\s*of\s*)?contents\s*:?[\s.]*", re.I)
# "Section 3: Monthly Scorecards", the form the native section numbering keeps
# current (#902): it renumbers these lines and the divider pages when a section
# is left out, and removes the left-out section's line.
SECTION_ENTRY = re.compile(r"\s*Section\s+\d+\s*:\s*(\S.*?)\s*", re.I)
# A title as a section's own name is written: words, spaces, "/", "&", dashes,
# apostrophes and commas. No digit, leader or symbol can hide in it.
TITLE = re.compile(r"[A-Za-z][A-Za-z /&'\u2019,\u2013\u2014-]*")
# A page number ending a title after a space: digits or a Roman numeral.
NUMBER_AT_END = re.compile(r"(?:^|[\s.\u2026])(?:\d{1,4}|[ivxlcdm]{1,7})$", re.I)
# A section whose type is absent starts on a new page, as in Word.
PAGE_STARTS = {"nextPage", "oddPage", "evenPage"}


def _in_order(node):
    """A node's content in document order, each text box paragraph in its place.

    A text box's paragraphs are read in their own turn, so their runs are not
    returned with the paragraph around them. Legacy Fallback copies repeat
    their Choice and are never read.
    """
    for child in node:
        if not isinstance(child.tag, str) or child.tag == MC + "Fallback":
            continue
        yield child
        yield from (_boxes(child) if child.tag == W + "p" else _in_order(child))


def _boxes(node):
    """Every paragraph inside a node, in order, each text once."""
    for child in node:
        if not isinstance(child.tag, str) or child.tag == MC + "Fallback":
            continue
        if child.tag == W + "p":
            yield child
        yield from _boxes(child)


def _character(node):
    """What a node of a run shows, or None for anything that is not text."""
    if node.tag == W + "t":
        return node.text or ""
    if node.getparent().tag != W + "r":
        return None  # A tab stop (pPr/tabs/tab) is layout, not text.
    if node.tag in (W + "tab", W + "ptab"):
        return "\t"
    if node.tag in (W + "br", W + "cr"):
        return "\n"
    if node.tag == W + "noBreakHyphen":
        return "-"
    if node.tag == W + "sym":
        return "\ufffd"  # A symbol glyph: never part of a title.
    return None


def _own_text(paragraph):
    """A paragraph's own text, with tabs and line breaks; not its text boxes' text."""
    return "".join(value for node in _in_order(paragraph) if node.tag != W + "p"
                   for value in [_character(node)] if value is not None)


def _page_field(paragraph):
    instructions = [node.get(W + "instr", "") for node in paragraph.iter(W + "fldSimple")]
    instructions += [node.text or "" for node in paragraph.iter(W + "instrText")]
    return any(re.search(r"\bPAGE(?:REF)?\b", value, re.I) for value in instructions)


def _starts_page(properties):
    kind = properties.find(W + "type")
    return (kind.get(W + "val") if kind is not None else "nextPage") in PAGE_STARTS


def _current_section(properties):
    """The section properties in force, not a tracked change's old copy."""
    parent = properties.getparent()
    if parent.tag == W + "body":
        return True
    paragraph = parent.getparent()
    return (parent.tag == W + "pPr" and paragraph is not None and paragraph.tag == W + "p"
            and not any(ancestor.tag in (W + "txbxContent", W + "tc") for ancestor in paragraph.iterancestors()))


def _deleted(node, paragraph):
    """A page break removed with tracked changes no longer breaks the page."""
    while node is not None and node is not paragraph:
        if node.tag in (W + "del", W + "moveFrom"):
            return True
        node = node.getparent()
    return False


def _pages(body):
    """The body's text page by page: [(paragraph, text), ...] for each page.

    A page starts at a page break, at a paragraph set to start a page and
    after a section break whose next section starts a page. Text that flows
    on to a further page stays with its page here, and a break this does not
    read (in a table, or a content control) joins two pages: either only adds
    lines to the check, and can never take one away from it.
    """
    marks = [node for node in body.iter(W + "sectPr") if _current_section(node)]
    section_ends = {current.getparent().getparent() for current, following in zip(marks, marks[1:])
                    if current.getparent().tag == W + "pPr"
                    and current.getparent().getparent().getparent().tag == W + "body"
                    and _starts_page(following)}
    pages, page = [], []
    for block in body:
        if not isinstance(block.tag, str) or block.tag == W + "sectPr":
            continue
        if block.tag != W + "p":
            page += [(paragraph, _own_text(paragraph)) for paragraph in _boxes(block)]
            continue
        before = block.find(W + "pPr/" + W + "pageBreakBefore")
        if before is not None and before.get(W + "val", "true").lower() not in {"0", "false", "off"}:
            pages.append(page)
            page = []
        text = []
        for node in _in_order(block):
            if node.tag == W + "p":
                page.append((node, _own_text(node)))  # A text box on this page.
            elif node.tag == W + "br" and node.get(W + "type") == "page" and not _deleted(node, block):
                page.append((block, "".join(text)))
                pages.append(page)
                page, text = [], []
            else:
                value = _character(node)
                if value is not None:
                    text.append(value)
        page.append((block, "".join(text)))
        if block in section_ends:
            pages.append(page)
            page = []
    pages.append(page)
    return pages


def _furniture(line):
    """The native contents page's own lines that are not contents entries.

    The closed patterns the native design recognizes on that page: the
    brand line, the confidentiality notice and the company address.
    """
    from app.monthly_report_native_design import ADDRESS_LINE, CONTENTS_NOTICE, REPORT_NOTICE
    line = " ".join(line.split())
    return line == "ENFRA" or line in (CONTENTS_NOTICE, REPORT_NOTICE) or ADDRESS_LINE.fullmatch(line) is not None


def _toc_style(paragraph):
    style = paragraph.find(W + "pPr/" + W + "pStyle")
    return style is not None and re.fullmatch(r"TOC(?:Heading|[1-9])", style.get(W + "val", ""), re.I) is not None


def section_titles_only(root):
    """True only for a contents page positively identified as section titles.

    The contents page is the page that holds the contents heading, from the
    page break or section break before it to the one after it. Every line on
    it must be the heading, a "Section N: Title" line or the native page's
    brand line, notice or address. Each title must be a report section the
    importer recognizes, written as a name with nothing after it, and no line
    may sit in a table or carry a page field. No paragraph styled as a
    contents entry may appear on any other page. Such a page has nothing that
    can go stale: its titles and order are the design's own and its numbers
    follow the report's sections (#902). Anything else keeps the warning
    (Codex on #1144: a page number in another table cell, after a space or as
    a Roman numeral, and a further entry such as "Monthly Activity Summary"
    with its page number after the section lines).
    """
    from app.monthly_report_import import _heading

    body = root if root.tag == W + "body" else root.find(W + "body")
    if body is None:
        return False
    checked = False
    for page in _pages(body):
        if not any(CONTENTS_HEADING.fullmatch(value) for _, text in page for value in (text, *text.split("\n"))):
            if any(_toc_style(paragraph) for paragraph, _ in page):
                return False
            continue
        entries = 0
        for paragraph, text in page:
            if _page_field(paragraph):
                return False
            if CONTENTS_HEADING.fullmatch(text):
                continue  # The heading, even across a line break.
            in_table = any(ancestor.tag == W + "tc" for ancestor in paragraph.iterancestors())
            for line in text.split("\n"):
                if not line.strip() or CONTENTS_HEADING.fullmatch(line) or _furniture(line):
                    continue
                match = SECTION_ENTRY.fullmatch(line)
                if (match is None or in_table or NUMBER_AT_END.search(match.group(1))
                        or not TITLE.fullmatch(" ".join(match.group(1).split()))
                        or _heading(match.group(1)) in (None, "unmatched")):
                    return False
                entries += 1
        if not entries:
            return False
        checked = True
    return checked


def contents_notice_for(profile):
    """Read the pinned source once per generation; retain only a short notice."""
    from app.monthly_report_designs import source_for
    from app.monthly_report_import import _package

    try:
        source = source_for(profile)
        if source is None:
            return ""  # The generated fallback has a current title-only list.
        with _package(source) as archive:
            root = parse_xml(archive.read("word/document.xml"))
        kind = contents_kind(root)
        if kind == "static" and section_titles_only(root):
            return ""  # Owner (27 Nov): no warning where nothing can be stale.
    except (OSError, ValueError, BadZipFile, etree.XMLSyntaxError):
        # Finished files must not disappear if their original becomes
        # unavailable after assembly. This does not bypass assembly's checks.
        return ("Contents verification is unavailable for these files. Check the contents "
                "titles, order and page numbers in the downloaded Word and PDF before use.")
    if not kind:
        return ""
    source_description = ("The selected design uses a Word contents field. Automatic contents updating is unavailable. "
                          if kind == "field" else "The selected design uses a static contents list. ")
    return (source_description + "Contents titles, order and page numbers are not recalculated "
            "for this report. Check and correct the contents in a copy of the finished Word file, "
            "then verify the resulting PDF before use.")
