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


def test_tables_follow_their_source_heading_in_the_built_in_design(storage):
    from app.monthly_report_model import AnchoredTable
    from app.monthly_report_library import _report_table_from_dict
    from dataclasses import asdict
    rejected = AnchoredTable(("Equipment", "Status"), (("Boiler", "Rejected"),), "src:1", "Rejected Quotes")
    pending = AnchoredTable(("Equipment", "Status"), (("Pump", "Pending"),), "src:2", "Pending Quotes")
    second = AnchoredTable(("Equipment", "Status"), (("Fan", "Pending"),), "src:3", "Pending Quotes")
    loose = ReportTable(("Equipment", "Status"), (("Valve", "Open"),), "src:4")
    edited = AnchoredTable(("Equipment", "Status"), (("Tank", "Open"),), "src:5", "Wording that was changed")
    draft = synthetic_draft(PROFILE, ReportPeriod(2026, 10))
    first = replace(draft.blocks[0], text="Option B Quotes\nRejected Quotes\nPending Quotes\nClosing note",
                    extra_tables=(rejected, pending, second, loose, edited))
    draft = replace(draft, blocks=(first, *draft.blocks[1:]))
    output = Document(BytesIO(assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)))
    order = []
    for node in output.element.body:
        if node.tag == qn("w:p"):
            text = "".join(node.xpath(".//w:t/text()")).strip()
            if text in ("Option B Quotes", "Rejected Quotes", "Pending Quotes", "Closing note"):
                order.append(text)
        elif node.tag == qn("w:tbl"):
            cells = [t for t in node.xpath(".//w:t/text()") if t.strip()]
            if cells[:2] == ["Equipment", "Status"]:
                order.append(cells[2])
    assert order == ["Option B Quotes", "Rejected Quotes", "Boiler", "Pending Quotes", "Pump", "Fan",
                     "Closing note", "Valve", "Tank"]
    # The source position survives saving; a plain table stays plain.
    assert _report_table_from_dict(asdict(rejected)) == rejected
    assert type(_report_table_from_dict(asdict(loose))) is ReportTable


def test_only_the_built_in_design_records_table_positions(storage):
    from app.monthly_report_model import AnchoredTable
    document = Document()
    document.add_heading("10 Pending & Declined Proposals", 1)
    document.add_paragraph("Rejected Quotes")
    table = document.add_table(rows=2, cols=2)
    for cell, value in zip(table.rows[0].cells, ("Equipment", "Status")):
        cell.text = value
    for cell, value in zip(table.rows[1].cells, ("Boiler", "Rejected")):
        cell.text = value
    path = storage / "proposals.docx"
    document.save(path)
    inspection = inspect_docx(path)
    ids = [item.id for item in inspection.items if item.kind in ("text", "table") and item.text != "10 Pending & Declined Proposals"]
    plan = {"key": "proposals", "target": "proposals", "approved": True, "selected": ids}
    for profile, anchored in ((PROFILE, True), (None, False), (replace(PROFILE, template="enfra_master:synthetic"), False)):
        mapped, _ = build_section_import(path, inspection, (plan,), profile=profile)
        tables = [t for block in mapped.blocks for t in block.extra_tables]
        assert len(tables) == 1
        assert isinstance(tables[0], AnchoredTable) is anchored
        if anchored:
            assert tables[0].anchor == "Rejected Quotes"


def png(size, color=(30, 90, 160)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def test_two_same_size_wide_slides_share_a_page_but_other_pictures_do_not(storage):
    from docx.shared import Inches
    assets = {"wf1.png": png((1280, 720)), "wf2.png": png((1280, 720), (90, 30, 160)),
              "matrix.png": png((2048, 1154)), "tall.png": png((600, 800))}
    draft = synthetic_draft(PROFILE, ReportPeriod(2026, 10))
    from app.monthly_report_asset_review import approve_all_assets
    first = approve_all_assets(replace(draft.blocks[0], text="", asset_hashes=tuple(assets)))
    draft = replace(draft, blocks=(first, *draft.blocks[1:]))
    output = Document(BytesIO(assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint,
                                            asset_loader=assets.__getitem__)))
    pictures = [p for p in output.paragraphs if p._p.xpath(".//pic:pic")]
    heights = [p._p.xpath(".//wp:extent/@cy")[0] for p in pictures]
    breaks = [bool(p.paragraph_format.page_break_before) for p in pictures]
    assert breaks == [False, False, True, True]
    assert int(heights[0]) + int(heights[1]) <= Inches(7.9)  # both fit one 9.5 in page


def test_text_and_table_that_followed_pictures_in_the_source_follow_them_again(storage):
    from app.monthly_report_model import AnchoredTable
    from app.monthly_report_library import _report_table_from_dict
    from app.monthly_report_asset_review import approve_all_assets
    from dataclasses import asdict
    assets = {"register.png": png((600, 800))}
    assets_list = AnchoredTable(("Equipment", "Status"), (("Chiller", "Covered"),), "src:1",
                                "Covered equipment list", "Status snapshot note")
    assert _report_table_from_dict(asdict(assets_list)) == assets_list
    draft = synthetic_draft(PROFILE, ReportPeriod(2026, 10))
    first = approve_all_assets(replace(
        draft.blocks[0], text="Training summary\nStatus snapshot note\nCovered equipment list",
        asset_hashes=tuple(assets), asset_captions=("Course register",), extra_tables=(assets_list,)))
    draft = replace(draft, blocks=(first, *draft.blocks[1:]))
    output = Document(BytesIO(assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint,
                                            asset_loader=assets.__getitem__)))
    order = []
    for node in output.element.body:
        text = "".join(node.xpath(".//w:t/text()")).strip()
        if node.xpath(".//pic:pic"):
            order.append("picture")
        elif node.tag == qn("w:tbl") and text.startswith("Equipment"):
            order.append("table")
        elif text in ("Training summary", "Course register", "Status snapshot note", "Covered equipment list"):
            order.append(text)
    assert order == ["Training summary", "picture", "Course register", "Status snapshot note",
                     "Covered equipment list", "table"]
