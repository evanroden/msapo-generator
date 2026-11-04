"""Keep pipe-table headers and data across Markdown alignment rules."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest

from app import monthly_report_capacity as capacity
from app import monthly_report_directory as directory, monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_docx import _build_docx
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock, default_sections,
)


COLUMNS = ("Facility", "Service", "Required capacity", "Available capacity", "Units")
NORTH = ("North Hospital", "Steam", "40000", "50000", "lb/hr")
SOUTH = ("South Hospital", "Chilled water", "0", "NR", "tons")


def pipe_row(cells, border=True):
    line = " | ".join(cells)
    return "| " + line + " |" if border else line


def text_table(rows=(NORTH, SOUTH), *, alignment="---", border=True):
    return "\n".join((pipe_row(COLUMNS, border),
                      pipe_row((alignment,) * len(COLUMNS), border),
                      *(pipe_row(row, border) for row in rows)))


@pytest.mark.parametrize("border", [True, False])
@pytest.mark.parametrize("alignment", ["---", ":---", "---:", ":---:"])
@pytest.mark.parametrize("indent", ["", "\t  "])
def test_pipe_alignment_keeps_exact_header_and_first_and_following_rows(border, alignment, indent):
    text = "\n".join(indent + line for line in text_table(border=border, alignment=alignment).splitlines())
    table, = capacity._text_tables(text, "Synthetic")
    assert table.columns == COLUMNS
    assert table.rows == (NORTH, SOUTH)


def test_alignment_rules_do_not_merge_distinct_tables_or_promote_first_data_row():
    steam = text_table((NORTH,))
    cooling_columns = ("Facility", "Cooling capacity", "Units", "Qualifier")
    cooling_row = ("South Hospital", "0", "tons", "Not measured")
    cooling = "\n".join((pipe_row(cooling_columns),
                          pipe_row(("---",) * 4), pipe_row(cooling_row)))
    tables = capacity._text_tables(steam + "\nSeparate source table\n" + cooling, "Synthetic")
    assert [(table.columns, table.rows) for table in tables] == [
        (COLUMNS, (NORTH,)), (cooling_columns, (cooling_row,)),
    ]
    assert [table.name for table in tables] == ["Synthetic / table 1", "Synthetic / table 2"]


@pytest.mark.parametrize("delimiter", [" | ", "\t", "  "])
def test_existing_tables_without_alignment_keep_their_cells(delimiter):
    text = "\n".join(delimiter.join(row) for row in (COLUMNS, NORTH, SOUTH))
    table, = capacity._text_tables(text, "Synthetic")
    assert table.columns == COLUMNS
    assert table.rows == (NORTH, SOUTH)


def test_actual_dash_values_remain_data_and_prose_still_separates_groups():
    missing = ("North Hospital", "Steam", "---", "---", "lb/hr")
    text = "\n".join(map(pipe_row, (COLUMNS, missing)))
    text += "\nNot part of either table\n" + "\n".join(map(pipe_row, (COLUMNS, SOUTH)))
    first, second = capacity._text_tables(text, "Synthetic")
    assert first.rows == (missing,)
    assert second.rows == (SOUTH,)


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    north = Facility("north", "North Hospital")
    south = Facility("south", "South Hospital")
    profile = ReportProfile("Synthetic Pipe Capacity", "north", "North Hospital", (north,))
    directory.save_directory(
        profile.contract, tuple(directory.DirectorySite(f.key, f.title) for f in (north, south)),
        expected_revision=0, actor="Synthetic Reviewer", confirmed=True,
    )
    return profile


def save(profile, tables, revision=0):
    return capacity.save_capacity(
        profile, tables, expected_revision=revision, actor="Synthetic Reviewer",
        reviewed_fingerprint=capacity.review_fingerprint(tables),
    )


def test_public_txt_import_save_reopen_and_word_keep_rows_scope_and_history(profile):
    raw = text_table().encode()
    inspection = capacity.inspect_capacity(profile, "synthetic-capacity.txt", raw)
    table, = inspection.tables
    assert table.columns == COLUMNS
    assert table.rows == (NORTH, SOUTH)
    assert table.site_keys == ("north", "south")
    assert not inspection.pending_pages
    assert sources.source_bytes(profile, inspection.content.source) == raw

    state = save(profile, capacity.first_fill_tables(None, inspection.tables))
    assert capacity.load_capacity(profile.contract) == state
    assert capacity.load_capacity(profile.contract, 1) == state
    block = capacity.capacity_block(profile, state)
    assert block.extra_tables[0].columns == COLUMNS
    assert block.extra_tables[0].rows == (NORTH,)
    south_profile = replace(profile, key="south", title="South Hospital",
                            facilities=(Facility("south", "South Hospital"),))
    assert capacity.capacity_block(south_profile, state).extra_tables[0].rows == (SOUTH,)
    assert capacity.capacity_block(replace(profile, contract="Other Synthetic Contract")) is None

    section = next(section for section in default_sections() if section.key == "scorecards")
    period = ReportPeriod(2026, 9)
    draft = ReportDraft(profile, period, "Synthetic Reviewer", (section,), (block,), synthetic=True)
    snapshot = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Reviewer")
    assert library.load_snapshot(profile.contract, profile.key, period).draft == draft
    document = Document(BytesIO(_build_docx(draft)))
    word_rows = [tuple(cell.text for cell in row.cells) for table in document.tables for row in table.rows]
    assert COLUMNS in word_rows
    assert word_rows.count(NORTH) == 1
    assert SOUTH not in word_rows

    corrected = capacity.inspect_capacity(profile, "synthetic-correction.txt", raw.replace(b"40000", b"42000"))
    save(profile, corrected.tables, revision=1)
    assert capacity.load_capacity(profile.contract, 1) == state
    assert library.load_snapshot(profile.contract, profile.key, period) == snapshot
    assert capacity.resolve_capacity(draft) is draft
    manual = replace(draft, blocks=(ResolvedBlock("thermal_capacity", "This month", text="Retain manual note"),))
    assert capacity.resolve_capacity(manual) is manual
    assert sources.source_bytes(profile, inspection.content.source) == raw
    with pytest.raises(library.RevisionConflict):
        save(profile, inspection.tables, revision=1)


def test_unknown_site_stays_unmapped_and_cannot_be_saved(profile):
    unknown_row = ("Unreviewed Facility", *NORTH[1:])
    raw = text_table((unknown_row,)).encode()
    inspection = capacity.inspect_capacity(profile, "synthetic-unmapped.txt", raw)
    table, = inspection.tables
    assert table.rows == (unknown_row,)
    assert table.site_keys == ("",)
    with pytest.raises(ValueError, match="Match each capacity row"):
        save(profile, inspection.tables)
    assert capacity.load_capacity(profile.contract) is None
    assert sources.source_bytes(profile, inspection.content.source) == raw
