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
    texts = _texts(inspection)
    assert "Visible note." in texts and "Reviewer:" in texts
    assert not any("Click or tap" in t or "Enter the" in t for t in texts)
    # The prompt-only paragraph keeps its ordinal: later IDs match a document
    # in which that paragraph had real text, so saved mappings do not shift.
    closing = next(i for i in inspection.items if i.text == "Closing line.")
    filled = _docx(tmp_path, [
        _run("Visible note."), _run("2026-10-14"), _run("Reviewer: x"), _run("Closing line."),
    ])
    assert closing.id == next(i for i in filled.items if i.text == "Closing line.").id


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
