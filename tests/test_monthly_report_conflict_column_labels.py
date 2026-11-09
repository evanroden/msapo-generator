"""Conflict comparisons retain cells when display labels collide with source headings."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import BlockSpec, ColumnSpec, ReportTable, ResolvedBlock, default_sections
from app.monthly_report_row_cards_ui import _comparison_rows


@pytest.mark.parametrize("columns", [
    ("Decision", "Decision", "1. Decision"),
    ("2. Decision", "Decision", "Decision"),
    ("Decision", "Decision", "1. Decision", "2. Decision"),
    ("", "", "1. "),
    ("Decision", "Decision", "1. Decision", "1. 1. Decision"),
])
def test_display_label_collisions_keep_every_cell_in_source_order(columns):
    rows = (tuple(f"First row cell {index}" for index in range(len(columns))),
            tuple("" if index % 2 else f"Second row cell {index}" for index in range(len(columns))))
    displayed = _comparison_rows(columns, rows)
    assert len(displayed) == len(rows)
    assert len(displayed[0]) == len(columns)
    assert tuple(displayed[0]) == tuple(displayed[1])
    assert tuple(tuple(row.values()) for row in displayed) == rows
    # A neutral repeat cannot rename or reorder either comparison's columns.
    assert _comparison_rows(columns, rows) == displayed


@pytest.mark.parametrize("columns, expected", [
    (("Proposal #", "Decision", "Decision"), ("Proposal #", "2. Decision", "3. Decision")),
    (("Proposal #", "Decision", "Notes"), ("Proposal #", "Decision", "Notes")),
    (("", "", "Notes"), ("1. ", "2. ", "Notes")),
    (("1. Decision", "Decision", "Notes"), ("1. Decision", "Decision", "Notes")),
])
def test_noncolliding_comparison_labels_remain_unchanged(columns, expected):
    rows = (("First value", "Second value", "Third value"),)
    displayed = _comparison_rows(columns, rows)
    assert tuple(displayed[0]) == expected
    assert tuple(displayed[0].values()) == rows[0]


SCRIPT = '''
from types import SimpleNamespace
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, ColumnSpec, ReportPeriod, ReportTable, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field
draft = st.session_state.setdefault('draft', synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)))
block = st.session_state.setdefault('block', INITIAL)
spec = SPEC
st.session_state['block'] = _edit_content(spec, block, SimpleNamespace(profile=draft.profile), 'comparison_test', {}, _field, draft)
'''


def _workspace(spec, block):
    app = AppTest.from_string(SCRIPT.replace("INITIAL", repr(block)).replace("SPEC", repr(spec))).run()
    assert not app.exception
    return app


def _button(app, label):
    return next(item for item in app.button if item.label == label)


def _draft(app, spec, block):
    section = next(section for section in default_sections() if section.key == "proposals")
    return replace(app.session_state["draft"], sections=(replace(section, blocks=(spec,)),), blocks=(block,))


@pytest.mark.parametrize("columns", [
    ("Decision", "Decision", "1. Decision"),
    ("2. Decision", "Decision", "Decision"),
], ids=["literal_heading_after_duplicates", "literal_heading_before_duplicates"])
@pytest.mark.parametrize("choice", ["Use row edits", "Keep current table"])
def test_native_conflict_choice_reopens_and_exports_original_columns(monkeypatch, tmp_path, columns, choice):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    spec = BlockSpec("proposals", "table", columns=tuple(
        ColumnSpec(str(index), title) for index, title in enumerate(columns)))
    rows = (("Original first", "Original second", "Original third"),
            ("Untouched first", "Untouched second", "Untouched third"))
    table = ReportTable(columns, rows, "synthetic-native-table-origin")
    block = ResolvedBlock("proposals", "This month", extra_tables=(table,),
                          references=("synthetic-owned-source",))
    app = _workspace(spec, block)
    original = _draft(app, spec, block)
    library.save_snapshot(original, expected_revision=0)

    _button(app, "Edit proposal").click().run()
    assert not app.exception
    changed_index = [index for index, title in enumerate(columns) if title == "Decision"][1]
    [item for item in app.text_input if item.label == "Decision"][1].set_value("Pending operator edit")
    pending_row = tuple("Pending operator edit" if index == changed_index else value
                        for index, value in enumerate(rows[0]))
    pending = replace(table, rows=(pending_row, rows[1]))
    incoming = replace(table, rows=(("Concurrent first", "Concurrent second", "Concurrent third"), rows[1]))
    current_block = replace(block, extra_tables=(incoming,))
    app.session_state["block"] = current_block
    app.run()

    assert not app.exception
    assert app.session_state["block"] == current_block
    assert any("Both versions are kept" in item.value for item in app.warning)
    assert len(app.dataframe) == 2
    for rendered, expected in zip(app.dataframe, (incoming, pending)):
        frame = rendered.value
        assert frame.shape == (2, len(columns))
        assert frame.columns.is_unique
        assert tuple(tuple(row) for row in frame.itertuples(index=False, name=None)) == expected.rows
    assert tuple(app.dataframe[0].value.columns) == tuple(app.dataframe[1].value.columns)

    _button(app, choice).click().run()
    assert not app.exception
    chosen = pending if choice == "Use row edits" else incoming
    selected = app.session_state["block"]
    assert selected == replace(block, extra_tables=(chosen,))
    assert selected.extra_tables[0].columns == columns
    assert selected.extra_tables[0].reference == table.reference
    assert selected.references == block.references

    saved = _draft(app, spec, selected)
    library.save_snapshot(saved, expected_revision=1)
    reopened = library.load_snapshot(saved.profile.contract, saved.profile.key, saved.period)
    assert reopened.draft == saved
    assert library.load_snapshot_version(saved.profile.contract, saved.profile.key, saved.period, 1).draft == original
    second_app = _workspace(spec, reopened.draft.blocks[0])
    _button(second_app, "Edit proposal").click().run()
    assert not second_app.exception
    assert tuple(item.value for item in second_app.text_input) == chosen.rows[0]

    word = assemble_docx(reopened.draft, acknowledged_fingerprint=reopened.draft.fingerprint)
    document = Document(BytesIO(word))
    native = next(item for item in document.tables
                  if tuple(cell.text for cell in item.rows[0].cells) == columns)
    assert tuple(tuple(cell.text for cell in row.cells) for row in native.rows[1:]) == chosen.rows
