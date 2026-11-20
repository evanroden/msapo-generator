"""Lossless physical cell positions and conservative native Word row-band evidence.

These are hints for explicit review, not a claim of completed work or of
contact identity. Every physical w:tc retains a source row/cell/grid pointer.
The original DOCX is never rewritten.
"""
from __future__ import annotations

from dataclasses import dataclass

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class WordTableGeometry:
    width: int
    # (native row, native cell ordinal, zero-based grid column, grid span, vMerge)
    cell_refs: tuple[tuple[int, int, int, int, str], ...]
    row_roles: tuple[str, ...]
    row_groups: tuple[int, ...]


def _number(node, default=0):
    if node is None:
        return default
    try:
        value = int(node.get(W + "val", str(default)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid Word table grid width.") from exc
    if not 0 <= value <= 100:
        raise ValueError("Word table grid width exceeds 100 columns.")
    return value


def word_table_geometry(table, rows) -> WordTableGeometry:
    """Describe physical positions without interpreting merged bands as records.

    No cell is duplicated for a horizontal span. The grid width also includes
    gridBefore, gridAfter and tblGrid declarations, not only visible text.
    Repeated headers are suppressed in *derived typed rows* only when both the
    native tblHeader flag and exact source labels confirm repetition.
    """
    grid = table.find(W + "tblGrid")
    grid_width = len(grid.findall(W + "gridCol")) if grid is not None else 0
    if grid_width > 100:
        raise ValueError("Word table grid width exceeds 100 columns.")
    refs = []
    roles = []
    groups = []
    group = 0
    header_values = None
    width = grid_width
    for index, row in enumerate(table.findall(W + "tr")):
        tr_pr = row.find(W + "trPr")
        before = _number(tr_pr.find(W + "gridBefore") if tr_pr is not None else None)
        after = _number(tr_pr.find(W + "gridAfter") if tr_pr is not None else None)
        header_flag = tr_pr.find(W + "tblHeader") if tr_pr is not None else None
        marked = (header_flag is not None and
                  header_flag.get(W + "val", "1").casefold() not in ("0", "false", "off"))
        column = before
        cells = row.findall(W + "tc")
        spans = []
        for physical, cell in enumerate(cells):
            tc_pr = cell.find(W + "tcPr")
            span = _number(tc_pr.find(W + "gridSpan") if tc_pr is not None else None, 1)
            if span < 1 or column + span > 100:
                raise ValueError("Word table grid width exceeds 100 columns.")
            merge = tc_pr.find(W + "vMerge") if tc_pr is not None else None
            vertical = merge.get(W + "val", "continue") if merge is not None else ""
            refs.append((index, physical, column, span, vertical))
            spans.append(span)
            column += span
        width = max(width, column + after)
        if width > 100:
            raise ValueError("Word table grid width exceeds 100 columns.")
        # Row labels come from the extractor's final-view data, never fresh
        # text from hidden revisions, graphics or unsupported nested tables.
        source = tuple(rows[index]) if index < len(rows) else ()
        values = tuple(value.strip() for value in source)
        full_band = (len(cells) == 1 and before == 0 and after == 0
                     and len(spans) == 1 and spans[0] > 1
                     and bool(values) and bool(values[0])
                     and not any(values[1:]))
        if full_band:
            role = "title_band" if index == 0 else "group_band"
            if index:
                group += 1
        elif marked and header_values is not None and source == header_values:
            role = "repeated_header"
        elif marked or ((index == 0 or (index == 1 and roles and roles[0] == "title_band"))
                        and len(cells) >= 2 and all(values[:len(cells)])
                        and len(set(values[:len(cells)])) == len(cells)):
            role = "header"
            if header_values is None:
                header_values = source
        else:
            role = "data"
        roles.append(role)
        groups.append(group)
    return WordTableGeometry(width, tuple(refs), tuple(roles), tuple(groups))


def typed_data_rows(item, start: int):
    """Keep every cell except explicitly repeated native page-header rows."""
    roles = getattr(item, "table_row_roles", ())
    return tuple(row for index, row in enumerate(item.rows)
                 if index >= start and (index >= len(roles) or roles[index] != "repeated_header"))
