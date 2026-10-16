"""Removing all imported rows must make the named source recovery achievable."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import BlockSpec, ReportTable, ResolvedBlock
from app.monthly_report_start_replay import merge_starting_drafts
from tests.test_monthly_report_start_replay import draft


def table_block(rows):
    return ResolvedBlock("work_orders", "This month", extra_tables=(
        ReportTable(("Recorded", "Status"), rows, "synthetic:original-table"),))


@pytest.mark.parametrize("verified", [True, False])
def test_empty_imported_schema_is_not_populated_source_content(verified):
    previous = draft(table_block((("September", "Pending"),)))
    current = draft(table_block(()))
    result = merge_starting_drafts(current, draft(), previous, verified=verified)
    assert result == current
    assert result.blocks[0].extra_tables[0].columns == ("Recorded", "Status")
    assert result.blocks[0].extra_tables[0].reference == "synthetic:original-table"
    assert merge_starting_drafts(result, draft(), draft(), verified=verified) == result


@pytest.mark.parametrize("value", ["0", "NR", "Pending", "Not recorded"])
def test_operational_values_are_not_discarded_as_empty(value):
    current = draft(table_block((("September", value),)))
    with pytest.raises(ValueError, match="Work orders is still in this report"):
        merge_starting_drafts(current, draft(), current)
    assert current.blocks[0].extra_tables[0].rows == (("September", value),)


def test_empty_table_cannot_hide_another_populated_table():
    empty = table_block(())
    current = draft(replace(empty, extra_tables=(*empty.extra_tables,
        ReportTable(("Item",), (("Human correction",),), "synthetic:other"))))
    with pytest.raises(ValueError, match="Work orders is still in this report"):
        merge_starting_drafts(current, draft(), current)


def test_normal_editor_keeps_empty_schema_and_allows_recovery(monkeypatch):
    from app import monthly_report_guided as guided
    previous = draft(table_block((("September", "Pending"),)))
    # Simulate the grid's explicit delete-all-rows result. This exercises the
    # actual editor/model boundary, not a claim of physical-browser input.
    monkeypatch.setattr(guided, "_grid", lambda *args, **kwargs: [])
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_ui import _field
st.session_state.result = _edit_content(st.session_state.spec,
    st.session_state.block, None, "synthetic_empty_table", {}, _field)
''')
    app.session_state.spec = BlockSpec("work_orders", "table")
    app.session_state.block = previous.blocks[0]
    app.run()
    assert not app.exception
    edited = app.session_state.result
    assert edited.extra_tables and not edited.extra_tables[0].rows
    current = replace(previous, blocks=(edited,))
    assert merge_starting_drafts(current, draft(), previous) == current
    assert previous.blocks[0].extra_tables[0].rows == (("September", "Pending"),)


@pytest.mark.parametrize("changed_headings", [False, True])
def test_real_starting_table_reselection_reuses_its_cleared_slot(tmp_path, changed_headings):
    from app.monthly_report_import import inspect_docx, imported_draft
    from app.monthly_report_start_import import build_starting_import
    from app.monthly_report_start_replay import _content
    from tests.test_monthly_report_start_import import build, report_file

    path = report_file(tmp_path, contact=False, table=True)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    _analysis, selected, plans = build(path)
    source = next(block for block in selected.blocks if block.key == "work_orders")
    assert len(source.extra_tables) == 1
    table = source.extra_tables[0]
    assert table.reference.startswith(f"docx:{inspection.sha256}:")
    cleared = replace(selected, blocks=tuple(
        replace(block, extra_tables=(replace(table, rows=()),))
        if block.key == source.key else block for block in selected.blocks))

    # The next acknowledged source review omits this table. Its report-level
    # empty editor schema is retained until the writer explicitly selects it.
    plan = plans["activity"]
    plan["selected"] = [identity for identity in plan["selected"]
                        if identity != table.reference.rsplit(":", 1)[1]]
    mapped, _ = build_starting_import(path, inspection, plans.values())
    deselected = imported_draft(selected.profile, selected.period, selected.prepared_by, mapped)
    assert not any(block.key == source.key for block in deselected.blocks)
    after_omission = merge_starting_drafts(cleared, deselected, selected)
    assert after_omission == cleared

    plan["selected"].append(table.reference.rsplit(":", 1)[1])
    if changed_headings:
        plan["tables"][table.reference.rsplit(":", 1)[1]] = replace(
            table, columns=("Reporting month", "PM completed"))
    mapped, _ = build_starting_import(path, inspection, plans.values())
    reselected = imported_draft(selected.profile, selected.period, selected.prepared_by, mapped)
    result = merge_starting_drafts(after_omission, reselected, deselected)
    actual = next(block for block in result.blocks if block.key == source.key)
    expected = next(block for block in reselected.blocks if block.key == source.key)
    assert actual.extra_tables == expected.extra_tables
    assert _content(actual) == _content(expected)
    assert merge_starting_drafts(result, reselected, reselected) == result
    assert path.read_bytes() == original


@pytest.mark.parametrize("independent_reference", ["", "synthetic:other-source"])
def test_reselection_keeps_independent_empty_schema_and_populated_table(independent_reference):
    source = table_block((("September", "Pending"),))
    empty_source = replace(source.extra_tables[0], rows=())
    independent = ReportTable(("Human field",), (), independent_reference)
    populated = ReportTable(("Operational value",), (("NR",),), "synthetic:human")
    current = draft(replace(source, extra_tables=(empty_source, independent, populated)))
    result = merge_starting_drafts(current, draft(source), draft())
    actual = result.blocks[0]
    assert actual.extra_tables == (independent, populated, source.extra_tables[0])
    assert current.blocks[0].extra_tables == (empty_source, independent, populated)


def test_reselection_does_not_replace_populated_source_table_even_when_equal():
    source = table_block((("September", "Pending"),))
    human = replace(source.extra_tables[0], rows=(("September", "Completed"),))
    result = merge_starting_drafts(draft(replace(source, extra_tables=(human,))),
                                   draft(source), draft())
    assert result.blocks[0].extra_tables == (human, source.extra_tables[0])


def test_unchanged_selected_table_does_not_restore_explicitly_cleared_rows():
    selected = draft(table_block((("September", "Pending"),)))
    cleared = draft(table_block(()))
    assert merge_starting_drafts(cleared, selected, selected) == cleared
