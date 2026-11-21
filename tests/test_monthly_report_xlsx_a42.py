"""A42 bounded synthetic XLSX source and capacity extraction regressions.

No client workbook, model execution, or production state is used.
"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from app import monthly_report_capacity as capacity
from app import monthly_report_directory as directory
from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportProfile


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = ReportProfile(
        "A42 Synthetic Contract", "plants", "Synthetic thermal plants",
        (Facility("north", "North Hospital", ("NH",)),
         Facility("south", "South Hospital", ("SH",))),
        scope_type="multi_site",
    )
    directory.save_directory(
        profile.contract,
        (directory.DirectorySite("north", "North Hospital", ("NH",)),
         directory.DirectorySite("south", "South Hospital", ("SH",))),
        expected_revision=0, actor="Synthetic reviewer", confirmed=True,
    )
    return profile


def _workbook(*, cached=False):
    book = Workbook()
    north = book.active
    north.title = "North capacity"
    north.append(("Facility", "Service", "Required capacity", "Available capacity"))
    north.append(("NH", "Chilled water", 0, -12))
    north.append(("NH", "Steam", "=3*7", 55))
    north["C2"].number_format = '#,##0 "tons"'
    north["D2"].number_format = '#,##0 "tons"'
    hidden = book.create_sheet("South archive")
    hidden.sheet_state = "veryHidden"
    hidden.append(("Facility", "Service", "Required capacity", "Available capacity"))
    hidden.append(("SH", "Steam", 800, 900))
    south = book.create_sheet("South capacity")
    south.append(("Facility", "Service", "Required capacity", "Available capacity"))
    south.append(("SH", "Chilled water", 125, 175))
    output = BytesIO()
    book.save(output)
    raw = output.getvalue()
    if not cached:
        return raw
    amended = BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(amended, "w") as result:
        for part in original.infolist():
            data = original.read(part.filename)
            if part.filename == "xl/worksheets/sheet1.xml":
                old = b"<f>3*7</f><v></v>"
                assert old in data
                data = data.replace(old, b"<f>3*7</f><v>21</v>", 1)
            result.writestr(part, data)
    return amended.getvalue()


def test_source_retains_hidden_provenance_and_exact_unavailable_cell(profile):
    raw = _workbook()
    content, attachments = sources.ingest(profile, "technical.xlsx", raw)
    assert attachments == ()
    assert sources.source_bytes(profile, content.source) == raw
    assert [table.name for table in content.tables] == [
        "North capacity", "South archive", "South capacity"
    ]
    assert content.tables[1].hidden is True
    assert content.tables[0].hidden is False
    assert content.tables[0].missing_formula_cache_cells == ("C3",)
    assert content.tables[0].rows[0][2:] == ("0", "-12")
    assert content.tables[0].rows[1][2:] == ("", "55")
    assert any("North capacity!C3" in notice for notice in content.source.notices)
    assert any("South archive" in notice and "Hidden" in notice for notice in content.source.notices)
    reloaded, _ = sources.ingest(profile, "technical.xlsx", raw)
    assert reloaded == content


def test_cached_formula_is_read_but_never_evaluated(profile):
    raw = _workbook(cached=True)
    content, _ = sources.ingest(profile, "cached.xlsx", raw)
    assert content.tables[0].rows[1][2] == "21"
    assert content.tables[0].missing_formula_cache_count == 0
    assert sources.source_bytes(profile, content.source) == raw


def test_capacity_has_exact_formula_notice_and_separates_sites(profile):
    raw = _workbook()
    result = capacity.inspect_capacity(profile, "thermal.xlsx", raw)
    assert len(result.tables) == 2
    assert [table.site_keys for table in result.tables] == [
        ("north", "north"), ("south",)
    ]
    assert result.tables[0].rows[0][2:] == ("0 tons", "-12 tons")
    assert result.tables[0].rows[1][2:] == ("", "55")
    assert any("North capacity!C3" in notice for notice in result.notices)
    assert any("South archive" in notice for notice in result.notices)
    assert sources.source_bytes(profile, result.content.source) == raw


def test_sheet_budget_applies_to_both_import_routes(profile):
    book = Workbook()
    book.active.title = "Plant 1"
    book.active.append(("Site", "Capacity"))
    book.active.append(("NH", 5))
    for index in range(2, 32):
        sh = book.create_sheet(f"Plant {index}")
        sh.append(("Site", "Capacity"))
        sh.append(("SH", 10))
    def raw():
        stream = BytesIO()
        book.save(stream)
        return stream.getvalue()
    with pytest.raises(ValueError, match="30 worksheets"):
        sources._spreadsheet(raw(), ".xlsx")
    with pytest.raises(ValueError, match="30 worksheets"):
        capacity.inspect_capacity(profile, "31-sheets.xlsx", raw())
    book.remove(book.worksheets[-1])
    assert len(sources._spreadsheet(raw(), ".xlsx")) == 30
    assert len(capacity.inspect_capacity(profile, "30-sheets.xlsx", raw()).content.source.page_texts) == 30


def test_bad_workbook_does_not_mutate_saved_capacity(profile):
    with pytest.raises(ValueError):
        capacity.inspect_capacity(profile, "malformed.xlsx", b"not a zip")
    with pytest.raises(ValueError):
        sources.ingest(profile, "malformed.xlsx", b"not a zip")


def test_hidden_rows_require_review_instead_of_automatic_capital_or_activity(profile):
    from app.monthly_report_structured_uploads import mapped_rows, native_update, reader_sources
    book = Workbook()
    book.active.append(("Notice",))
    book.active.append(("This is a visible synthetic cover",))
    hidden = book.create_sheet("Private historical capital")
    hidden.sheet_state = "hidden"
    hidden.append(("Facility", "Priority", "Recommendation"))
    hidden.append(("South Hospital", "High", "Old synthetic quote"))
    stream = BytesIO()
    book.save(stream)
    raw = stream.getvalue()
    content, _ = sources.ingest(profile, "hidden-capital.xlsx", raw)
    assert content.tables[1].hidden
    assert content.tables[1].rows[0][2] == "Old synthetic quote"
    assert mapped_rows(content, "capital_renewal") == ()
    assert reader_sources((content,), "activity_summary") == ()
    assert native_update((content,), "activity_summary").text == ""
    assert sources.source_bytes(profile, content.source) == raw


def test_cell_budget_accepts_200000_grid_cells_and_rejects_excess():
    # Exercise the real limit rather than patching its value. Identical
    # zero cells are intentionally nonempty; zeros cannot be dropped as NR.
    book = Workbook()
    sheet = book.active
    sheet.title = "Synthetic measurements"
    row = [0] * 20
    for _ in range(10_000):
        sheet.append(row)
    stream = BytesIO()
    book.save(stream)
    table, = sources._spreadsheet(stream.getvalue(), ".xlsx")
    assert len(table.columns) == 20
    assert len(table.rows) == 9_999
    assert table.rows[-1] == tuple("0" for _ in range(20))

    sheet.append(row)  # 200,020 physical cells exceeds the 200,000 cap.
    stream = BytesIO()
    book.save(stream)
    with pytest.raises(ValueError, match="review budget"):
        sources._spreadsheet(stream.getvalue(), ".xlsx")


def test_same_filename_replaced_source_has_distinct_cache_and_bytes(profile):
    original = _workbook(cached=False)
    replacement = _workbook(cached=True)
    first, _ = sources.ingest(profile, "stable-name.xlsx", original)
    second, _ = sources.ingest(profile, "stable-name.xlsx", replacement)
    assert first.source.id != second.source.id
    assert first.tables[0].rows[1][2] == ""
    assert second.tables[0].rows[1][2] == "21"
    assert sources.source_bytes(profile, first.source) == original
    assert sources.source_bytes(profile, second.source) == replacement


def test_reviewed_capacity_snapshot_round_trips_without_hidden_site(profile):
    from dataclasses import replace
    raw = _workbook(cached=True)
    inspection = capacity.inspect_capacity(profile, "approved-capacity.xlsx", raw)
    approved = replace(
        inspection.tables[0],
        rows=inspection.tables[0].rows[:1],
        site_keys=inspection.tables[0].site_keys[:1],
    )
    state = capacity.save_capacity(
        profile, (approved,), expected_revision=0, actor="Synthetic Reviewer",
        reviewed_fingerprint=capacity.review_fingerprint((approved,)),
    )
    loaded = capacity.load_capacity(profile.contract)
    assert loaded == state
    assert loaded.revision == 1
    assert loaded.tables[0].rows[0][2:] == ("0 tons", "-12 tons")
    assert {site for table in loaded.tables for site in table.site_keys} == {"north"}
    assert sources.source_bytes(profile, inspection.content.source) == raw


def test_uncached_capacity_formula_is_visible_and_not_autosaved(profile, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_capacity_ui as ui
    from test_monthly_report_capacity import draft

    APP = """
import streamlit as st
from app.monthly_report_capacity_ui import render_capacity
def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
draft = st.session_state['test_draft']
block = next(b for b in draft.blocks if b.key == 'thermal_capacity')
draft, block = render_capacity(draft, block, 'test', field)
st.session_state['test_draft'] = draft
"""
    uploaded = BytesIO(_workbook(cached=False))
    uploaded.name = "uncached-capacity.xlsx"
    monkeypatch.setattr(ui.st, "file_uploader", lambda *args, **kwargs: uploaded)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = draft(profile)
    app.run()
    assert not app.exception
    assert any("North capacity!C3" in str(warning.proto) for warning in app.warning)
    assert any("correct their values" in str(message.proto) for message in app.info)
    assert capacity.load_capacity(profile.contract) is None
    assert any("Apply reviewed capacity" in button.label for button in app.button)
