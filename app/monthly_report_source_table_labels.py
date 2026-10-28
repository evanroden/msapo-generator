"""Source-oriented names for reviewed Monthly tables, not internal table slots.

Labels use saved column schema, destination and physical row count only. They
do not infer completion, site ownership or facts from uploaded values.
"""
from __future__ import annotations

import re


def _headings(table):
    return tuple(" ".join(str(title).casefold().split())
                 for title in table.columns)


def table_task_label(table, destination: str, *, position=0, total=1) -> str:
    """Return a plain-text, stable label without interpreting original cells."""
    headings = _headings(table)
    if destination == "work_orders":
        months = ("jan", "feb", "mar", "apr", "may", "jun",
                  "jul", "aug", "sep", "oct", "nov", "dec")
        normalized = tuple(value.rstrip(".")[:3] for value in headings)
        if all(month in normalized for month in months):
            title = "Annual work-order summary"
        elif any(h in {"wo #", "wo", "work order", "work order number", "work order id"}
                 for h in headings):
            title = "Work-order records"
        elif any(re.search(r"\bpm\b", h) or "preventive maintenance" in h
                 for h in headings):
            title = "Preventive maintenance summary"
        else:
            title = "Work-order source table"
    elif destination == "service_calls":
        title = "Service-call records"
    elif destination == "subcontractor_matrix":
        title = "Vendor contacts"
    elif destination == "capital_renewal":
        title = "Capital renewal items"
    elif destination == "proposals":
        title = "Proposal records"
    elif destination == "training_summary":
        title = "Training source table"
    else:
        title = "Imported source table"
    if total > 1:
        title += f" · source {position + 1} of {total}"
    count = len(table.rows)
    return f"{title} · {count} source {'row' if count == 1 else 'rows'}"
