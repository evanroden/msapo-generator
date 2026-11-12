"""Synthetic-only master compatibility, import and report-month regressions."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib

from docx import Document
from lxml import etree
import pytest

from app import monthly_report_designs as designs, monthly_report_library as library
from app.monthly_report_import import inspect_docx, report_period_from_title_candidates
from app.monthly_report_master_install_compat import prepare_master_working_copy
from app.monthly_report_native_package import passive_docx
from app.monthly_report_model import ReportPeriod
from test_monthly_report_designs import master_reference

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
WPS = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}"
V = "{urn:schemas-microsoft-com:vml}"


def edit_package(path, edit):
    with ZipFile(path) as source:
        parts = {item.filename: (item, source.read(item.filename)) for item in source.infolist()}
    root = etree.fromstring(parts["word/document.xml"][1])
    edit(root, parts)
    parts["word/document.xml"] = (parts["word/document.xml"][0], etree.tostring(root))
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, (info, data) in parts.items():
            archive.writestr(info if info else name, data)


def alternate(root, *, modern=True, mismatch=False, malformed=False):
    body = root.find(W + "body")
    p = etree.Element(W + "p")
    wrapper = etree.SubElement(p, MC + "AlternateContent", nsmap={
        "mc": MC[1:-1], "wps": WPS[1:-1], "w": W[1:-1],
        "a": A[1:-1], "v": V[1:-1]})
    choice = etree.SubElement(wrapper, MC + "Choice", Requires="wps")
    drawing = etree.SubElement(choice, W + "drawing")
    graphic = etree.SubElement(drawing, A + "graphic")
    data = etree.SubElement(graphic, A + "graphicData", uri=WPS[1:-1])
    shape = etree.SubElement(data, WPS + "wsp")
    props = etree.SubElement(shape, WPS + "spPr")
    xfrm = etree.SubElement(props, A + "xfrm")
    etree.SubElement(xfrm, A + "ext", cx="127000", cy="254000")
    etree.SubElement(props, A + "prstGeom", prst="rect")
    textbox = etree.SubElement(shape, WPS + "txbx")
    wordbox = etree.SubElement(textbox, W + "txbxContent")
    text = etree.SubElement(etree.SubElement(etree.SubElement(wordbox, W + "p"), W + "r"), W + "t")
    text.text = "Synthetic shape"
    if not malformed:
        fallback = etree.SubElement(wrapper, MC + "Fallback")
        pict = etree.SubElement(fallback, W + "pict")
        legacy = etree.SubElement(pict, V + "shape", type="#_x0000_t202",
                                  style="width:10pt;height:20pt")
        legacybox = etree.SubElement(legacy, V + "textbox")
        txt = etree.SubElement(etree.SubElement(etree.SubElement(
            etree.SubElement(legacybox, W + "txbxContent"), W + "p"), W + "r"), W + "t")
        txt.text = "Different hidden text" if mismatch else "Synthetic shape"
    body.insert(0, p)


def test_matching_modern_legacy_shape_normalizes_without_mutating_source(tmp_path):
    src = master_reference(tmp_path)
    edit_package(src, lambda root, parts: alternate(root))
    original = src.read_bytes()
    working, reasons = prepare_master_working_copy(src)
    assert src.read_bytes() == original
    assert working is not None and reasons == ("equivalent_modern_choice",)
    with ZipFile(BytesIO(working)) as doc:
        contents = doc.read("word/document.xml")
        assert b"AlternateContent" not in contents
        assert b"Synthetic shape" in contents
        assert b"Different hidden text" not in contents
        assert doc.namelist() == ZipFile(src).namelist()
    second = tmp_path / "working.docx"
    second.write_bytes(working)
    assert prepare_master_working_copy(second) == (None, ())
    passive_docx(second)


@pytest.mark.parametrize("case", ["different", "missing_fallback", "unknown_namespace"])
def test_unproved_drawing_fails_with_actionable_error_and_original_preserved(tmp_path, case):
    src = master_reference(tmp_path)
    def mutate(root, parts):
        alternate(root, mismatch=case == "different", malformed=case == "missing_fallback")
        if case == "unknown_namespace":
            root.find(".//" + MC + "Choice").set("Requires", "invented")
    edit_package(src, mutate)
    original = src.read_bytes()
    with pytest.raises(ValueError, match="AlternateContent|drawing|namespace"):
        prepare_master_working_copy(src)
    assert src.read_bytes() == original


def test_fallback_only_is_not_discarded(tmp_path):
    src = master_reference(tmp_path)
    def mutate(root, parts):
        alternate(root)
        wrapper = root.find(".//" + MC + "AlternateContent")
        wrapper.remove(wrapper.find(MC + "Choice"))
    edit_package(src, mutate)
    assert prepare_master_working_copy(src) == (None, ())
    assert b"Fallback" in src.read_bytes()


def test_only_orphan_comments_are_cleaned_in_working_copy(tmp_path):
    src = master_reference(tmp_path)
    def mutate(root, parts):
        p = root.find(".//" + W + "p")
        for identity in ("1", "999"):
            etree.SubElement(p, W + "commentRangeStart", {W + "id": identity})
            etree.SubElement(p, W + "commentRangeEnd", {W + "id": identity})
            etree.SubElement(p, W + "commentReference", {W + "id": identity})
        comments = etree.Element(W + "comments")
        etree.SubElement(comments, W + "comment", {W + "id": "1"})
        parts["word/comments.xml"] = (None, etree.tostring(comments))
    edit_package(src, mutate)
    original = src.read_bytes()
    working, reasons = prepare_master_working_copy(src)
    assert src.read_bytes() == original
    assert reasons == ("orphan_comment_marker",)
    with ZipFile(BytesIO(working)) as doc:
        root = etree.fromstring(doc.read("word/document.xml"))
        assert {n.get(W + "id") for n in root.iter() if n.tag in {
            W + "commentRangeStart", W + "commentRangeEnd", W + "commentReference"}} == {"1"}
        assert doc.read("word/comments.xml") == ZipFile(src).read("word/comments.xml")


def test_master_install_keeps_original_and_pinned_history(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    src = master_reference(tmp_path)
    edit_package(src, lambda root, parts: alternate(root))
    original = src.read_bytes()
    digest = designs.install_master(src, actor="Synthetic editor", expected_revision=0)
    from app.monthly_report_model import synthetic_profiles
    pinned = designs.pin(synthetic_profiles()[0], latest_master=True)
    assert designs.source_for(pinned).read_bytes() == original
    normalized = designs.render_source_for(pinned)
    assert normalized != designs.source_for(pinned)
    assert normalized.read_bytes() != original
    assert inspect_docx(normalized).items
    saved = designs.install_master(src, actor="Synthetic editor", expected_revision=1)
    assert saved == digest
    assert designs.master_state()["revision"] == 1
    assert designs.source_for(pinned).read_bytes() == original
    assert designs.render_source_for(pinned) == normalized
    second = master_reference(tmp_path, name="different", marker="Second design")
    new = designs.install_master(second, actor="Synthetic editor", expected_revision=1)
    assert new != digest
    assert designs.source_for(pinned).read_bytes() == original
    assert designs.render_source_for(pinned).read_bytes() == normalized.read_bytes()


def test_title_month_is_distinct_from_cover_print_date_and_conflicts_are_reviewed():
    period, notes = report_period_from_title_candidates((
        "QA-UNO Monthly Report — January 2026",
        "Cover printed Date: February 2, 2026",
    ))
    assert period == ReportPeriod(2026, 1)
    assert not notes
    period, notes = report_period_from_title_candidates((
        "Report month: January 2026",
        "Reporting period: February 2026",
    ))
    assert period is None
    assert any("conflict" in message.casefold() for message in notes)
    assert report_period_from_title_candidates(("Date: February 2, 2026",))[0] is None


def test_unrecognized_section_and_its_table_stay_reviewable(tmp_path):
    doc = Document()
    doc.add_heading("Synthetic Monthly Report", 0)
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Routine operations.")
    doc.add_paragraph("13 EXTRA REGIONAL OPERATIONS")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Field"
    table.cell(1, 0).text = "Unmapped value"
    src = tmp_path / "unmatched.docx"
    doc.save(src)
    result = inspect_docx(src)
    assert any(item.section == "unmatched" and item.kind == "table"
               and "Unmapped value" in str(item.rows) for item in result.items)


def test_supported_native_word_output_preserves_editable_tables(tmp_path):
    from test_monthly_report_master_tables import master_source, current
    from app.monthly_report_master_tables import from_inspection
    from app.monthly_report_native_layout import build_native_docx

    source = master_source(tmp_path)
    selected = from_inspection(inspect_docx(source))
    raw = build_native_docx(current(selected), source, master=True)
    assert raw[:2] == b"PK"
    rendered = Document(BytesIO(raw))
    assert len(rendered.tables) == 2
    assert rendered.tables[0].cell(1, 2).text == "45 gpm"
    assert "OLD PRIVATE CLIENT" not in "\n".join(
        cell.text for table in rendered.tables for row in table.rows for cell in row.cells)


def test_supported_native_pdf_export_uses_local_libreoffice(tmp_path):
    import shutil
    import fitz
    from test_monthly_report_master_tables import master_source, current
    from app.monthly_report_master_tables import from_inspection
    from app.monthly_report_native_layout import build_native_docx
    from app import pdf_converter

    if not (shutil.which("libreoffice") or shutil.which("soffice")):
        pytest.skip("The configured real PDF renderer is not installed in this environment.")
    source = master_source(tmp_path)
    selected = from_inspection(inspect_docx(source))
    rendered = tmp_path / "synthetic-master.docx"
    rendered.write_bytes(build_native_docx(current(selected), source, master=True))
    pdf_path = pdf_converter._convert_libreoffice(rendered, lossless_images=True)
    try:
        with pdf_path.open("rb") as stream:
            assert stream.read(5) == b"%PDF-"
        with fitz.open(pdf_path) as result:
            assert len(result) > 0
            body = "\n".join(page.get_text() for page in result)
            assert "Q-TEST-731" in body
            assert "OLD PRIVATE CLIENT" not in body
    finally:
        pdf_path.unlink()


def test_import_save_reopen_keeps_unknown_section_in_review(tmp_path, monkeypatch):
    from app.monthly_report_import import ImportMapping, map_items
    from app.monthly_report_model import synthetic_profiles

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "synthetic-library"))
    document = Document()
    document.add_heading("Synthetic Operations Monthly Report — September 2026", 0)
    document.add_heading("2 Monthly Activity Summary", 1)
    document.add_paragraph("Invented completed rounds, no monetary amounts.")
    document.add_paragraph("13 EXTRA REGIONAL OPERATIONS")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Identifier"
    table.cell(1, 0).text = "Unknown review-only example"
    source = tmp_path / "synthetic-unknown.docx"
    document.save(source)
    original = source.read_bytes()
    inspection = inspect_docx(source)
    unknown = next(item for item in inspection.items if item.kind == "table"
                   and item.section == "unmatched")
    text_item = next(item for item in inspection.items if item.kind == "text"
                     and item.section == "activity"
                     and "Invented completed rounds" in item.text)
    mapped = map_items(source, inspection, (ImportMapping(text_item.id, "activity_summary"),))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    library.save_import(profile.contract, profile.key, mapped.blocks,
                        overrides=mapped.overrides, expected_revision=1,
                        actor="Synthetic Editor", confirmed=True)
    reloaded = library.load_profile(profile.contract, profile.key)
    assert "Invented completed rounds" in reloaded.block("activity_summary").text
    assert unknown.id not in mapped.mapped_ids
    assert source.read_bytes() == original
    assert any(item.id == unknown.id for item in inspect_docx(source).items)


def test_working_copy_keeps_numbering_images_headers_footers_and_relationships(tmp_path):
    from PIL import Image
    from docx.shared import Inches
    from docx.opc.constants import RELATIONSHIP_TYPE as REL
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    source = master_reference(tmp_path)
    doc = Document(source)
    doc.add_paragraph("Invented numbered operation", style="List Number")
    image = BytesIO()
    Image.new("RGB", (24, 24), (37, 90, 57)).save(image, format="PNG")
    image.seek(0)
    doc.sections[0].header.paragraphs[0].add_run().add_picture(image, width=Inches(0.2))
    doc.sections[0].footer.paragraphs[0].text = "Synthetic internal footer"
    link = doc.part.relate_to("https://example.invalid/info", REL.HYPERLINK, is_external=True)
    paragraph = doc.add_paragraph()
    node = OxmlElement("w:hyperlink")
    node.set(qn("r:id"), link)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "Synthetic safe link"
    run.append(text)
    node.append(run)
    paragraph._p.append(node)
    doc.save(source)
    edit_package(source, lambda root, parts: alternate(root))
    with ZipFile(source) as original:
        parts_before = {n: original.read(n) for n in original.namelist()}
    copy_bytes, reasons = prepare_master_working_copy(source)
    assert reasons == ("equivalent_modern_choice",)
    with ZipFile(BytesIO(copy_bytes)) as prepared:
        assert set(prepared.namelist()) == set(parts_before)
        assert all(prepared.read(name) == data for name, data in parts_before.items()
                   if name != "word/document.xml")
        assert b"AlternateContent" not in prepared.read("word/document.xml")
        assert b"Synthetic safe link" in prepared.read("word/document.xml")
        assert b"numbering.xml" in prepared.read("word/_rels/document.xml.rels")
        assert any(name.startswith("word/media/") for name in prepared.namelist())
        assert any(name.startswith("word/header") for name in prepared.namelist())
        assert any(name.startswith("word/footer") for name in prepared.namelist())
