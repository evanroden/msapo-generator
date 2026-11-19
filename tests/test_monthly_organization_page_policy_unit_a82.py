"""Bounded, synthetic tests for exact-output organization page policy (A82)."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from PIL import Image
import pytest

from app.monthly_report_docx import _build_docx
from app.monthly_report_model import ResolvedBlock, default_sections
from app.monthly_report_organization_page_policy import (
    label_current_diagram, repeat_current_contact_headers, separate_current_diagrams,
)
from tests.test_monthly_report_generic_contact_page import _draft


@pytest.mark.parametrize("rows", [0, 1, 46])
def test_only_actual_current_contact_heading_is_repeated(rows):
    document = Document()
    table = document.add_table(rows=rows + 1, cols=2)
    for index, row in enumerate(table.rows):
        row.cells[0].text = "Header" if index == 0 else f"Synthetic {index}"
    repeat_current_contact_headers(table._tbl)
    if rows:
        assert table.rows[0]._tr.xpath("./w:trPr/w:tblHeader")
        assert all(row._tr.xpath("./w:trPr/w:cantSplit") for row in table.rows)
    else:
        assert not table.rows[0]._tr.xpath("./w:trPr/w:tblHeader")
    assert not any(row._tr.xpath("./w:trPr/w:tblHeader") for row in table.rows[1:])


def test_chart_title_moves_with_chart_after_prior_text():
    document = Document()
    document.add_paragraph("Synthetic earlier section details")
    title = document.add_paragraph("ORGANIZATIONAL CHART")
    chart = document.add_paragraph("New chart")
    separate_current_diagrams(document.element.body, [chart._p], [])
    assert title._p.xpath("./w:pPr/w:pageBreakBefore")
    assert not chart._p.xpath("./w:pPr/w:pageBreakBefore")


def test_source_section_boundary_is_not_given_a_duplicate_page_break():
    document = Document()
    previous = document.add_paragraph("Synthetic prior content")
    previous._p.get_or_add_pPr().append(OxmlElement("w:sectPr"))
    title = document.add_paragraph("ORGANIZATIONAL CHART")
    chart = document.add_paragraph("New chart")
    separate_current_diagrams(document.element.body, [chart._p], [])
    assert not title._p.xpath("./w:pPr/w:pageBreakBefore")


def test_first_workflow_moves_after_chart_without_orphaning_workflow_heading():
    document = Document()
    chart = document.add_paragraph("New chart")
    title = document.add_paragraph("Business hours workflow")
    workflow = document.add_paragraph("New workflow")
    separate_current_diagrams(document.element.body, [chart._p], [workflow._p])
    assert title._p.xpath("./w:pPr/w:pageBreakBefore")
    assert not workflow._p.xpath("./w:pPr/w:pageBreakBefore")


def test_empty_diagrams_never_add_breaks_or_synthetic_contact_rows():
    document = Document()
    alone = document.add_paragraph("Existing source content")
    table = document.add_table(rows=1, cols=2)
    before = document.element.body.xml
    separate_current_diagrams(document.element.body, [], [alone._p])
    label_current_diagram(alone._p, "unrecognized_block")
    repeat_current_contact_headers(table._tbl)
    assert document.element.body.xml == before


def test_approved_diagram_alt_replaces_source_only_client_description():
    document = Document()
    picture = BytesIO()
    Image.new("RGB", (200, 100), "blue").save(picture, "PNG")
    shape = document.add_picture(BytesIO(picture.getvalue()))
    shape._inline.docPr.set("descr", "OLD SOURCE CLIENT SECRET")
    label_current_diagram(document.paragraphs[-1]._p, "org_chart")
    assert shape._inline.docPr.get("descr") == "Organization chart for this report"
    assert "OLD SOURCE" not in document.element.xml


@pytest.mark.parametrize("chart", [True, False])
def test_generic_chart_workflow_and_contacts_have_distinct_page_starts(chart):
    value = _draft(chart=chart)
    image = BytesIO()
    Image.new("RGB", (1800, 450), "blue").save(image, "PNG")
    raw = image.getvalue()
    reference = sha256(raw).hexdigest() + ".png"
    procedure = ResolvedBlock(
        "business_hours_workflow", "This month",
        text="Synthetic approved procedure summary",
        asset_hashes=(reference,),
    )
    section = next(section for section in default_sections()
                   if section.key == "organization")
    value = replace(value, sections=(section,), blocks=(*value.blocks, procedure))
    document = Document(BytesIO(
        _build_docx(value, asset_loader={reference: raw}.__getitem__)
    ))
    workflow_text = next(p for p in document.paragraphs
                         if p.text == "Synthetic approved procedure summary")
    assert workflow_text.paragraph_format.page_break_before is (True if chart else None)
    contact_heading = next(p for p in document.paragraphs
                           if p.text == "Facility contacts")
    assert contact_heading.paragraph_format.page_break_before is True
    descriptions = [shape._inline.docPr.get("descr")
                    for shape in document.inline_shapes]
    assert descriptions.count("Organization chart for this report") == int(chart)
    assert descriptions.count("Business-hours workflow diagram for this contract") == 1
    picture_shape = next(shape for shape in document.inline_shapes
                         if shape._inline.docPr.get("descr", "").startswith("Business-hours"))
    assert abs(picture_shape.width / picture_shape.height - 4) < .02
