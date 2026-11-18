"""A77: source-free contents crosswalk, independent of LibreOffice/Word.

Synthetic physical PDFs are intentionally 2, 15, or 40 pages. We verify the
rendered outline, visible contents links, physical section starts and Word
caches instead of trusting matching outline/link metadata in isolation.
"""
from io import BytesIO
from types import SimpleNamespace
from hashlib import sha256

from docx import Document
from docx.oxml.ns import qn
import pymupdf as fitz
import pytest

from app.monthly_report_contents_pagination import (
    add_entry, anchor_for, mark_target, synchronize,
)


def _sections(count):
    return tuple(SimpleNamespace(
        key=f"synthetic-section-{index}", number=str(index + 1),
        title=f"Synthetic Section {index + 1}",
    ) for index in range(count))


def _word(sections):
    document = Document()
    document.add_paragraph("Table of contents")
    for section in sections:
        add_entry(document, section)
    for index, section in enumerate(sections):
        mark_target(document.add_heading(f"{section.number}. {section.title}", 1),
                    section.key, index)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def _pdf(sections, destinations, size, *, missing_heading=False,
         reversed_outline=False, reversed_visible=False):
    assert len(sections) == len(destinations)
    report = fitz.open()
    for _ in range(size):
        report.new_page()
    contents = report[0]
    contents.insert_text((72, 70), "Table of contents", fontsize=18)
    visual = list(zip(sections, destinations))
    if reversed_visible:
        visual.reverse()
    for index, (section, destination) in enumerate(visual):
        label = f"{section.number}. {section.title}"
        y = 125 + index * 40
        contents.insert_text((72, y), label, fontsize=11)
        contents.insert_text((500, y), str(destination + 1), fontsize=11)
        title_rect = contents.search_for(label)[0]
        number_rect = next(rect for rect in contents.search_for(str(destination + 1))
                           if rect.x0 > 400)
        for rect in (title_rect, number_rect):
            contents.insert_link({"kind": fitz.LINK_GOTO, "from": rect, "page": destination,
                                  "to": fitz.Point(72, 70)})
    for index, (section, destination) in enumerate(zip(sections, destinations)):
        if missing_heading and index == len(sections) - 1:
            continue
        report[destination].insert_text((72, 110),
                                        f"{section.number}. {section.title}", fontsize=14)
    outline = [[1, f"{section.number}. {section.title}", destination + 1]
               for section, destination in zip(sections, destinations)]
    if reversed_outline:
        outline.reverse()
    report.set_toc(outline)
    raw = report.tobytes()
    report.close()
    return raw


def _cache(raw):
    doc = Document(BytesIO(raw))
    return {
        field.get(qn("w:instr")).strip():
        "".join(item.text or "" for item in field.iter(qn("w:t")))
        for field in doc.element.iter(qn("w:fldSimple"))
        if (field.get(qn("w:instr")) or "").strip().startswith("PAGEREF mr_contents_")
    }


@pytest.mark.parametrize("size,destinations", [
    (2, (1,)), (15, (1, 14)), (40, (1, 39)),
])
def test_page_count_crosswalk_has_real_boundaries_links_and_word_cache(size, destinations):
    sections = _sections(len(destinations))
    word = _word(sections)
    pdf = _pdf(sections, destinations, size)
    verified, notice = synchronize(word, pdf, sections)
    assert notice == ""
    assert list(_cache(verified).values()) == [str(i + 1) for i in destinations]
    with fitz.open(stream=pdf, filetype="pdf") as report:
        assert len(report) == size
        assert [entry[1:] for entry in report.get_toc()] == [
            [f"{section.number}. {section.title}", page + 1]
            for section, page in zip(sections, destinations)
        ]
        links = [link for link in report[0].get_links() if link["kind"] == fitz.LINK_GOTO]
        assert len(links) == 2 * len(sections)
        for section, destination in zip(sections, destinations):
            title = f"{section.number}. {section.title}"
            assert title in report[destination].get_text()
            assert sum(link["page"] == destination for link in links) == 2
            assert _cache(verified)[f"PAGEREF {anchor_for(section.key)} \\h"] == str(destination + 1)
    assert sha256(word).hexdigest() != sha256(verified).hexdigest()
    assert synchronize(verified, pdf, sections)[1] == ""


@pytest.mark.parametrize("size,destinations", [(15, (1, 14)), (40, (1, 39))])
@pytest.mark.parametrize("damage", ["missing_heading", "reversed_outline", "reversed_visible"])
def test_corrupted_physical_or_order_evidence_does_not_publish_cached_numbers(size, destinations, damage):
    sections = _sections(len(destinations))
    word = _word(sections)
    pdf = _pdf(sections, destinations, size, **{damage: True})
    unchanged, notice = synchronize(word, pdf, sections)
    assert unchanged == word
    assert "could not be verified" in notice
    assert set(_cache(unchanged).values()) == {"?"}


@pytest.mark.parametrize("damage", ["linked_title", "bookmark_heading"])
def test_word_contents_and_bookmark_must_match_selected_section_title(damage):
    sections = _sections(1)
    word = Document(BytesIO(_word(sections)))
    if damage == "linked_title":
        link = next(word.element.iter(qn("w:hyperlink")))
        next(link.iter(qn("w:t"))).text = "1. Obsolete section label"
    else:
        target = next(word.element.iter(qn("w:bookmarkStart")))
        next(target.getparent().iter(qn("w:t"))).text = "1. Obsolete section heading"
    output = BytesIO()
    word.save(output)
    stale = output.getvalue()
    pdf = _pdf(sections, (1,), 2)
    unchanged, notice = synchronize(stale, pdf, sections)
    assert unchanged == stale
    assert "could not be verified" in notice


def test_attachment_rerender_replaces_old_cache_and_rejects_stale_output():
    sections = _sections(2)
    original = _word(sections)
    early = _pdf(sections, (1, 14), 15)
    shifted = _pdf(sections, (4, 39), 40)
    word_early, notice = synchronize(original, early, sections)
    assert notice == "" and list(_cache(word_early).values()) == ["2", "15"]
    word_final, notice = synchronize(word_early, shifted, sections)
    assert notice == "" and list(_cache(word_final).values()) == ["5", "40"]
    assert word_final != word_early
    assert synchronize(word_final, shifted, sections)[1] == ""
    assert synchronize(word_final, None, sections) == (
        word_final, synchronize(word_final, None, sections)[1])
    assert "could not be verified" in synchronize(word_final, None, sections)[1]


def test_missing_or_malformed_pdf_never_fills_unknown_page_numbers():
    sections = _sections(1)
    word = _word(sections)
    for invalid in (None, b"not-a-pdf"):
        unchanged, notice = synchronize(word, invalid, sections)
        assert unchanged == word
        assert "could not be verified" in notice
        assert set(_cache(unchanged).values()) == {"?"}
