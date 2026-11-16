"""Synthetic column-weight regressions for PR 933."""
from docx import Document
import pytest
from app import monthly_report_docx as renderer


@pytest.mark.parametrize("text, expected", [
    ("AHU-TEST-04 drive", 17),
    ("longestword medium AHU-1", 17),
    ("AHU-TEST-04", 11),
    ("plain words", 5),
    ("", 1),
])
def test_hyphenated_token_keeps_room_for_an_actual_other_word(monkeypatch, text, expected):
    observed = []
    def distribute(total, weights, minimum=900):
        observed.append(tuple(weights))
        return [total // len(weights)] * len(weights)
    monkeypatch.setattr(renderer, "_distribute_width", distribute)
    table = Document().add_table(rows=3, cols=2)
    renderer._fit_imported_table_columns(table, ("A", "B"), ((text, "ok"), (None, "x")))
    assert observed == [(expected, 2)]
    assert len(table.columns) == 2
