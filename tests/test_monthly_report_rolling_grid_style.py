"""Synthetic native-grid sizing never changes saved master bytes or cell values."""
from copy import deepcopy
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_rolling_grid_style import fit_narrow_rolling_grid

COLUMNS = ("Non-PM Received", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026",
           "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026",
           "Nov 2026", "Dec 2026", "Jan 2027")


def table_with_values():
    doc = Document()
    table = doc.add_table(rows=2, cols=13)
    for column, label in enumerate(COLUMNS):
        table.cell(0, column).text = label
    for column, label in enumerate(("North QA", "", "0", "1", "", "", "", "", "", "", "", "", "")):
        table.cell(1, column).text = label
    return table._tbl


def grid_widths(table):
    return tuple(int(node.get(qn("w:w"))) for node in table.find(qn("w:tblGrid")))


def text_of(table):
    return tuple(node.text for node in table.iter(qn("w:t")))


def test_narrow_rolling_grid_rebalances_copy_without_losing_any_values():
    source = table_with_values()
    before = source.xml
    generated = deepcopy(source)
    widths = grid_widths(generated)
    values = text_of(generated)
    assert widths[0] * 5 < sum(widths)
    assert fit_narrow_rolling_grid(generated, COLUMNS)
    adjusted = grid_widths(generated)
    assert sum(adjusted) == sum(widths)
    assert adjusted[0] * 5 >= sum(adjusted)
    assert all(width > 0 for width in adjusted)
    assert text_of(generated) == values
    assert source.xml == before
    assert generated.find("./" + qn("w:tblPr") + "/" + qn("w:tblLayout")).get(qn("w:type")) == "fixed"
    for row in generated.findall(qn("w:tr")):
        cells = row.findall(qn("w:tc"))
        assert tuple(int(cell.find("./" + qn("w:tcPr") + "/" + qn("w:tcW")).get(qn("w:w")))
                     for cell in cells) == adjusted
        for cell in cells:
            assert all(run.find("./" + qn("w:rPr") + "/" + qn("w:sz")).get(qn("w:val")) == "16"
                       for run in cell.iter(qn("w:r")))
    assert not fit_narrow_rolling_grid(generated, COLUMNS)  # idempotent


def test_nonrolling_nonconsecutive_and_merged_tables_are_untouched():
    for columns in (("Asset", *COLUMNS[1:]), (COLUMNS[0], *reversed(COLUMNS[1:]))):
        table = table_with_values()
        before = table.xml
        assert not fit_narrow_rolling_grid(table, columns)
        assert table.xml == before
    table = table_with_values()
    cell = table.find("./" + qn("w:tr") + "/" + qn("w:tc"))
    cell.find(qn("w:tcPr")).append(OxmlElement("w:gridSpan"))
    before = table.xml
    assert not fit_narrow_rolling_grid(table, COLUMNS)
    assert table.xml == before


def test_existing_wide_first_column_keeps_native_layout():
    table = table_with_values()
    grid = table.find(qn("w:tblGrid"))
    total = sum(grid_widths(table))
    first = (total + 4) // 5
    rest = (total - first) // 12
    for i, col in enumerate(grid):
        col.set(qn("w:w"), str(first if i == 0 else rest))
    before = table.xml
    assert not fit_narrow_rolling_grid(table, COLUMNS)
    assert table.xml == before
