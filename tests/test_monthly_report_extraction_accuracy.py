"""Synthetic Word/PDF text-fidelity regressions: what the reader sees is what is extracted.

Only constructed documents; no client report content.
"""
from docx import Document
from docx.oxml import parse_xml
import pymupdf as fitz

from app import monthly_report_import as importer
from app import monthly_report_sources as sources
from app import ocr
from app.extracted_text import normalize_extracted_text, word_symbol_text
from app.monthly_report_model import synthetic_profiles

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _run(text):
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def _docx(tmp_path, paragraphs, *, header=None):
    document = Document()
    document.add_heading("2 Monthly Activity Summary", 1)
    body = document.element.body
    for inner in paragraphs:
        body.insert(len(body) - 1, parse_xml(f"<w:p {W_NS}>{inner}</w:p>"))
    if header is not None:
        target = document.sections[0].header._element
        for child in list(target):
            target.remove(child)
        target.append(parse_xml(f"<w:p {W_NS}>{header}</w:p>"))
    path = tmp_path / "synthetic.docx"
    document.save(path)
    return importer.inspect_docx(path)


def _texts(inspection, part="word/document.xml"):
    return [item.text for item in inspection.items if item.kind == "text" and item.part.startswith(part)]


def test_positional_tab_separates_header_words(tmp_path):
    inspection = _docx(tmp_path, [_run("Body")], header=(
        _run("Synthetic Site") + '<w:r><w:ptab w:relativeTo="margin" w:alignment="right" w:leader="none"/></w:r>'
        + _run("Monthly Review")))
    assert _texts(inspection, "word/header") == ["Synthetic Site Monthly Review"]


def test_non_breaking_hyphen_and_symbol_font_characters_are_kept(tmp_path):
    inspection = _docx(tmp_path, [
        _run("24") + "<w:r><w:noBreakHyphen/></w:r>" + _run("hour coverage"),
        _run("Setpoint 44") + '<w:r><w:sym w:font="Symbol" w:char="F0B0"/></w:r>' + _run("F ")
        + '<w:r><w:sym w:font="Symbol" w:char="F0B1"/></w:r>' + _run("2"),
        '<w:r><w:sym w:font="Wingdings" w:char="F0FE"/></w:r>' + _run(" Filters replaced"),
    ])
    texts = _texts(inspection)
    assert "24-hour coverage" in texts
    assert "Setpoint 44°F ±2" in texts
    assert "☑ Filters replaced" in texts


def test_placeholder_prompts_are_not_extracted_and_ids_stay_put(tmp_path):
    def placeholder(prompt):
        return ('<w:sdt><w:sdtPr><w:showingPlcHdr/></w:sdtPr><w:sdtContent>'
                + _run(prompt) + "</w:sdtContent></w:sdt>")
    inspection = _docx(tmp_path, [
        _run("Visible note."),
        placeholder("Enter the inspection date."),
        _run("Reviewer: ") + placeholder("Click or tap here to enter text."),
        _run("Closing line."),
    ])
    offered = [i.text for i in inspection.items if i.kind == "text" and i.note != importer._PLACEHOLDER_NOTE]
    assert "Visible note." in offered and "Reviewer:" in offered
    assert not any("Click or tap" in t or "Enter the" in t for t in offered)
    # The prompt-only paragraph stays in the inventory, unsuggested, so item
    # IDs, item count and saved per-item texts match a filled-in document.
    prompt = next(i for i in inspection.items if i.note == importer._PLACEHOLDER_NOTE)
    assert prompt.suggested_slot == ""
    closing = next(i for i in inspection.items if i.text == "Closing line.")
    filled = _docx(tmp_path, [
        _run("Visible note."), _run("2026-10-14"), _run("Reviewer: x"), _run("Closing line."),
    ])
    assert closing.id == next(i for i in filled.items if i.text == "Closing line.").id
    assert len(inspection.items) == len(filled.items)


def test_word_symbol_table_never_invents_unknown_dingbats():
    assert word_symbol_text("Symbol", "F0B0") == "°"
    assert word_symbol_text("symbol", "00B1") == "±"
    assert word_symbol_text("Wingdings", "F0FC") == "✓"
    assert word_symbol_text("Wingdings", "F041") == ""  # no reliable text equivalent
    assert word_symbol_text("Times New Roman", "00B5") == "µ"
    assert word_symbol_text("Arial", "F020") == ""  # private-use code in a text font
    assert word_symbol_text("Symbol", "zz") == ""


def test_normalizer_only_changes_display_equivalent_characters():
    assert normalize_extracted_text("eﬃcient ﬂow 24‑hour a​b﻿") == "efficient flow 24-hour ab"
    assert normalize_extracted_text("44 °F ± 2 µm ft² 2026–2027 — ✓") == "44 °F ± 2 µm ft² 2026–2027 — ✓"


def _ligature_pdf():
    with fitz.open() as document:
        page = document.new_page()
        page.insert_font(fontname="dv", fontfile=FONT)
        page.insert_text((50, 60), "Actions: Replaced eﬃcient ﬁlter on 24‑hour unit.",
                         fontname="dv", fontfile=FONT)
        return document.tobytes()


def test_pdf_intake_reads_ligatures_as_plain_letters_and_keeps_passage_proof(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    content, _ = sources.ingest(synthetic_profiles()[0], "synthetic-ligature.pdf", _ligature_pdf())
    text = content.source.page_texts[0]
    assert "Replaced efficient filter on 24-hour unit." in text
    # Native passage geometry still tiles the normalized page text exactly.
    assert content.source.pdf_text_blocks
    number, start, end, _ = content.source.pdf_text_blocks[0]
    assert number == 1 and text[start:end].startswith("Actions: Replaced efficient filter")


def test_purchase_order_pdf_text_reads_ligatures_as_plain_letters():
    assert "Replaced efficient filter on 24-hour unit." in ocr.extract_text_from_pdf(_ligature_pdf())


def test_ligature_labels_in_side_by_side_columns_still_need_page_review():
    from app.monthly_report_vendor_passages import block_spans
    with fitz.open() as pdf:
        page = pdf.new_page(width=760, height=620)
        page.insert_font(fontname="dv", fontfile=FONT)
        left = "ﬁndings: The demo filter was worn.\nNext visit in spring."
        right = "ﬁndings: The demo fan stayed offline.\nParts are on order."
        assert page.insert_textbox(fitz.Rect(35, 135, 315, 355), left, fontsize=10, fontname="dv") >= 0
        assert page.insert_textbox(fitz.Rect(425, 135, 725, 355), right, fontsize=10, fontname="dv") >= 0
        assert any("ﬁndings" in block[4] for block in page.get_text("blocks"))
        text = normalize_extracted_text(page.get_text()).strip()
        assert "findings:" in text
        ambiguous = set()
        assert block_spans(page, text, 1, ambiguous_pages=ambiguous) == ()
        assert ambiguous == {1}


def _paragraph(inner):
    return parse_xml(f"<w:p {W_NS}>{inner}</w:p>")


def test_rewriting_imported_text_does_not_repeat_symbols_or_hyphens():
    from app.monthly_report_native_layout import _set_reviewed_footer_text, _set_text
    inner = (_run("Limit 44") + '<w:r><w:sym w:font="Symbol" w:char="F0B0"/></w:r>' + _run("F, 24")
             + "<w:r><w:noBreakHyphen/></w:r>" + _run("hour"))
    for writer in (_set_text, _set_reviewed_footer_text):
        paragraph = _paragraph(inner)
        value = importer._text(paragraph)
        assert value == "Limit 44°F, 24-hour"
        writer(paragraph, value)
        assert importer._text(paragraph) == value
        paragraph = _paragraph(inner)
        writer(paragraph, "Limit 45°F, 24-hour")
        assert importer._text(paragraph) == "Limit 45°F, 24-hour"
    # A symbol with no known text equivalent is never imported, so it stays.
    paragraph = _paragraph('<w:r><w:sym w:font="Wingdings" w:char="F041"/></w:r>' + _run(" Note"))
    _set_text(paragraph, "Revised note")
    assert paragraph.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}sym") is not None


def test_text_written_into_a_placeholder_survives_reimport():
    from app.monthly_report_native_layout import _set_text
    paragraph = _paragraph('<w:sdt><w:sdtPr><w:showingPlcHdr/></w:sdtPr><w:sdtContent>'
                           + _run("Click or tap here to enter text.") + "</w:sdtContent></w:sdt>"
                           + _run("Prepared by: Alice"))
    assert importer._text(paragraph) == "Prepared by: Alice"
    _set_text(paragraph, "Prepared by: Bob")
    assert importer._text(paragraph) == "Prepared by: Bob"


def test_a_symbol_only_paragraph_adds_no_item_so_saved_inventories_still_match(tmp_path):
    checkbox = '<w:r><w:sym w:font="Wingdings" w:char="F0FE"/></w:r>'
    hyphen = "<w:r><w:noBreakHyphen/></w:r>"
    inspection = _docx(tmp_path, [_run("Before."), checkbox, hyphen, _run("After.")])
    plain = _docx(tmp_path, [_run("Before."), "", "", _run("After.")])
    assert len(inspection.items) == len(plain.items)
    assert [i.id for i in inspection.items] == [i.id for i in plain.items]


def test_an_unmapped_picture_font_glyph_is_not_turned_into_a_letter():
    from app.extracted_text import word_symbol_text
    from app.monthly_report_native_layout import _set_reviewed_footer_text
    assert word_symbol_text("Webdings", "0061") == ""
    assert word_symbol_text("Zapf Dingbats", "0034") == ""
    assert word_symbol_text("Calibri", "00E9") == "é"
    paragraph = _paragraph('<w:r><w:sym w:font="Webdings" w:char="0061"/></w:r>' + _run(" Page 3"))
    assert importer._text(paragraph).strip() == "Page 3"
    _set_reviewed_footer_text(paragraph, "Page 4")
    assert paragraph.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}sym") is not None
    assert "a" not in importer._text(paragraph).replace("Page", "")
