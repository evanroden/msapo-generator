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
# A page number on its own, or ending a line: digits or a Roman numeral.
PAGE_NUMBER = r"(?:\d{1,4}|[ivxlcdm]{1,7})"
NUMBER_ONLY = re.compile(r"\s*" + PAGE_NUMBER + r"\s*", re.I)
NUMBER_AT_END = re.compile(r"(?:^|[\s.\u2026])" + PAGE_NUMBER + r"$", re.I)


def _own_text(paragraph):
    """A paragraph's own text, with tab characters; not its text boxes' text.

    A tab stop (pPr/tabs/tab) is layout, not text, and a text box's paragraphs
    are read in their own turn.
    """
    parts = []
    for node in paragraph.iter(W + "t", W + "tab"):
        owner = node.getparent()
        while owner is not None and owner.tag != W + "p":
            owner = owner.getparent()
        if owner is not paragraph:
            continue
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.getparent().tag == W + "r":
            parts.append("\t")
    return "".join(parts)


def _page_field(paragraph):
    instructions = [node.get(W + "instr", "") for node in paragraph.iter(W + "fldSimple")]
    instructions += [node.text or "" for node in paragraph.iter(W + "instrText")]
    return any(re.search(r"\bPAGE(?:REF)?\b", value, re.I) for value in instructions)


def section_titles_only(root):
    """True only for a contents list positively identified as section titles.

    That is: the contents heading, then nothing but "Section N: Title" lines
    (blank lines allowed), each title a report section the importer
    recognizes, with nothing after the title, none of them in a table and no
    page field among them; and the first line after the list is not a page
    number on its own. Such a list has nothing that can go stale: its titles
    and order are the design's own and its numbers follow the report's
    sections. Anything else keeps the warning (Codex on #1144: a page number
    in another table cell, after a space or as a Roman numeral).
    """
    from app.monthly_report_import import _heading

    # A text box's legacy Fallback repeats its Choice; read each text once.
    paragraphs = [paragraph for paragraph in root.iter(W + "p")
                  if not any(ancestor.tag == MC + "Fallback" for ancestor in paragraph.iterancestors())]
    texts = [_own_text(paragraph) for paragraph in paragraphs]
    heading = next((index for index, text in enumerate(texts) if CONTENTS_HEADING.fullmatch(text)
                    and text.strip()), None)
    if heading is None:
        return False
    entries = 0
    for paragraph, text in zip(paragraphs[heading + 1:], texts[heading + 1:]):
        if _page_field(paragraph):
            return False
        if not text.strip():
            continue
        match = SECTION_ENTRY.fullmatch(text)
        if match is None:
            # The list has ended. A page number listed apart from the titles,
            # e.g. in a frame after them, keeps the warning.
            return entries > 0 and not NUMBER_ONLY.fullmatch(text)
        title = match.group(1)
        in_table = any(ancestor.tag == W + "tc" for ancestor in paragraph.iterancestors())
        if (in_table or NUMBER_AT_END.search(title)
                or _heading(title) in (None, "unmatched")):
            return False
        entries += 1
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
