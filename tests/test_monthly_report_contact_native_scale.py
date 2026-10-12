"""Native Word/PDF contact-grid acceptance at zero, one, four and forty rows.

The fixture is entirely invented; no authentic customer master or contact data
is published. It tests a real physical Word table and actual LibreOffice PDF.
"""
from io import BytesIO
import re

import fitz
import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches

from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable,
    ResolvedBlock, default_sections,
)
from app.monthly_report_native_layout import build_native_docx
from conftest import requires_libreoffice


HEADERS = ("Site", "Role", "Name", "Telephone", "Email")


def scenario(tmp_path, contact_count):
    source = Document()
    section = source.sections[0]
    section.top_margin = Inches(.65)
    section.bottom_margin = Inches(.65)
    source.add_heading("ORGANIZATIONAL CHART", 1)
    table = source.add_table(rows=2, cols=len(HEADERS))
    for index, title in enumerate(HEADERS):
        table.cell(0, index).text = title
        table.cell(1, index).text = "OTHER CLIENT: obsolete details"
    source_path = tmp_path / "invented-native-contact-master.docx"
    source.save(source_path)
    profile = ReportProfile(
        "Synthetic Contact Acceptance", "north", "Invented North",
        (Facility("north", "Invented North"),),
    )
    rows = tuple(
        ("Invented North", "Shift coordinator", f"Synthetic Person {index:02d}",
         f"555-{1000+index}", f"person{index:02d}@example.invalid")
        for index in range(1, contact_count + 1)
    )
    contacts = ResolvedBlock(
        "contact_matrix", "This month",
        extra_tables=(ReportTable(HEADERS, rows, "synthetic:current-contacts"),),
    )
    draft = ReportDraft(
        profile, ReportPeriod(2026, 9), "Invented Tester",
        default_sections(), (contacts,), synthetic=True,
    )
    return source_path, draft, rows


@pytest.mark.parametrize("contact_count", (0, 1, 4, 40))
def test_contact_native_word_retains_only_current_rows_and_physical_schema(tmp_path, contact_count):
    source, draft, rows = scenario(tmp_path, contact_count)
    output = build_native_docx(draft, source, section_key="organization", master=True)
    rendered = Document(BytesIO(output))
    text = "\n".join(paragraph.text for paragraph in rendered.paragraphs)
    text += "\n" + "\n".join(
        cell.text for table in rendered.tables for row in table.rows for cell in row.cells)
    assert "OTHER CLIENT" not in text
    assert "ORGANIZATIONAL CHART" in text
    for row in rows:
        assert text.count(row[2]) == 1
    assert "Synthetic Person 41" not in text
    if contact_count:
        matching = [table for table in rendered.tables
                    if len(table.columns) == len(HEADERS)
                    and table.cell(0, 0).text == HEADERS[0]]
        assert len(matching) == 1
        grid = matching[0]
        assert len(grid.rows) == contact_count + 1
        assert tuple(cell.text for cell in grid.rows[0].cells) == HEADERS
        assert tuple(grid.rows[-1].cells[n].text for n in range(5)) == rows[-1]
        header_props = grid.rows[0]._tr.find(qn("w:trPr"))
        assert header_props is not None
        assert header_props.find(qn("w:tblHeader")) is not None
        # Each person has multiple fields. The header and *every* current
        # contact row must stay on the same printed page, even for 40 people.
        # Unrelated narrative/native grids are intentionally not changed.
        assert all(row._tr.find(qn("w:trPr") + "/" + qn("w:cantSplit")) is not None
                   for row in grid.rows)


@requires_libreoffice
@pytest.mark.parametrize("contact_count", (0, 1, 4, 40))
def test_contact_native_pdf_has_no_old_rows_and_preserves_every_current_person(
        tmp_path, monkeypatch, contact_count):
    from app import pdf_converter
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    source, draft, rows = scenario(tmp_path, contact_count)
    output = build_native_docx(draft, source, section_key="organization", master=True)
    path = tmp_path / f"current-contact-{contact_count}.docx"
    path.write_bytes(output)
    pdf_path = pdf_converter.convert_to_pdf(path)
    with fitz.open(pdf_path) as doc:
        assert len(doc) >= 1
        pages = [page.get_text() for page in doc]
        # Cell text can wrap between a person's name and two-digit index.
        # Collapse only layout whitespace; still require each exact contact once.
        normalized_pages = [re.sub(r"\s+", " ", value) for value in pages]
        joined = " ".join(normalized_pages)
        assert "OTHER CLIENT" not in joined
        assert "ORGANIZATIONAL CHART" in joined
        assert "Synthetic Person 41" not in joined
        for row in rows:
            assert joined.count(row[2]) == 1
        if rows:
            heading_page = next(i for i, text in enumerate(normalized_pages)
                                if "ORGANIZATIONAL CHART" in text)
            first_person_page = next(i for i, text in enumerate(normalized_pages)
                                     if "Synthetic Person 01" in text)
            assert first_person_page == heading_page, (
                "The native contact header must not be orphaned below the chart heading.")
        for i, page in enumerate(doc):
            for block in page.get_text("blocks"):
                if block[6] == 0 and block[4].strip():
                    x0, y0, x1, y1 = block[:4]
                    assert x0 >= -1 and y0 >= -1 and x1 <= page.rect.width + 1, i
                    assert y1 <= page.rect.height + 1, i
