"""Conservative annual multi-site work-order table adapter.

Only Site/Metric/Unit headers, twelve ordered month headings, and recognized
whole-row category bands qualify. This remains an editable ReportTable: it
does not invent work-order tasks or monthly totals. Ambiguous shapes stay in
review, retaining their original source rows.
"""
from __future__ import annotations

from app.monthly_report_model import ReportTable


_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_BANDS = frozenset({
    "work order status", "work orders", "work order", "pm status",
    "preventive maintenance", "preventative maintenance",
    "corrective maintenance", "cm status",
})
_IDENTIFIERS = (frozenset({"site", "facility", "location"}),
                frozenset({"metric", "measure", "work type"}),
                frozenset({"unit", "units"}))


def _normalized(value):
    return " ".join(str(value).casefold().split())


def _month(value):
    return _MONTHS.get(_normalized(value).removesuffix("."))


def _band(row):
    if not row or any(_normalized(value) for value in row[1:]):
        return ""
    return str(row[0]).strip() if _normalized(row[0]) in _BANDS else ""


def _header(row):
    return (len(row) == 15
            and all(_normalized(row[i]) in _IDENTIFIERS[i] for i in range(3))
            and tuple(_month(v) for v in row[3:]) == tuple(range(1, 13)))


def _first_header(rows):
    if not rows:
        return None
    if _header(rows[0]):
        return 0
    if len(rows) >= 2 and _band(rows[0]) and _header(rows[1]):
        return 1
    return None


def annual_grid_candidate(item):
    """Catch partial month-column schemas before they are auto-assigned."""
    if getattr(item, "kind", "") != "table" or getattr(item, "section", "") != "activity":
        return False
    rows = item.rows
    if not rows:
        return False
    top = rows[1] if _band(rows[0]) and len(rows) > 1 else rows[0]
    return (len(top) == 15
            and all(_normalized(top[i]) in _IDENTIFIERS[i] for i in range(3))
            and sum(_month(v) is not None for v in top[3:]) >= 8)


def annual_site_month_table(item) -> ReportTable | None:
    """Add an explicit Category field without changing any source month cell."""
    if not annual_grid_candidate(item):
        return None
    rows = item.rows
    first = _first_header(rows)
    if first is None or len(rows) < first + 3:
        return None
    heading = tuple(str(v).strip() for v in rows[first])
    group = _band(rows[0]) if first else ""
    counts = {group: 0} if group else {}
    sites = set()
    values = []
    merge_proof = getattr(item, "merged_title_rows", None)
    for index in range(first + 1, len(rows)):
        row = rows[index]
        if len(row) != len(heading):
            return None
        if _header(row):
            continue  # A repeated real header is not a work-order record.
        band = _band(row)
        if band:
            # In inspections which retain original Word merge geometry, a
            # band without a proven full-width merge requires explicit review.
            if merge_proof is not None and index not in merge_proof:
                return None
            group = band
            counts.setdefault(group, 0)
            continue
        if not any(_normalized(value) for value in row):
            continue  # A completely empty source spacer, never a 0 count.
        if not group or not all(_normalized(row[i]) for i in range(3)):
            return None
        sites.add(_normalized(row[0]))
        values.append((group, *(str(value) for value in row)))
        counts[group] += 1
    if len(sites) < 2 or not values or not counts or not all(counts.values()):
        return None
    return ReportTable(("Category", *heading), tuple(values))


def annual_grid_matches_profile(table: ReportTable, profile) -> bool:
    """Foreign/unknown site membership is a review task, not silent inclusion."""
    if not profile or not getattr(profile, "facilities", ()) or not table.rows:
        return False
    permitted = {_normalized(value) for site in profile.facilities
                 for value in (site.title, *site.aliases) if _normalized(value)}
    return all(_normalized(row[1]) in permitted for row in table.rows)


def annual_header_cells(table: ReportTable) -> frozenset[tuple[int, int]]:
    """Exempt only exact month header coordinates from false stale-month warnings."""
    if (len(table.columns) != 16 or _normalized(table.columns[0]) != "category"
            or not all(_normalized(table.columns[i + 1]) in _IDENTIFIERS[i]
                       for i in range(3))
            or tuple(_month(value) for value in table.columns[4:]) != tuple(range(1, 13))
            or not table.rows
            or any(len(row) != 16 or not all(_normalized(value) for value in row[:4])
                   for row in table.rows)):
        return frozenset()
    return frozenset((0, column) for column in range(4, 16))
