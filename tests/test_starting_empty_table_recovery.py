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
