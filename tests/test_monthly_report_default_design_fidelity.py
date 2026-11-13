"""Built-in design output follows the layout of a finished monthly report.

Synthetic stand-ins for differences found against a real October report:
page titles that share a paragraph with their picture, title bands over
service-call tables, campus band rows, and wide schedules set compactly.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from PIL import Image
import pytest

from app.monthly_report_docx import _table_font_size, _title_band, assemble_docx
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import (
    ReportPeriod, ReportTable, ResolvedBlock, synthetic_draft, synthetic_profiles,
)
from app.monthly_report_sections import _builtin_design, build_section_import

PROFILE = synthetic_profiles()[0]
TITLE = ("October 2026 Service Calls", "Column 2", "Column 3", "Column 4", "Column 5")
HEADER = ("WO #", "Finish Date", "Area", "Task Code-Description", "Tag #")
CALL = ("00042", "2026-10-12", "Synthetic plant", "Inspect pump", "P-0007")


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def render(*tables):
    draft = synthetic_draft(PROFILE, ReportPeriod(2026, 10))
    first = draft.blocks[0]
    draft = replace(draft, blocks=(replace(first, extra_tables=tables), *draft.blocks[1:]))
    output = Document(BytesIO(assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)))
    return [table for table in output.tables if len(table.columns) == len(tables[0].columns)]


def unique_cells(row):
    seen, cells = set(), []
    for cell in row.cells:
        if id(cell._tc) not in seen:
            seen.add(id(cell._tc))
            cells.append(cell)
    return cells


def repeats_as_header(row):
    return row._tr.trPr is not None and row._tr.trPr.find(qn("w:tblHeader")) is not None


def test_title_band_renders_full_width_over_the_real_headings(storage):
    assert _title_band(TITLE)
    assert not _title_band(HEADER)
    assert not _title_band(("Not a title", "Column 3", "Column 4"))  # not the importer's own numbering
    table, = render(ReportTable(TITLE, (HEADER, CALL)))
    title, headings, call = table.rows
    assert [cell.text for cell in unique_cells(title)] == [TITLE[0]]
    assert [cell.text for cell in headings.cells] == list(HEADER)
    assert [cell.text for cell in call.cells] == list(CALL)
    assert repeats_as_header(title) and repeats_as_header(headings) and not repeats_as_header(call)
    assert "Column 2" not in "".join(cell.text for row in table.rows for cell in row.cells)


def test_group_band_rows_span_the_table_and_ordinary_rows_do_not(storage):
    columns = ("Description", "Designation", "Status")
    note = "No October work recorded for this campus."
    table, = render(ReportTable(columns, (
        ("NEW EQUIPMENT", "", ""), ("Boiler", "B-6", "Open"), (note, "", ""),
        ("Pump", "", ""), ("UNITY HOSPITAL",))))
    _, band, ordinary, message, partial, short = table.rows
    assert [cell.text for cell in unique_cells(band)] == ["NEW EQUIPMENT"]
    assert all(run.bold for p in unique_cells(band)[0].paragraphs for run in p.runs)
    assert [cell.text for cell in ordinary.cells] == ["Boiler", "B-6", "Open"]
    assert [cell.text for cell in unique_cells(message)] == [note]
    # A short value in an otherwise blank row, or a short source row, stays a data row.
    assert [cell.text for cell in partial.cells] == ["Pump", "", ""]
    assert [cell.text for cell in short.cells] == ["UNITY HOSPITAL", "", ""]


def test_wide_schedules_use_the_compact_report_size(storage):
    long_titles = ("Campus", "Description", "Designation", "Capacity", "Units",
                   "End of Useful Life", "O&M Option")
    schedule, = render(ReportTable(long_titles, tuple(("U", "Pump", "P-1", "1", "Count", "2030", "A"),) * 3))
    assert _table_font_size(schedule, True) == 7
    many = tuple(f"C{n}" for n in range(7))
    grid, = render(ReportTable(many, (tuple("x" * 7),)))
    assert _table_font_size(grid, True) == 9  # a short wide grid keeps the ordinary size
    small, = render(ReportTable(("Name", "Role", "Phone"), (("A", "B", "C"),)))
    assert _table_font_size(small, True) == 10


def picture_page(path, title):
    image = BytesIO()
    Image.new("RGB", (400, 500), (20, 120, 200)).save(image, "PNG")
    image.seek(0)
    document = Document()
    document.add_heading("7 Water Treatment Reports", 1)
    paragraph = document.add_paragraph()
    paragraph.add_run(title)
    paragraph.add_run().add_break()
    paragraph.add_run().add_picture(image)
    document.save(path)
    inspection = inspect_docx(path)
    text = next(item for item in inspection.items if item.kind == "text" and item.text == title)
    picture = next(item for item in inspection.items if item.kind == "image")
    return inspection, text, picture


def imported(path, inspection, ids, profile, texts=None):
    plan = {"key": "water", "target": "water", "approved": True, "selected": list(ids)}
    if texts is not None:
        plan["texts"] = texts
    mapped, mappings = build_section_import(path, inspection, (plan,), profile=profile)
    return {block.key: block for block in mapped.blocks}, {m.item_id: m.slot for m in mappings}


def test_picture_title_in_the_same_paragraph_becomes_its_caption(storage):
    path = storage / "water.docx"
    title = "Metro Group water report, October 13, 2026"
    inspection, text, picture = picture_page(path, title)
    blocks, slots = imported(path, inspection, (text.id, picture.id), PROFILE)
    assert _builtin_design(PROFILE)
    page = blocks[slots[picture.id]]
    assert page.asset_captions == (title,)
    assert slots[text.id] == slots[picture.id]
    assert not any(title in block.text for block in blocks.values())
    assert any(text.id in reference for reference in page.references)


@pytest.mark.parametrize("profile", [None, replace(PROFILE, template="enfra_master:synthetic")])
def test_saved_design_or_no_design_keeps_the_title_where_the_source_put_it(storage, profile):
    path = storage / "water.docx"
    title = "Metro Group water report, October 13, 2026"
    inspection, text, picture = picture_page(path, title)
    assert not _builtin_design(profile)
    blocks, slots = imported(path, inspection, (text.id, picture.id), profile)
    assert slots[text.id] != slots[picture.id]
    assert blocks[slots[text.id]].text.strip() == title
    assert blocks[slots[picture.id]].asset_captions in ((), ("",))


def test_edited_title_wording_stays_prose(storage):
    path = storage / "water.docx"
    inspection, text, picture = picture_page(path, "Metro Group water report")
    edit = {text.id: "Metro Group water report, reviewed"}
    blocks, slots = imported(path, inspection, (text.id, picture.id), PROFILE, edit)
    assert slots[text.id] != slots[picture.id]
    assert blocks[slots[text.id]].text.strip() == edit[text.id]
    assert blocks[slots[picture.id]].asset_captions in ((), ("",))


def test_a_priced_title_is_never_moved_onto_a_picture(storage):
    path = storage / "water.docx"
    inspection, text, picture = picture_page(path, "Proposal total $1,597.32 for water treatment")
    with pytest.raises(ValueError, match="pricing"):
        imported(path, inspection, (text.id, picture.id), PROFILE)
