"""Preserve merged vendor trade bands as contact groups, not fictitious people.

An original complete Word horizontal merge and recognizable column headings
are required; unproved or ambiguous table geometry stays in manual review.
The trade is stored in the row's distinct grouping field, never a separate
contact record.
"""
from __future__ import annotations

from app.monthly_report_model import ReportTable


_LABELS = {
    "vendor", "vendor name", "company", "contractor", "supplier",
    "contact", "contact name", "name", "phone", "phone number",
    "telephone", "email", "email address", "msa", "agreement status",
    "discipline", "trade", "category",
}
_GROUP_COLUMNS = {"discipline", "trade", "category"}
_NAME_COLUMNS = {"vendor", "vendor name", "company", "contractor", "supplier", "contact", "contact name", "name"}
_DETAIL_COLUMNS = {"phone", "phone number", "telephone", "email", "email address", "msa", "agreement status"}


def _normalized(row):
    return tuple(" ".join(str(value).casefold().split()) for value in row)


def _is_header(row):
    labels = _normalized(row)
    return (all(labels) and len(set(labels)) == len(labels)
            and sum(label in _LABELS for label in labels) >= 2
            and bool(set(labels) & _NAME_COLUMNS)
            and bool(set(labels) & _DETAIL_COLUMNS))


def grouped_vendor_contacts(item) -> ReportTable | None:
    """Return editable contact rows or None; never retype ambiguous source rows."""
    rows = item.rows
    width = len(rows[0]) if rows else 0
    merged = set(item.merged_title_rows)
    if not 2 <= width <= 12 or len(rows) < 3 or not merged:
        return None
    if _is_header(rows[0]):
        header_index, current_group = 0, ""
    elif 0 in merged and _is_header(rows[1]):
        header_index, current_group = 1, str(rows[0][0]).strip()
    else:
        return None

    columns = tuple(str(cell).strip() for cell in rows[header_index])
    labels = _normalized(columns)
    category_index = next((index for index, title in enumerate(labels)
                           if title in _GROUP_COLUMNS), None)
    # A filtered source table must not regain price columns in this adapter.
    from app.monthly_report_content_policy import table_price_columns
    if table_price_columns(columns, rows[header_index + 1:]):
        return None

    groups = {current_group: 0} if current_group else {}
    contacts = []
    for index in range(header_index + 1, len(rows)):
        row = rows[index]
        if len(row) != width:
            return None
        if index in merged:
            title = str(row[0]).strip()
            if not title or any(str(cell).strip() for cell in row[1:]) or _is_header(row):
                return None
            current_group = title
            groups.setdefault(current_group, 0)
            continue
        if not any(str(cell).strip() for cell in row):
            continue  # A blank Word spacer is not a vendor.
        if _normalized(row) == labels:
            continue  # An exact repeated header is not a person.
        if not current_group or _is_header(row):
            return None
        values = tuple(str(value) for value in row)
        if category_index is not None:
            saved = values[category_index].strip()
            if saved and saved.casefold() != current_group.casefold():
                return None  # Source row and merged group disagree.
            values = (*values[:category_index], saved or current_group,
                      *values[category_index + 1:])
        else:
            values = (current_group, *values)
        contacts.append(values)
        groups[current_group] += 1

    if not contacts or not groups or not all(groups.values()):
        return None
    return ReportTable(columns if category_index is not None else ("Discipline", *columns),
                       tuple(contacts))
