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


# "Section 3: Monthly Scorecards", the form the native section numbering keeps
# current (#902): it renumbers these lines and the divider pages when a section
# is left out, and removes the left-out section's line.
SECTION_ENTRY = re.compile(r"\s*Section\s+\d+\s*:\s*\S", re.I)
# A page number at the end of a line, after a tab, dot leaders or an ellipsis.
PAGE_NUMBER_TAIL = re.compile(r"(?:\t|\.{2,}|…)\s*\d{1,4}\s*$")


def section_titles_only(root):
    """True when the contents name sections only and no line ends in a page number.

    Such a list has nothing that can go stale: its titles and order are the
    design's own, and its section numbers follow the report's sections. Any
    line anywhere that ends in a page number keeps the warning.
    """
    entries = 0
    for paragraph in root.iter(W + "p"):
        if paragraph.find(".//" + W + "p") is not None:
            continue  # Read a text box's own paragraphs, not their anchor.
        # A tab character is its own element in a run; keep it, so "Title<tab>3"
        # shows. A tab *stop* (pPr/tabs/tab) is layout, not text.
        text = "".join((node.text or "") if node.tag == W + "t"
                       else ("\t" if node.getparent().tag == W + "r" else "")
                       for node in paragraph.iter(W + "t", W + "tab"))
        if PAGE_NUMBER_TAIL.search(text):
            return False
        entries += bool(SECTION_ENTRY.match(text))
    return entries > 0


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
