"""Synthetic final-view DOCX controls: tables, review comments and range revisions."""
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.shared import Inches
from lxml import etree as XML
import pytest

from conftest import requires_libreoffice
from app.monthly_report_import import ImportError, inspect_docx
from app.monthly_report_native_package import passive_docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DELETED = "SYNTHETIC-CONFIDENTIAL-DELETED-9381"
COMMENT = "SYNTHETIC-COMMENT-PRIVATE-2917"
MOVED = "SYNTHETIC-MOVED-FROM-SECRET-3419"


def _change(paragraph, kind, text):
    tag = XML.SubElement(paragraph, W + kind, {W + "id": "7", W + "author": "Synthetic"})
    run = XML.SubElement(tag, W + "r")
    XML.SubElement(run, W + ("delText" if kind in ("del", "moveFrom") else "t")).text = text


def _fixture(tmp_path):
    """One body-level table control and an inline cell control with a merged cell."""
    doc = Document()
    doc.sections[0].page_width = Inches(11)
    doc.sections[0].page_height = Inches(8.5)
    doc.sections[0].left_margin = Inches(0.8)
    doc.add_heading("MONTHLY ACTIVITY SUMMARY", 1)
    narrative = doc.add_paragraph("Visible comment anchor. ")
    doc.add_comment(narrative.runs, text=COMMENT, author="Synthetic", initials="SY")
    _change(narrative._p, "ins", "Accepted narrative.")
    _change(narrative._p, "del", DELETED)
    _change(narrative._p, "moveFrom", MOVED)
    _change(narrative._p, "moveTo", "Accepted moved text.")
    table = doc.add_table(rows=2, cols=3)
    for cell, value in zip(table.rows[0].cells, ("Asset", "Status", "Details")):
        cell.text = value
    first = table.cell(1, 0)
    first.text = ""
    _change(first.paragraphs[0]._p, "ins", "ACCEPTED-CELL")
    _change(first.paragraphs[0]._p, "del", DELETED)
    table.cell(1, 1).merge(table.cell(1, 2)).text = "Merged accepted"
    # Wrap the actual table cell, not merely a run, in a valid Word SDT.
    row = table.rows[1]._tr
    cell = row.find(W + "tc")
    assert cell is not None
    sdt_cell = XML.Element(W + "sdt")
    XML.SubElement(sdt_cell, W + "sdtContent").append(cell)
    row.insert(0, sdt_cell)
    # The table itself is also the only block inside a content control.
    body = doc.element.body
    table_node = table._tbl
    at = body.index(table_node)
    sdt_table = XML.Element(W + "sdt")
    XML.SubElement(sdt_table, W + "sdtContent").append(table_node)
    body.insert(at, sdt_table)
    doc.add_paragraph("AFTER-CONTROL-ANCHOR")
    path = tmp_path / "a38-synthetic.docx"
    doc.save(path)
    return path


def test_final_view_recovers_controlled_table_geometry_without_review_leak(tmp_path):
    path = _fixture(tmp_path)
    original = path.read_bytes()
    inspected = inspect_docx(path)
    table = next(i for i in inspected.items if i.kind == "table")
    assert table.rows == (
        ("Asset", "Status", "Details"),
        ("ACCEPTED-CELL", "Merged accepted", ""),
    )
    assert table.position == 3
    assert any(i.position == 4 and i.text == "AFTER-CONTROL-ANCHOR" for i in inspected.items)
    assert "Accepted narrative." in str(inspected.items)
    assert "Accepted moved text." in str(inspected.items)
    assert all(s not in str(inspected.items) for s in (DELETED, COMMENT, MOVED))
    assert inspected.sha256 == sha256(original).hexdigest()
    assert inspected.revision_view_version == 1
    assert all(i.id.startswith("current-v1-") for i in inspected.items)
    assert path.read_bytes() == original
    rendered = passive_docx(path)
    with ZipFile(BytesIO(rendered)) as archive:
        assert not any("comments" in name.casefold() for name in archive.namelist())
        body = archive.read("word/document.xml")
        native = XML.fromstring(body)
        assert len(list(native.iter(W + "sdt"))) == 2
        assert "2" in [node.get(W + "val") for node in native.iter(W + "gridSpan")]
        with ZipFile(BytesIO(original)) as source_zip:
            source_xml = XML.fromstring(source_zip.read("word/document.xml"))
        old_size = next(source_xml.iter(W + "pgSz"))
        new_size = next(native.iter(W + "pgSz"))
        assert old_size.attrib == new_size.attrib
        assert b"ACCEPTED-CELL" in body
        assert b"AFTER-CONTROL-ANCHOR" in body
        assert all(s.encode() not in body for s in (DELETED, COMMENT, MOVED))


@pytest.mark.parametrize("kind", ["moveFrom", "customXmlDel", "customXmlMoveFrom"])
def test_unwrapped_range_deletion_fails_closed_in_inspection_and_native_view(tmp_path, kind):
    doc = Document()
    doc.add_heading("MONTHLY ACTIVITY SUMMARY", 1)
    p = doc.add_paragraph(MOVED)
    p._p.insert(0, XML.Element(W + kind + "RangeStart", {W + "id": "42"}))
    p._p.append(XML.Element(W + kind + "RangeEnd", {W + "id": "42"}))
    path = tmp_path / ("range-" + kind + ".docx")
    doc.save(path)
    original = path.read_bytes()
    for operation in (inspect_docx, passive_docx):
        with pytest.raises(ImportError, match="range|structur|tracked"):
            operation(path)
    assert path.read_bytes() == original


def test_unwrapped_range_start_without_end_fails_closed(tmp_path):
    doc = Document()
    p = doc.add_paragraph(MOVED)
    p._p.insert(0, XML.Element(W + "moveFromRangeStart", {W + "id": "42"}))
    path = tmp_path / "unpaired.docx"
    doc.save(path)
    with pytest.raises(ImportError, match="range|structur|tracked"):
        inspect_docx(path)


def test_mixed_content_control_is_not_silently_imported_as_prose(tmp_path):
    doc = Document()
    doc.add_heading("MONTHLY ACTIVITY SUMMARY", 1)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Heading"
    table.cell(1, 0).text = "Data"
    body, node = doc.element.body, table._tbl
    at = body.index(node)
    control = XML.Element(W + "sdt")
    content = XML.SubElement(control, W + "sdtContent")
    para = XML.SubElement(content, W + "p")
    run = XML.SubElement(para, W + "r")
    XML.SubElement(run, W + "t").text = "Context before separate table"
    content.append(node)
    body.insert(at, control)
    path = tmp_path / "mixed-control.docx"
    doc.save(path)
    original = path.read_bytes()
    inspected = inspect_docx(path)
    assert any(i.kind == "unsupported" and "mixed or multiple table" in i.note for i in inspected.items)
    assert not any(i.kind == "table" for i in inspected.items)
    assert not any(i.kind == "text" and "Context before separate table" in i.text for i in inspected.items)
    assert path.read_bytes() == original


def test_missing_and_malformed_docx_do_not_create_any_import_items(tmp_path):
    with pytest.raises((FileNotFoundError, OSError)):
        inspect_docx(tmp_path / "not-uploaded.docx")
    malformed = tmp_path / "malformed.docx"
    malformed.write_bytes(b"not a DOCX")
    with pytest.raises(ImportError, match="could not be safely read"):
        inspect_docx(malformed)


@requires_libreoffice
def test_passive_docx_pdf_layout_and_accepted_cells(tmp_path):
    from app.pdf_converter import convert_to_pdf
    import pymupdf

    path = _fixture(tmp_path)
    output = tmp_path / "a38-passive.docx"
    output.write_bytes(passive_docx(path))
    pdf_path = convert_to_pdf(output)
    try:
        with pymupdf.open(pdf_path) as pages:
            assert pages.page_count >= 1
            page = pages[0]
            assert abs(page.rect.width - 792) < 2
            assert abs(page.rect.height - 612) < 2
            content = "".join(p.get_text() for p in pages)
            assert "ACCEPTED-CELL" in content
            assert "Merged accepted" in content
            assert all(s not in content for s in (DELETED, COMMENT, MOVED))
    finally:
        pdf_path.unlink(missing_ok=True)
