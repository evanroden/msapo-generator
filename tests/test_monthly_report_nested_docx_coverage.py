"""Synthetic DOCX source-item conservation tests for #271/#471.

All source bytes and names are synthetic. No customer report is read here.
"""
from hashlib import sha256
from docx import Document
from app import monthly_report_import as importer
from app.monthly_report_sections import section_reviews, table_without_prices


def _nested_source(tmp_path):
    doc = Document()
    doc.add_paragraph("Synthetic Facility North")
    doc.add_heading("Monthly Activity Summary", 1)
    doc.add_paragraph("Synthetic completed September 2026 service.")
    outer = doc.add_table(rows=2, cols=2)
    outer.cell(0, 0).text = "Area"
    outer.cell(0, 1).text = "Details"
    outer.cell(1, 0).text = "Mechanical"
    outer.cell(1, 1).text = "Parent note"
    nested = outer.cell(1, 1).add_table(rows=2, cols=2)
    for cell, value in zip(nested.rows[0].cells, ("Equipment", "Status")):
        cell.text = value
    for cell, value in zip(nested.rows[1].cells, ("Pump A", "Completed")):
        cell.text = value
    path = tmp_path / "nested-synthetic.docx"
    doc.save(path)
    return path


def test_nested_table_occurrences_are_conserved_and_reviewed(tmp_path):
    path = _nested_source(tmp_path)
    before = sha256(path.read_bytes()).hexdigest()
    inspected = importer.inspect_docx(path)
    assert inspected.sha256 == before
    assert sha256(path.read_bytes()).hexdigest() == before
    tables = [item for item in inspected.items if item.kind == "table"]
    assert len(tables) == 1, "Nested table must be an independent editable item."
    child = tables[0]
    assert child.rows == (("Equipment", "Status"), ("Pump A", "Completed"))
    assert child.section == "activity"
    assert child.suggested_slot
    parents = [item for item in inspected.items if item.kind == "unsupported"
               and "nested" in item.note.lower() and item.position == child.position]
    assert len(parents) == 1, "Outer layout must remain in a single actionable review item."
    assert "Pump A" not in parents[0].text, "Nested cells cannot be duplicated as outer prose."
    assert child.id.startswith(parents[0].id + "-nested-")
    assert any(parent.id in {i.id for s in section_reviews(inspected) for i in s.items}
               for parent in parents)
    table, removed = table_without_prices(child)
    assert table.columns == ("Equipment", "Status")
    assert table.rows == (("Pump A", "Completed"),)
    assert not removed


def test_plain_table_schema_remains_unchanged(tmp_path):
    doc = Document()
    doc.add_heading("Training Summary", 1)
    table = doc.add_table(rows=2, cols=2)
    for cell, value in zip(table.rows[0].cells, ("Session", "Hours")):
        cell.text = value
    for cell, value in zip(table.rows[1].cells, ("Synthetic safety", "0")):
        cell.text = value
    path = tmp_path / "plain-synthetic.docx"
    doc.save(path)
    inspection = importer.inspect_docx(path)
    candidates = [i for i in inspection.items if i.kind == "table"]
    assert len(candidates) == 1
    assert candidates[0].rows == (("Session", "Hours"), ("Synthetic safety", "0"))
