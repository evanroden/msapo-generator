"""A74: verified synthetic DOCX capital rows must become reviewed scoped defaults.

Original native columns, source bytes, and report-only edits remain separate.
"""
from dataclasses import replace

from docx import Document
import pytest

from app import monthly_report_library as library
from app.monthly_report_capital_master import (
    capital_report_block, load_capital_master, save_capital_master, select_capital,
)
from app.monthly_report_capital_ui import reviewed_capital_items
from app.monthly_report_import import ImportMapping, imported_draft, inspect_docx, map_items
from app.monthly_report_model import (
    ColumnSpec, Facility, ReportDraft, ReportPeriod, ReportProfile, default_sections,
)
from app.monthly_report_setup import new_month_draft


PERIOD = ReportPeriod(2026, 9)
NEXT = ReportPeriod(2026, 10)


@pytest.fixture
def native(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    a = Facility("north", "Synthetic North", ("North Wing",))
    b = Facility("south", "Synthetic South", ("South Wing",))
    both = ReportProfile("A74 synthetic contract", "both", "Both", (a, b),
                         scope_type="multi_site")
    north = ReportProfile(both.contract, "north", "North", (a,))
    south = ReportProfile(both.contract, "south", "South", (b,))
    other = ReportProfile("Unrelated A74 contract", "north", "Other", (a,))
    document = Document()
    document.add_heading("9 Priority Capital Renewal List", level=1)
    table = document.add_table(rows=4, cols=6)
    cells = (
        ("Facility", "Priority", "Recommendation", "Asset", "Status", "Source note"),
        ("Synthetic North", "High", "Renew pump", "PUMP-1", "Pending", "First unit"),
        ("North Wing", "Low", "Renew pump", "PUMP-2", "Pending", "Second unit"),
        ("Synthetic South", "Medium", "Plan roof renewal", "ROOF-1", "Deferred", "Unconfirmed timing"),
    )
    for row, values in zip(table.rows, cells):
        for cell, value in zip(row.cells, values):
            cell.text = value
    original = tmp_path / "capital-source.docx"
    document.save(original)
    before = original.read_bytes()
    inspected = inspect_docx(original)
    source_table = next(item for item in inspected.items if item.kind == "table")
    imported = map_items(original, inspected, (ImportMapping(source_table.id, "capital_renewal"),))
    draft = imported_draft(both, PERIOD, "A74 synthetic reviewer", imported)
    capital = next(item for item in draft.blocks if item.key == "capital_renewal")
    assert capital.rows == cells[1:]
    assert capital.references == (f"docx:{inspected.sha256}:{source_table.id}",)
    return both, north, south, other, draft, capital, original, before


def approve(profile, rows, revision=0, removed=()):
    return save_capital_master(profile, rows, expected_revision=revision,
                               actor="A74 synthetic reviewer", confirmed=True,
                               removed_ids=removed)


def _replace_headers(draft, titles):
    return replace(draft, sections=tuple(
        replace(section, blocks=tuple(
            replace(block, columns=tuple(
                ColumnSpec(f"imported_{i}", title) for i, title in enumerate(titles)
            )) if block.key == "capital_renewal" else block
            for block in section.blocks
        )) for section in draft.sections
    ))


def test_real_native_import_maps_rows_once_and_preserves_original_schema(native):
    both, north, south, other, draft, block, path, original = native
    items, removed = reviewed_capital_items(draft, block, load_capital_master(both.contract))
    assert not removed and len(items) == 3
    assert [item.priority for item in items] == ["High", "Low", "Medium"]
    assert [item.recommendation for item in items] == [
        "Renew pump", "Renew pump", "Plan roof renewal",
    ]
    assert len({item.key for item in items}) == 3
    assert [item.site_keys for item in items] == [
        ("north",), ("north",), ("south",),
    ]
    assert items[0].asset == "PUMP-1" and items[1].asset == "PUMP-2"
    assert items[0].status == items[0].status_period == ""
    assert ("Source status (historical, not current completion)", "Pending") in items[0].extra_fields
    assert ("Source note", "Second unit") in items[1].extra_fields
    assert all(item.source_reference.startswith(block.references[0] + ":") for item in items)
    master = approve(both, items)
    assert len(select_capital(north, master, NEXT).occurrences) == 2
    assert len(select_capital(south, master, NEXT).occurrences) == 1
    assert len(select_capital(both, master, NEXT).occurrences) == 3
    with pytest.raises(ValueError, match="cross contract"):
        select_capital(other, master, NEXT)
    assert load_capital_master(other.contract).revision == 0
    assert draft.blocks[0] == block
    assert path.read_bytes() == original


def test_amended_priority_needs_explicit_confirmation_and_retains_row_identity(native):
    both, north, south, _, draft, block, path, original = native
    first_items, _ = reviewed_capital_items(draft, block, load_capital_master(both.contract))
    first = approve(both, first_items)
    edited = replace(block, rows=((block.rows[0][0], "Urgent", *block.rows[0][2:]),
                                  *block.rows[1:]))
    with pytest.raises(ValueError, match="priority changes"):
        reviewed_capital_items(draft, edited, first)
    assert load_capital_master(both.contract) == first
    changed, removed = reviewed_capital_items(
        draft, edited, first, confirm_priority_changes=True)
    assert not removed and changed[0].key == first.items[0].key
    assert changed[0].priority == "Urgent"
    assert changed[1:] == first.items[1:]
    second = approve(north, changed, revision=1)
    assert load_capital_master(both.contract, 1) == first
    assert second.items[2] == first.items[2]
    assert select_capital(south, second, NEXT).occurrences[0].item.priority == "Medium"
    assert path.read_bytes() == original


def test_unknown_site_unverified_identity_and_malformed_source_fail_closed(native):
    both, _, _, _, draft, block, path, original = native
    master = load_capital_master(both.contract)
    unknown = replace(block, rows=(("Unknown remote site", *block.rows[0][1:]), *block.rows[1:]))
    with pytest.raises(ValueError, match="selected facility"):
        reviewed_capital_items(draft, unknown, master)
    with pytest.raises(ValueError, match="source"):
        reviewed_capital_items(draft, replace(block, references=()), master)
    no_priority = _replace_headers(draft, ("Facility", "Ranking", "Recommendation",
                                          "Asset", "Status", "Source note"))
    with pytest.raises(ValueError, match="column"):
        reviewed_capital_items(no_priority, block, master)
    ambiguous = _replace_headers(draft, ("Facility", "Priority", "Priority",
                                        "Asset", "Status", "Source note"))
    with pytest.raises(ValueError, match="column"):
        reviewed_capital_items(ambiguous, block, master)
    importer_renamed_duplicate = _replace_headers(
        draft, ("Facility", "Priority", "Priority (3)", "Asset", "Status", "Source note"))
    with pytest.raises(ValueError, match="column"):
        reviewed_capital_items(importer_renamed_duplicate, block, master)
    financial = _replace_headers(draft, ("Facility", "Priority", "Recommendation",
                                        "Asset", "Cost", "Source note"))
    with pytest.raises(ValueError, match="financial|Financial|monetary"):
        reviewed_capital_items(financial, block, master)
    assert load_capital_master(both.contract).revision == 0
    assert path.read_bytes() == original


def test_approved_items_survive_save_reload_and_local_monthly_edit(native):
    both, north, south, _, draft, block, path, original = native
    rows, _ = reviewed_capital_items(draft, block, load_capital_master(both.contract))
    master = approve(both, rows)
    selected = select_capital(north, master, PERIOD)
    capital = capital_report_block(north, selected)
    modified = replace(capital, rows=(
        ("Synthetic North", "Urgent", "Report-only follow-up"), *capital.rows[1:]),
        text="Local planning note")
    section = next(section for section in default_sections() if section.key == "capital")
    report = ReportDraft(north, PERIOD, "A74 synthetic reviewer", (section,),
                         (modified,), synthetic=True)
    library.save_snapshot(report, expected_revision=0)
    restored = library.load_snapshot(north.contract, north.key, PERIOD)
    assert restored.draft == report
    rolled = new_month_draft(restored.draft, NEXT)
    assert rolled.blocks[0].rows == modified.rows
    assert rolled.blocks[0].text == "Local planning note"
    assert rolled.blocks[0].references == (master.reference,)
    assert load_capital_master(both.contract) == master
    assert capital_report_block(south, select_capital(south, master, NEXT)).rows == (
        ("Synthetic South", "Medium", "Plan roof renewal"),)
    assert path.read_bytes() == original


def test_native_approval_controls_require_review_clicks(native):
    from streamlit.testing.v1 import AppTest

    both, north, south, _, draft, block, path, original = native
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_capital_ui import render_capital_master
st.session_state["block"] = render_capital_master(
    st.session_state["draft"], st.session_state["block"], "native_a74")
""", default_timeout=25)
    app.session_state["draft"] = draft
    app.session_state["block"] = block
    app.run()
    assert not app.exception
    save = next(button for button in app.button
                if button.label == "Save approved Capital Renewal version")
    assert save.disabled
    assert load_capital_master(both.contract).revision == 0
    next(box for box in app.checkbox if box.label.startswith(
        "I reviewed these capital recommendations")).check().run()
    next(button for button in app.button
         if button.label == "Save approved Capital Renewal version").click().run()
    assert not app.exception
    first = load_capital_master(both.contract)
    assert len(first.items) == 3
    assert app.session_state["block"] == block

    edited = replace(block, rows=((block.rows[0][0], "Urgent", *block.rows[0][2:]),
                                  *block.rows[1:]))
    app.session_state["block"] = edited
    app.run()
    next(box for box in app.checkbox if box.label.startswith(
        "I reviewed these capital recommendations")).check().run()
    next(button for button in app.button
         if button.label == "Save approved Capital Renewal version").click().run()
    assert any("priority changes" in warning.value for warning in app.warning)
    assert load_capital_master(both.contract) == first
    next(box for box in app.checkbox if box.label.startswith(
        "I also confirm changes to previously approved")).check().run()
    next(button for button in app.button
         if button.label == "Save approved Capital Renewal version").click().run()
    assert not app.exception
    assert load_capital_master(both.contract).items[0].priority == "Urgent"
    assert app.session_state["block"] == edited
    assert path.read_bytes() == original


def test_new_month_source_file_reuses_unique_items_and_does_not_duplicate(native, tmp_path):
    both, north, south, _, initial, block, path, original = native
    items, _ = reviewed_capital_items(initial, block, load_capital_master(both.contract))
    first = approve(both, items)
    new_source = tmp_path / "second-month.docx"
    document = Document(path)
    document.add_paragraph("Synthetic second report source for next month")
    document.save(new_source)
    inspected = inspect_docx(new_source)
    table = next(item for item in inspected.items if item.kind == "table")
    mapped = map_items(new_source, inspected, (ImportMapping(table.id, "capital_renewal"),))
    later = imported_draft(both, NEXT, "A74 synthetic reviewer", mapped)
    later_block = next(item for item in later.blocks if item.key == "capital_renewal")
    assert later_block.references != block.references
    assert later_block.rows == block.rows
    reused, removed = reviewed_capital_items(later, later_block, first)
    assert reused == first.items and not removed
    assert approve(both, reused, revision=1) == first
    assert [item.item.key for item in select_capital(north, first, NEXT).occurrences] == [
        items[0].key, items[1].key,
    ]
    assert len(select_capital(south, first, NEXT).occurrences) == 1
    assert path.read_bytes() == original
