"""Generated internal page references, verified against the finished PDF.

Only the application's source-free report shell calls these writers. Native
source fields and artwork remain under their existing preservation boundary.
No field instruction, bookmark or cached page value is taken from an upload.
"""
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from lxml import etree

from app.monthly_report_xml_parser import parse_xml
import pymupdf as fitz

PREFIX = "mr_contents_"
UNAVAILABLE = ("Contents page numbers could not be verified for these files. "
               "The Word contents use internal page references; check their updated values "
               "and the finished PDF before use.")


def anchor_for(key):
    return PREFIX + sha256(key.encode()).hexdigest()[:16]


def add_entry(document, section):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.tab_stops.add_tab_stop(Inches(6.9), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    anchor = anchor_for(section.key)
    link = OxmlElement("w:hyperlink")
    link.set(qn("w:anchor"), anchor)
    run, text = OxmlElement("w:r"), OxmlElement("w:t")
    text.text = f"{section.number}. {section.title}"
    run.append(text)
    link.append(run)
    paragraph._p.append(link)
    paragraph.add_run("\t")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), f" PAGEREF {anchor} \\h ")
    field.set(qn("w:dirty"), "true")
    run, text = OxmlElement("w:r"), OxmlElement("w:t")
    text.text = "?"  # Unknown is explicit until the renderer resolves it.
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


def mark_target(paragraph, key, index):
    start, end = OxmlElement("w:bookmarkStart"), OxmlElement("w:bookmarkEnd")
    start.set(qn("w:name"), anchor_for(key))
    start.set(qn("w:id"), str(index + 1000))
    end.set(qn("w:id"), str(index + 1000))
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _text(page, rectangle):
    box = fitz.Rect(rectangle)
    box.x0 -= .6; box.y0 -= .6; box.x1 += .6; box.y1 += .6
    # Writer's link rectangle includes the edge of an adjacent dot leader.
    return " ".join(page.get_textbox(box).split()).strip(" .")


def synchronize(docx, pdf, sections):
    """Fill only generated field caches after links, labels and pages agree.

    Writer already resolved the actual field values during the single PDF
    conversion. Copy those verified values back into the downloadable Word
    cache; changing a cache never changes its field or target. If a converter
    omits outlines/links or cannot prove a value, preserve Word and say so.
    """
    with ZipFile(BytesIO(docx)) as archive:
        xml = archive.read("word/document.xml")
        root = parse_xml(xml)
        generated = [field for field in root.iter(qn("w:fldSimple"))
                     if field.get(qn("w:instr"), "").strip().startswith("PAGEREF " + PREFIX)]
        if not generated:
            return docx, None
        try:
            if not pdf:
                return docx, UNAVAILABLE
            fields = {}
            for section in sections:
                anchor = anchor_for(section.key)
                expected = f"PAGEREF {anchor} \\h"
                matches = [field for field in generated if field.get(qn("w:instr"), "").strip() == expected]
                targets = [node for node in root.iter(qn("w:bookmarkStart")) if node.get(qn("w:name")) == anchor]
                links = [node for node in root.iter(qn("w:hyperlink")) if node.get(qn("w:anchor")) == anchor]
                if len(matches) != 1 or len(targets) != 1 or len(links) != 1:
                    return docx, UNAVAILABLE
                title = f"{section.number}. {section.title}"
                linked_title = " ".join("".join(text.text or "" for text in links[0].iter(qn("w:t"))).split())
                target_title = " ".join("".join(text.text or "" for text in targets[0].getparent().iter(qn("w:t"))).split())
                if linked_title != title or target_title != title:
                    return docx, UNAVAILABLE
                fields[title] = matches[0]
            if len(fields) != len(generated):
                return docx, UNAVAILABLE
            with fitz.open(stream=pdf, filetype="pdf") as rendered:
                outlines = rendered.get_toc()
                # An outline/link pair can agree on an obsolete page even when
                # the actual section heading moved after an attachment change.
                if [entry[1] for entry in outlines if entry[0] == 1] != list(fields):
                    return docx, UNAVAILABLE
                pages = {}
                for title in fields:
                    destinations = [entry[2] for entry in outlines if entry[1] == title]
                    if len(destinations) != 1 or not 1 <= destinations[0] <= len(rendered):
                        return docx, UNAVAILABLE
                    physical_text = " ".join(rendered[destinations[0] - 1].get_text(sort=True).split())
                    if title not in physical_text:
                        return docx, UNAVAILABLE
                    pages[title] = destinations[0]
                found = set()
                visual_order = []
                for page_index, page in enumerate(rendered):
                    links = [link for link in page.get_links() if link.get("kind") == fitz.LINK_GOTO]
                    for link in links:
                        label = _text(page, link["from"])
                        matches = [title for title in fields if title.strip(" .") == label]
                        if len(matches) != 1:
                            continue
                        title = matches[0]
                        number = pages[title]
                        if title in found or link.get("page") != number - 1:
                            return docx, UNAVAILABLE
                        center = (link["from"].y0 + link["from"].y1) / 2
                        page_fields = [candidate for candidate in links
                                       if candidate.get("page") == number - 1
                                       and abs((candidate["from"].y0 + candidate["from"].y1) / 2 - center) < 2
                                       and _text(page, candidate["from"]) == str(number)]
                        if len(page_fields) != 1:
                            return docx, UNAVAILABLE
                        found.add(title)
                        visual_order.append((page_index, center, title))
                if found != set(fields) or [item[2] for item in sorted(visual_order)] != list(fields):
                    return docx, UNAVAILABLE
            for title, field in fields.items():
                texts = list(field.iter(qn("w:t")))
                if len(texts) != 1:
                    return docx, UNAVAILABLE
                texts[0].text = str(pages[title])
            replacement = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            output = BytesIO()
            with ZipFile(output, "w", ZIP_DEFLATED) as target:
                for info in archive.infolist():
                    target.writestr(info, replacement if info.filename == "word/document.xml" else archive.read(info.filename))
            return output.getvalue(), ""
        except (ValueError, RuntimeError, fitz.FileDataError):
            return docx, UNAVAILABLE


def only_generated_cache_changed(before, after):
    """Prove a PDF retry changed cached decimal results, not report content."""
    try:
        with ZipFile(BytesIO(before)) as old, ZipFile(BytesIO(after)) as new:
            if old.namelist() != new.namelist():
                return False
            if any(old.read(name) != new.read(name) for name in old.namelist() if name != "word/document.xml"):
                return False
            roots = [parse_xml(archive.read("word/document.xml")) for archive in (old, new)]
            values = []
            for root in roots:
                cached = []
                for field in root.iter(qn("w:fldSimple")):
                    if not field.get(qn("w:instr"), "").strip().startswith("PAGEREF " + PREFIX):
                        continue
                    texts = list(field.iter(qn("w:t")))
                    if len(texts) != 1:
                        return False
                    cached.append(texts[0].text or "")
                    texts[0].text = ""
                values.append(cached)
            return (bool(values[0]) and values[0] != values[1]
                    and all(value == "?" or value.isdecimal() for value in values[0])
                    and all(value.isdecimal() for value in values[1])
                    and etree.tostring(roots[0], method="c14n") == etree.tostring(roots[1], method="c14n"))
    except (OSError, ValueError, BadZipFile, KeyError, etree.XMLSyntaxError):
        return False


def ensure_pdf_page_links(pdf, sections):
    """Repair only missing PDF number links when the destination is independently proven.

    LibreOffice can render the correct PAGEREF number while omitting its \h
    link. The physical section heading, outline, linked contents title and
    already-printed number must all agree. Do not rewrite a PDF's visible
    number, infer a destination, or touch pinned native report contents.
    """
    if not pdf or not sections:
        return pdf
    try:
        with fitz.open(stream=pdf, filetype="pdf") as rendered:
            expected = [f"{section.number}. {section.title}" for section in sections]
            outlines = [entry for entry in rendered.get_toc() if entry[0] == 1]
            if [entry[1] for entry in outlines] != expected:
                return pdf
            title_links = {title: [] for title in expected}
            for page_index, page in enumerate(rendered):
                for link in page.get_links():
                    if link.get("kind") != fitz.LINK_GOTO:
                        continue
                    title = _text(page, link["from"])
                    if title in title_links:
                        title_links[title].append((page_index, link))
            if any(len(title_links[title]) != 1 for title in expected):
                return pdf
            visible_order = sorted(
                (page_index, (link["from"].y0 + link["from"].y1) / 2, title)
                for title in expected for page_index, link in title_links[title]
            )
            if [title for _, _, title in visible_order] != expected:
                return pdf
            additions = []
            for title, (_, _, number) in zip(expected, outlines):
                if not 1 <= number <= len(rendered):
                    return pdf
                if title not in " ".join(rendered[number - 1].get_text(sort=True).split()):
                    return pdf
                if len(title_links[title]) != 1:
                    return pdf
                page_index, title_link = title_links[title][0]
                if title_link.get("page") != number - 1:
                    return pdf
                page = rendered[page_index]
                title_rectangle = title_link["from"]
                title_mid = (title_rectangle.y0 + title_rectangle.y1) / 2
                candidates = [rectangle for rectangle in page.search_for(str(number))
                              if rectangle.x0 > title_rectangle.x1 + 1
                              and abs((rectangle.y0 + rectangle.y1) / 2 - title_mid) < 3
                              and _text(page, rectangle) == str(number)]
                if len(candidates) != 1:
                    return pdf
                rectangle = candidates[0]
                # Never place a valid link over an existing wrong/foreign link.
                occupied = [link for link in page.get_links()
                            if link["from"].intersects(rectangle)
                            and (link["from"] & rectangle).get_area() >= .5 * rectangle.get_area()]
                if occupied:
                    if (len(occupied) != 1 or occupied[0].get("kind") != fitz.LINK_GOTO
                            or occupied[0].get("page") != number - 1):
                        return pdf
                    continue
                additions.append((page_index, rectangle, number - 1,
                                  title_link.get("to") or fitz.Point(72, 72)))
            for page_index, rectangle, target_index, target_position in additions:
                rendered[page_index].insert_link({
                    "kind": fitz.LINK_GOTO, "from": rectangle,
                    "page": target_index, "to": target_position,
                })
            return rendered.tobytes() if additions else pdf
    except (ValueError, RuntimeError, fitz.FileDataError):
        return pdf
