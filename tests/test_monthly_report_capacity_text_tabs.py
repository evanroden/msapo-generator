"""Capacity TXT tabs preserve physical cells through review, save, and output.

All inputs and storage are synthetic. AppTest emits the native file picker and
injects only its selected-file transport; it is not real-browser acceptance.
Word assertions inspect actual generated cells. PDF conversion uses the
existing LibreOffice capability gate and never an external document reader.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_capacity as capacity
from app import monthly_report_directory as directory, monthly_report_library as library
from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock, default_sections
from app.monthly_report_sources import source_bytes
from tests.conftest import requires_libreoffice


HEADERS = ("Facility", "Service", "Required capacity", "Available capacity", "Units")
LEADING_BLANK = (
    b"Facility\tService\tRequired capacity\tAvailable capacity\tUnits\n"
    b"\tSteam\t40000\t50000\tlb/hr\n"
)
EXPECTED = (("", "Steam", "40000", "50000", "lb/hr"),)
SOUTH = Facility("south", "Synthetic South Site", ("SH",))


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    facility = Facility("north", "Synthetic North Site", ("NH",))
    result = ReportProfile(
        "Synthetic Tab Capacity Contract", "north", "Synthetic North Site",
        (facility,),
    )
    directory.save_directory(
        result.contract,
        tuple(directory.DirectorySite(site.key, site.title, site.aliases) for site in (facility, SOUTH)),
        expected_revision=0, actor="Synthetic Reviewer", confirmed=True,
    )
    return result


def inspected(profile, raw):
    result = capacity.inspect_capacity(profile, "synthetic-capacity.txt", raw)
    assert result.content.source.sha256 == sha256(raw).hexdigest()
    assert source_bytes(profile, result.content.source) == raw
    return result


def test_blank_site_keeps_each_measure_in_its_source_column(profile):
    result = inspected(profile, LEADING_BLANK)
    assert len(result.tables) == 1
    table = result.tables[0]
    assert table.columns == HEADERS
    assert table.rows == (("", "Steam", "40000", "50000", "lb/hr"),)
    assert table.site_keys == ("",)


def test_two_leading_empty_cells_are_not_removed(profile):
    raw = (
        b"Facility\tService\tRequired capacity\tAvailable capacity\tUnits\n"
        b"\t\t40000\t50000\tlb/hr\n"
    )
    table, = inspected(profile, raw).tables
    assert table.columns == HEADERS
    assert table.rows == (("", "", "40000", "50000", "lb/hr"),)


def test_blank_required_value_does_not_take_available_value(profile):
    raw = b"Required capacity\tAvailable capacity\tFacility\n\t50000\tNH\n"
    table, = inspected(profile, raw).tables
    assert table.rows == (("", "50000", "NH"),)
    assert table.site_keys == ("north",)


def test_single_value_row_with_blank_site_stays_reviewable(profile):
    result = inspected(profile, b"Facility\tCapacity\n\t200\n")
    assert len(result.tables) == 1
    assert result.tables[0].rows == (("", "200"),)
    assert result.tables[0].site_keys == ("",)
    assert result.pending_pages == ()


def test_blank_first_heading_retains_physical_column_identity(profile):
    raw = (
        b"\tFacility\tRequired capacity\tAvailable capacity\n"
        b"East plant\tNH\t40000\t50000\n"
    )
    table, = inspected(profile, raw).tables
    assert table.columns == ("", "Facility", "Required capacity", "Available capacity")
    assert table.rows == (("East plant", "NH", "40000", "50000"),)
    assert table.site_column == 1
    assert table.site_keys == ("north",)


def test_short_blank_site_row_does_not_drop_itself_and_following_row(profile):
    raw = b"Facility\tCapacity\nNH\t100\n\t200\nNH\t300\n"
    result = inspected(profile, raw)
    assert len(result.tables) == 1
    assert result.tables[0].rows == (("NH", "100"), ("", "200"), ("NH", "300"))
    assert result.tables[0].site_keys == ("north", "", "north")


def test_spaces_around_tab_delimiters_preserve_blank_cells(profile):
    raw = b" Facility \t Capacity \t Units \n \t 200 \t tons \n"
    table, = inspected(profile, raw).tables
    assert table.columns == ("Facility", "Capacity", "Units")
    assert table.rows == (("", "200", "tons"),)


def test_site_review_save_and_reopen_keep_source_measure_positions(profile):
    result = inspected(profile, LEADING_BLANK)
    original = result.tables[0]
    # This is the public save API after the normal UI site-key selection. It
    # does not fabricate a Facility cell or change any imported source value.
    reviewed = (replace(original, site_keys=("north",)),)
    capacity.save_capacity(
        profile, reviewed, expected_revision=0, actor="Synthetic Reviewer",
        reviewed_fingerprint=capacity.review_fingerprint(reviewed),
    )
    loaded = capacity.load_capacity(profile.contract)
    block = capacity.capacity_block(profile, loaded)
    assert source_bytes(profile, result.content.source) == LEADING_BLANK
    assert loaded.revision == 1
    assert loaded.tables[0].rows == (("", "Steam", "40000", "50000", "lb/hr"),)
    assert block.extra_tables[0].rows == loaded.tables[0].rows


@pytest.mark.parametrize(("raw", "columns", "rows"), [
    (
        b"Facility\tCapacity\tUnits\nNH\t200\ttons\n",
        ("Facility", "Capacity", "Units"), (("NH", "200", "tons"),),
    ),
    (
        b"Facility\tCapacity\tUnits\nNH\t200\t\n",
        ("Facility", "Capacity", "Units"), (("NH", "200", ""),),
    ),
    (
        b"Facility\tRequired capacity\tAvailable capacity\nNH\t\t200\n",
        ("Facility", "Required capacity", "Available capacity"),
        (("NH", "", "200"),),
    ),
    (
        b"| Facility | Capacity | Units |\n| NH | 200 | tons |\n",
        ("Facility", "Capacity", "Units"), (("NH", "200", "tons"),),
    ),
    (
        b"Facility  Capacity  Units\nNH  200  tons\n",
        ("Facility", "Capacity", "Units"), (("NH", "200", "tons"),),
    ),
    (
        b"Facility\tCapacity\n\t\t\nNH\t200\n",
        ("Facility", "Capacity"), (("NH", "200"),),
    ),
])
def test_existing_ordinary_and_non_tab_tables_remain_unchanged(profile, raw, columns, rows):
    table, = inspected(profile, raw).tables
    assert table.columns == columns
    assert table.rows == rows
    assert table.site_keys == ("north",)


@pytest.mark.parametrize(("raw", "columns", "rows", "site_column", "sites"), [
    (
        b"\tFacility\tCapacity\t\nPlant A\tNH\t200\t\n",
        ("", "Facility", "Capacity", ""), (("Plant A", "NH", "200", ""),), 1, ("north",),
    ),
    (
        b"\t\tFacility\tCapacity\nPlant A\tBoiler room\tNH\tNR\n",
        ("", "", "Facility", "Capacity"), (("Plant A", "Boiler room", "NH", "NR"),), 2, ("north",),
    ),
    (
        b"Facility\tCapacity\t\nNH\t0\t\n",
        ("Facility", "Capacity", ""), (("NH", "0", ""),), 0, ("north",),
    ),
    (
        b"Facility\tService\tRequired capacity\tAvailable capacity\tUnits\r\n\tSteam\t0\tNR\tlb/hr\r\n",
        HEADERS, (("", "Steam", "0", "NR", "lb/hr"),), 0, ("",),
    ),
    (
        b"Facility\tService\tRequired capacity\tAvailable capacity\tUnits\n\tSteam\t40,000.50\t\tlb/hr\t\n",
        (*HEADERS, ""), (("", "Steam", "40,000.50", "", "lb/hr", ""),), 0, ("",),
    ),
    (
        b"Facility\tService\tCapacity\tUnits\nNH\tSteam  Boiler A\t200\tlb/hr\n",
        ("Facility", "Service", "Capacity", "Units"), (("NH", "Steam  Boiler A", "200", "lb/hr"),), 0, ("north",),
    ),
    (
        b"Facility\tService\tCapacity\nNH\tSteam | Boiler A\t200\n",
        ("Facility", "Service", "Capacity"), (("NH", "Steam | Boiler A", "200"),), 0, ("north",),
    ),
    (
        b"Facility\tCapacity\tUnits\nNH\t0\t\n \t \t \nNH\tNR\t\n",
        ("Facility", "Capacity", "Units"), (("NH", "0", ""), ("NH", "NR", "")), 0, ("north", "north"),
    ),
])
def test_tab_cell_boundaries_and_literal_values(profile, raw, columns, rows, site_column, sites):
    result = inspected(profile, raw)
    table, = result.tables
    assert table.columns == columns
    assert table.rows == rows
    assert table.site_column == site_column
    assert table.site_keys == sites
    assert not result.pending_pages and not result.used_reader


@pytest.mark.parametrize("indent,tail", [("   ", "   "), ("\t", "\t"), (" \t ", " \t ")])
def test_indented_bordered_pipe_tables_keep_their_existing_columns(profile, indent, tail):
    raw = (indent + "| Facility | Capacity | Units |" + tail + "\n" +
           indent + "| NH | 200 | tons |" + tail + "\n").encode()
    table, = inspected(profile, raw).tables
    assert table.columns == ("Facility", "Capacity", "Units")
    assert table.rows == (("NH", "200", "tons"),)
    assert table.site_keys == ("north",)


def test_established_tab_table_keeps_pipe_only_middle_cell_in_its_column(profile):
    raw = b"Facility\tCapacity\tNotes\n\t|200|\t\n"
    table, = inspected(profile, raw).tables
    assert table.columns == ("Facility", "Capacity", "Notes")
    assert table.rows == (("", "|200|", ""),)
    assert table.site_keys == ("",)


@pytest.mark.parametrize("pipe_first", [False, True])
def test_existing_caption_separator_resets_table_format(profile, pipe_first):
    tabbed = b"Facility\tCapacity\tUnits\n\t200\ttons\n"
    piped = b"\t| Facility | Capacity | Units |\t\n\t| NH | 100 | tons |\t\n"
    parts = (piped, tabbed) if pipe_first else (tabbed, piped)
    result = inspected(profile, b"Source caption\n".join(parts))
    assert len(result.tables) == 2
    expected = ((("NH", "100", "tons"),), (("", "200", "tons"),))
    if not pipe_first:
        expected = tuple(reversed(expected))
    assert tuple(table.rows for table in result.tables) == expected
    assert all(table.columns == ("Facility", "Capacity", "Units") for table in result.tables)


@pytest.mark.parametrize("position", ["before", "after"])
def test_tab_indented_title_or_caption_is_not_a_pipe_data_row(profile, position):
    piped = b"\t| Facility | Capacity | Units |\t\n\t| NH | 200 | tons |\t\n"
    caption = b"\tThermal capacity\n" if position == "before" else b"\tCapacity measured this month\n"
    table, = inspected(profile, caption + piped if position == "before" else piped + caption).tables
    assert table.columns == ("Facility", "Capacity", "Units")
    assert table.rows == (("NH", "200", "tons"),)
    assert table.site_keys == ("north",)


@pytest.mark.parametrize("separator", [" | ", "  "])
@pytest.mark.parametrize("position", ["before", "after"])
def test_legacy_text_table_titles_and_captions_do_not_become_data(profile, separator, position):
    body = (separator.join(("Facility", "Capacity", "Units")) + "\n" +
            separator.join(("NH", "200", "tons")) + "\n").encode()
    caption = b"\tThermal capacity\n" if position == "before" else b"\tCapacity measured this month\n"
    table, = inspected(profile, caption + body if position == "before" else body + caption).tables
    assert table.columns == ("Facility", "Capacity", "Units")
    assert table.rows == (("NH", "200", "tons"),)
    assert table.site_keys == ("north",)


@pytest.mark.parametrize(("raw", "columns", "row", "site_column"), [
    (b"\tCapacity\nNH\t200\n", ("", "Capacity"), ("NH", "200"), 0),
    (b"Capacity\t\n200\tNH\n", ("Capacity", ""), ("200", "NH"), 1),
])
def test_single_populated_heading_keeps_its_physical_empty_cell(profile, raw, columns, row, site_column):
    table, = inspected(profile, raw).tables
    assert table.columns == columns
    assert table.rows == (row,)
    assert table.site_column == site_column
    assert table.site_keys == ("north",)


def _reviewed_save(profile, inspection, site_keys, *, revision=0):
    tables = tuple(replace(table, site_keys=keys) for table, keys in zip(inspection.tables, site_keys))
    state = capacity.save_capacity(profile, tables, expected_revision=revision,
        actor="Synthetic Reviewer", reviewed_fingerprint=capacity.review_fingerprint(tables))
    return state, tables


def _draft(profile, block=None):
    sections = tuple(section for section in default_sections() if section.key == "scorecards")
    return ReportDraft(profile, ReportPeriod(2026, 11), "Synthetic Reviewer", sections,
                       (block or ResolvedBlock("thermal_capacity", "Library"),))


def _assert_word_cells(raw):
    document = Document(BytesIO(raw))
    table, = document.tables
    assert tuple(cell.text for cell in table.rows[0].cells) == HEADERS
    assert tuple(tuple(cell.text for cell in row.cells) for row in table.rows[1:]) == EXPECTED


def _native_word(report, tmp_path):
    from app.monthly_report_docx import assemble_docx
    from app.monthly_report_native_layout import build_native_docx

    # Keep normal deterministic output validation in front of native rendering.
    assemble_docx(report, acknowledged_fingerprint=report.fingerprint)
    document = Document()
    document.add_paragraph(report.profile.facilities[0].title)
    document.add_paragraph("November 2026")
    document.add_heading("4 MONTHLY SCORECARDS", 1)
    document.add_heading("Thermal Services Requirements and Capacity", 2)
    table = document.add_table(rows=2, cols=len(HEADERS))
    for row, values in zip(table.rows, (HEADERS, ("Old site", "Old service", "1", "2", "old units"))):
        for cell, value in zip(row.cells, values):
            cell.text = value
    path = tmp_path / "synthetic-capacity-design.docx"
    document.save(path)
    original = path.read_bytes()
    raw = build_native_docx(report, path, section_key="scorecards")
    assert path.read_bytes() == original
    return raw


APP = '''
import streamlit as st
from app.monthly_report_capacity_ui import render_capacity
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
draft = st.session_state['draft']
block = next(block for block in draft.blocks if block.key == 'thermal_capacity')
draft, block = render_capacity(draft, block, 'capacity_tabs', field)
st.session_state['draft'] = draft
st.session_state['block'] = block
'''


def _app(report):
    app = AppTest.from_string(APP, default_timeout=20)
    app.session_state["draft"] = report
    return app.run()


def test_native_site_selection_first_fill_reopen_and_word_keep_empty_site_cell(profile, tmp_path, monkeypatch):
    from app import monthly_report_ai as ai, monthly_report_capacity_ui as ui
    from app.monthly_report_docx import assemble_docx

    def forbidden(*args, **kwargs):
        pytest.fail("Native capacity text must not call an external reader")

    monkeypatch.setattr(ai, "reserve_call", forbidden)
    monkeypatch.setattr(ai, "request_json", forbidden)
    upload = BytesIO(LEADING_BLANK)
    upload.name = "synthetic-capacity-tabs.txt"
    uploads = [upload]
    native_uploader = ui.st.file_uploader

    def selected_file(label, *args, **kwargs):
        value = native_uploader(label, *args, **kwargs)
        return uploads[0] if label == "Thermal capacity file" else value

    monkeypatch.setattr(ui.st, "file_uploader", selected_file)
    app = _app(_draft(profile))
    assert not app.exception
    picker, = [widget for widget in app.get("file_uploader") if widget.label == "Thermal capacity file"]
    picker_id = picker.id
    assert capacity.load_capacity(profile.contract) is None
    selector, = [widget for widget in app.selectbox if widget.label.startswith("Site for ")]
    selector.select(profile.facilities[0].title).run()
    assert not app.exception
    saved = capacity.load_capacity(profile.contract)
    assert saved.revision == 1
    assert saved.tables[0].site_keys == ("north",)
    current = app.session_state["draft"]
    source = app.session_state["capacity_tabs_capacity_inspection"].content.source
    assert source_bytes(profile, source) == LEADING_BLANK
    app.run()
    assert not app.exception
    assert next(widget for widget in app.get("file_uploader") if widget.label == "Thermal capacity file").id == picker_id
    assert capacity.load_capacity(profile.contract) == saved
    assert app.session_state["draft"] == current
    snapshot = library.save_snapshot(current, expected_revision=0, entered_editor=current.prepared_by)
    reopened = library.load_snapshot(profile.contract, profile.key, current.period).draft
    assert reopened == current
    uploads[0] = None
    fresh = _app(reopened)
    fresh.run()
    assert not fresh.exception
    assert fresh.session_state["draft"] == reopened
    assert capacity.load_capacity(profile.contract) == saved
    # Run the complete UI/storage/output path before checking the desired cells;
    # the failing-before version therefore demonstrates actual wrong Word output.
    plain = assemble_docx(reopened, acknowledged_fingerprint=reopened.fingerprint)
    native = _native_word(reopened, tmp_path)
    _assert_word_cells(plain)
    _assert_word_cells(native)
    assert saved.tables[0].rows == EXPECTED
    assert saved.tables[0].source_sha256 == sha256(LEADING_BLANK).hexdigest()
    assert capacity.load_capacity(profile.contract, 1) == saved
    assert library.load_snapshot_version(profile.contract, profile.key, current.period, 1) == snapshot
    assert source_bytes(profile, source) == LEADING_BLANK


def test_reviewed_correction_preserves_other_site_pins_history_and_revision_guard(profile):
    raw = LEADING_BLANK + b"SH\tChilled water\t800\tNR\ttons\n"
    inspection = inspected(profile, raw)
    original, _ = _reviewed_save(profile, inspection, (("north", "south"),))
    north = _draft(profile, capacity.capacity_block(profile, original))
    snapshot = library.save_snapshot(north, expected_revision=0)
    revised_raw = LEADING_BLANK.replace(b"40000", b"42000")
    revised = inspected(profile, revised_raw)
    reviewed = (replace(revised.tables[0], site_keys=("north",)),)
    assert capacity.first_fill_tables(original, reviewed) == ()
    with pytest.raises(library.RevisionConflict):
        capacity.save_capacity(profile, reviewed, expected_revision=0, actor="Synthetic Reviewer",
            reviewed_fingerprint=capacity.review_fingerprint(reviewed))
    assert capacity.load_capacity(profile.contract) == original
    changed = capacity.save_capacity(profile, reviewed, expected_revision=1, actor="Synthetic Reviewer",
        reviewed_fingerprint=capacity.review_fingerprint(reviewed))
    assert changed.revision == 2
    assert capacity.capacity_block(profile, changed).extra_tables[0].rows == (("", "Steam", "42000", "50000", "lb/hr"),)
    south = replace(profile, key="south", title=SOUTH.title, facilities=(SOUTH,))
    assert capacity.capacity_block(south, changed).extra_tables[0].rows == (("SH", "Chilled water", "800", "NR", "tons"),)
    assert capacity.resolve_capacity(north) is north
    assert north.blocks[0].extra_tables[0].rows == EXPECTED
    assert capacity.load_capacity(profile.contract, 1) == original
    assert library.load_snapshot(profile.contract, profile.key, north.period) == snapshot
    assert source_bytes(profile, inspection.content.source) == raw
    assert source_bytes(profile, revised.content.source) == revised_raw


def test_duplicate_reviewed_blank_site_measurements_still_require_resolution(profile):
    result = inspected(profile, LEADING_BLANK + b"\tSteam\t40000\t50000\tlb/hr\n")
    table, = result.tables
    assert table.rows == EXPECTED * 2
    reviewed = (replace(table, site_keys=("north", "north")),)
    with pytest.raises(ValueError, match="same site and labels"):
        capacity.save_capacity(profile, reviewed, expected_revision=0, actor="Synthetic Reviewer",
            reviewed_fingerprint=capacity.review_fingerprint(reviewed))
    assert capacity.load_capacity(profile.contract) is None
    assert source_bytes(profile, result.content.source) == LEADING_BLANK + b"\tSteam\t40000\t50000\tlb/hr\n"


@requires_libreoffice
def test_native_pdf_retains_measure_positions_and_original_source(profile, tmp_path, monkeypatch):
    import pymupdf as fitz
    from app import pdf_converter

    inspection = inspected(profile, LEADING_BLANK)
    saved, _ = _reviewed_save(profile, inspection, (("north",),))
    report = _draft(profile, capacity.capacity_block(profile, saved))
    raw = _native_word(report, tmp_path)
    _assert_word_cells(raw)
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    path = tmp_path / "synthetic-capacity-tabs.docx"
    path.write_bytes(raw)
    pdf_bytes = pdf_converter.convert_to_pdf(path).read_bytes()
    target = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path))) / "capacity-text-tabs"
    target.mkdir(parents=True, exist_ok=True)
    (target / "capacity.docx").write_bytes(raw)
    (target / "capacity.pdf").write_bytes(pdf_bytes)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
        assert "Steam 40000 50000 lb/hr" in text
        assert "Old service" not in text and "old units" not in text
        for number, page in enumerate(document, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(target / f"capacity-page-{number}.png")
        pages = len(document)
    (target / "manifest.json").write_text(json.dumps({
        "synthetic_only": True, "pages": pages, "source_sha256": inspection.content.source.sha256,
        "docx_sha256": sha256(raw).hexdigest(), "pdf_sha256": sha256(pdf_bytes).hexdigest(),
        "scenario": "reviewed tab-separated capacity with blank Facility cell",
    }, indent=2))
    assert source_bytes(profile, inspection.content.source) == LEADING_BLANK
    assert capacity.load_capacity(profile.contract) == saved


