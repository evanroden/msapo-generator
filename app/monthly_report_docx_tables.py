"""Bounded Word table-grid extraction without flattening nested table children.

A nested w:tbl occupies its own native XML occurrence. Parent rows retain
only their own cell text; descendants are inventoried separately by the caller.
This helper neither reads source files nor changes original package bytes.
"""
from dataclasses import dataclass

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class NativeGrid:
    rows: tuple[tuple[str, ...], ...]
    full_width_bands: tuple[tuple[int, int], ...]
    descendants: tuple


def native_grid(element, *, text_of, error_type, children=None):
    """Read direct grid text and all child tables, preserving merged-cell spans.

    The table's native geometry remains in the original. Word vertical merges
    are not silently guessed into repeated values; empty continuation cells
    remain explicit and must be confirmed by the editor. ``children(parent, tag)``
    lists a parent's direct rows or cells; the importer passes one that also
    looks inside simple content controls.
    """
    if children is None:
        def children(parent, tag):
            return parent.findall(tag)
    descendants = tuple(node for node in element.iter(W + "tbl") if node is not element)
    rows, full_width_bands = [], []
    for row in children(element, W + "tr"):
        cells = []
        before = row.find(f"{W}trPr/{W}gridBefore")
        cells.extend([""] * min(100, int(before.get(W + "val", "0"))) if before is not None else [])
        row_cells = children(row, W + "tc")
        if len(row_cells) == 1 and before is None:
            merged = row_cells[0].find(f"{W}tcPr/{W}gridSpan")
            if merged is not None:
                full_width_bands.append((len(rows), int(merged.get(W + "val", "1"))))
        for cell in row_cells:
            # A nested table is its own data grid; never duplicate its cells
            # inside the parent cell's flattened narrative.
            cells.append(text_of(cell, exclude=set(cell.iter(W + "tbl"))))
            span = cell.find(f"{W}tcPr/{W}gridSpan")
            count = int(span.get(W + "val", "1")) if span is not None else 1
            if count < 1 or count > 100 or len(cells) > 100:
                raise error_type("Table is too wide to review safely.")
            cells.extend([""] * (count - 1))
        rows.append(tuple(cells))
    if rows:
        width = max(map(len, rows))
        rows = [row + ("",) * (width - len(row)) for row in rows]
    return NativeGrid(tuple(rows), tuple(full_width_bands), descendants)
