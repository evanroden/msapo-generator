"""Fit recognized rolling work-order grids without modifying their source master."""
from __future__ import annotations

from calendar import month_abbr
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

_METRICS = {"pm received", "pm closed", "non-pm received", "non-pm closed",
            "non pm received", "non pm closed"}
_MONTH = re.compile(r"^([A-Za-z]{3})\s+(\d{4})$")


def _is_rolling_grid(columns):
    if len(columns) != 13 or " ".join(str(columns[0]).casefold().split()) not in _METRICS:
        return False
    months = {name.casefold(): index for index, name in enumerate(month_abbr) if index}
    indices = []
    for label in columns[1:]:
        match = _MONTH.fullmatch(str(label).strip())
        if not match or match.group(1).casefold() not in months:
            return False
        indices.append(int(match.group(2)) * 12 + months[match.group(1).casefold()] - 1)
    return all(b == a + 1 for a, b in zip(indices, indices[1:]))


def fit_narrow_rolling_grid(table, columns):
    """Give a too-narrow label column room; preserve content and total width.

    Only recognized consecutive-month work-order grids with 13 ordinary cells
    per row are eligible. Properly proportioned tables are left untouched.
    The caller applies this to the generated copy, never the installed master.
    """
    if not _is_rolling_grid(columns):
        return False
    grid = table.find(qn("w:tblGrid"))
    if grid is None or len(grid) != 13:
        return False
    try:
        widths = [int(column.get(qn("w:w"), "0")) for column in grid]
    except ValueError:
        return False
    rows = table.findall(qn("w:tr"))
    if not rows or any(value <= 0 for value in widths):
        return False
    if any(len(row.findall(qn("w:tc"))) != 13 for row in rows):
        return False
    if any(cell.find("./" + qn("w:tcPr") + "/" + qn("w:" + merge)) is not None
           for row in rows for cell in row.findall(qn("w:tc"))
           for merge in ("gridSpan", "vMerge", "hMerge")):
        return False
    if any(node.tag in (qn("w:drawing"), qn("w:pict")) for node in table.iter()):
        return False
    total = sum(widths)
    if total < 7200 or widths[0] * 5 >= total:  # Five inches, or already wide enough.
        return False
    target = (total + 4) // 5
    remaining = total - target
    month_total = sum(widths[1:])
    months = [max(1, remaining * width // month_total) for width in widths[1:]]
    months[-1] += remaining - sum(months)
    if min(months) < 300:
        return False
    adjusted = (target, *months)
    for column, width in zip(grid, adjusted):
        column.set(qn("w:w"), str(width))
    properties = table.find(qn("w:tblPr"))
    if properties is None:
        properties = OxmlElement("w:tblPr")
        table.insert(0, properties)
    layout = properties.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        properties.append(layout)
    layout.set(qn("w:type"), "fixed")
    for row in rows:
        for cell, width in zip(row.findall(qn("w:tc")), adjusted):
            props = cell.find(qn("w:tcPr"))
            if props is None:
                props = OxmlElement("w:tcPr")
                cell.insert(0, props)
            cell_width = props.find(qn("w:tcW"))
            if cell_width is None:
                cell_width = OxmlElement("w:tcW")
                props.append(cell_width)
            cell_width.set(qn("w:w"), str(width))
            cell_width.set(qn("w:type"), "dxa")
            margins = props.find(qn("w:tcMar"))
            if margins is None:
                margins = OxmlElement("w:tcMar")
                props.append(margins)
            for side in ("left", "right"):
                margin = margins.find(qn("w:" + side))
                if margin is None:
                    margin = OxmlElement("w:" + side)
                    margins.append(margin)
                margin.set(qn("w:w"), "40")  # two points, in twentieths of a point
                margin.set(qn("w:type"), "dxa")
            for run in cell.iter(qn("w:r")):
                run_props = run.find(qn("w:rPr"))
                if run_props is None:
                    run_props = OxmlElement("w:rPr")
                    run.insert(0, run_props)
                for name in ("sz", "szCs"):
                    size = run_props.find(qn("w:" + name))
                    if size is None:
                        size = OxmlElement("w:" + name)
                        run_props.append(size)
                    size.set(qn("w:val"), "16")  # eight-point text
    return True
