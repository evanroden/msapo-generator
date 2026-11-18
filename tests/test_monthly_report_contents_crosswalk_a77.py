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
    add_entry, anchor_for, ensure_pdf_page_links, mark_target, synchronize, only_generated_cache_changed,
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
    unavailable, notice = synchronize(word_final, None, sections)
    assert unavailable == word_final
    assert "could not be verified" in notice
    # An earlier saved section order cannot certify a newer PDF's contents.
    reordered, notice = synchronize(original, shifted, tuple(reversed(sections)))
    assert reordered == original
    assert "could not be verified" in notice


def test_missing_or_malformed_pdf_never_fills_unknown_page_numbers():
    sections = _sections(1)
    word = _word(sections)
    for invalid in (None, b"not-a-pdf"):
        unchanged, notice = synchronize(word, invalid, sections)
        assert unchanged == word
        assert "could not be verified" in notice
        assert set(_cache(unchanged).values()) == {"?"}


@pytest.mark.parametrize("size", [2, 15, 40])
def test_real_writer_pdf_crosswalk_repairs_only_missing_number_links(tmp_path, size):
    """Exercise real LibreOffice field rendering, not only injected PDF metadata."""
    from tests.conftest import libreoffice_can_convert
    if not libreoffice_can_convert():
        pytest.skip("LibreOffice Writer and Calc filters are unavailable")
    from app import pdf_converter

    sections = _sections(1 if size == 2 else 2)
    document = Document()
    document.add_paragraph("Table of contents")
    for section in sections:
        add_entry(document, section)
    document.add_page_break()
    mark_target(document.add_heading(f"1. {sections[0].title}", 1), sections[0].key, 0)
    if len(sections) > 1:
        # One explicit break per synthetic attachment page; last heading starts
        # on the 15th or 40th page, respectively.
        for index in range(size - 3):
            document.add_page_break()
            document.add_paragraph(f"Synthetic attachment continuation {index + 1}")
        document.add_page_break()
        mark_target(document.add_heading(f"2. {sections[1].title}", 1), sections[1].key, 1)
    path = tmp_path / f"a77-{size}.docx"
    document.save(path)
    word_before = path.read_bytes()
    original_hash = sha256(word_before).hexdigest()

    converted = pdf_converter.convert_to_pdf(path, lossless_images=True)
    try:
        pdf_before = converted.read_bytes()
    finally:
        converted.unlink(missing_ok=True)
    expected_pages = (2,) if size == 2 else (2, size)
    with fitz.open(stream=pdf_before, filetype="pdf") as report:
        assert len(report) == size
        assert [entry[2] for entry in report.get_toc()] == list(expected_pages)
        for section, page in zip(sections, expected_pages):
            assert f"{section.number}. {section.title}" in report[page - 1].get_text()

    repaired_pdf = ensure_pdf_page_links(pdf_before, sections)
    word_after, notice = synchronize(word_before, repaired_pdf, sections)
    assert notice == ""
    assert list(_cache(word_after).values()) == list(map(str, expected_pages))
    assert only_generated_cache_changed(word_before, word_after)
    assert sha256(path.read_bytes()).hexdigest() == original_hash  # source untouched
    assert ensure_pdf_page_links(repaired_pdf, sections) == repaired_pdf  # no extra PDF rewrite
    with fitz.open(stream=repaired_pdf, filetype="pdf") as report:
        assert len(report) == size
        links = [link for link in report[0].get_links() if link["kind"] == fitz.LINK_GOTO]
        assert len(links) == 2 * len(sections)
        for page in expected_pages:
            assert sum(link["page"] == page - 1 for link in links) == 2


@pytest.mark.parametrize("damage", ["missing_heading", "reversed_outline", "reversed_visible"])
def test_pdf_page_link_repair_does_not_alter_ambiguous_or_false_contents(damage):
    sections = _sections(2)
    corrupted = _pdf(sections, (1, 14), 15, **{damage: True})
    assert ensure_pdf_page_links(corrupted, sections) == corrupted
    assert ensure_pdf_page_links(None, sections) is None
    assert ensure_pdf_page_links(b"not-a-pdf", sections) == b"not-a-pdf"


def test_pdf_repair_keeps_reversed_visible_contents_unchanged_when_number_links_missing():
    sections = _sections(2)
    original = _pdf(sections, (1, 14), 15, reversed_visible=True)
    with fitz.open(stream=original, filetype="pdf") as report:
        contents = report[0]
        for link in list(contents.get_links()):
            if contents.get_textbox(link["from"]).strip().isdecimal():
                contents.delete_link(link)
        without_number_links = report.tobytes()
    with fitz.open(stream=without_number_links, filetype="pdf") as report:
        assert len(report[0].get_links()) == 2  # Title-only links, as with Writer.
    assert ensure_pdf_page_links(without_number_links, sections) == without_number_links
    raw = _word(sections)
    unchanged, notice = synchronize(raw, without_number_links, sections)
    assert unchanged == raw and "could not be verified" in notice
