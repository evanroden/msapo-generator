"""Reviewable CSV work-order adapter; preserves the existing source parser.

The source cache already accepts UTF-8/BOM and bounded CP1252 exports, plus
comma, semicolon, tab and pipe delimiters. This adapter NEVER reparses a
different, unverified file or changes the current CSV metrics. Only expressly
reviewed field positions and numeric date order can resolve uncertain rows.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256
import json
import re
from typing import Mapping

from app.monthly_report_model import ReportPeriod, ReportProfile
from app.monthly_report_sources import SourceContent
from app.monthly_report_work_order_normalized import (
    FIELDS, ColumnMapping, WorkOrderReview, _issues, _mark_duplicates,
    correct_row, exclude_row, normalize_table, reimport_review,
    restore_review, review_record, suggest_mapping,
)

DATE_ORDERS = ("", "MDY", "DMY")
_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s*$")


@dataclass(frozen=True)
class CsvReview:
    """Unpublished, source/period-bound result; selections need human review."""

    workorders: WorkOrderReview
    numeric_date_order: str = ""

    def __post_init__(self):
        if self.numeric_date_order not in DATE_ORDERS:
            raise ValueError("Choose MDY, DMY, or leave numeric dates for review.")

    @property
    def revision(self):
        encoded = json.dumps(
            (self.workorders.revision, self.numeric_date_order),
            separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    @property
    def unresolved_dates(self):
        fields = ("work_date", "completed_date")
        result = []
        for row in self.workorders.rows:
            if row.excluded:
                continue
            for field in fields:
                position = getattr(self.workorders.mapping, field)
                if position is None:
                    continue
                raw = row.origin.cells[position].strip()
                if _NUMERIC_DATE.fullmatch(raw) and not getattr(row, field):
                    result.append((row.key, field, raw))
        return tuple(result)

    @property
    def questions(self):
        problems = list(self.workorders.questions)
        if self.unresolved_dates:
            problems.append(
                "Numeric dates need an explicit MDY/DMY interpretation or a row correction."
                if not self.numeric_date_order else
                "Some numeric dates remain invalid for the selected date order. Correct those rows."
            )
        return tuple(dict.fromkeys(problems))

    @property
    def ready_for_inclusion(self):
        return (self.workorders.kind == "records"
                and not self.questions
                and any(not row.excluded for row in self.workorders.rows)
                and all(not row.issues for row in self.workorders.rows if not row.excluded))

    def editable_table(self):
        """Use the existing editable-table schema; never silently publish it."""
        return self.workorders.review_table()


def physical_columns(content: SourceContent, table_number: int = 1):
    """Return exact positions, including duplicate/unknown physical headers."""
    if (content.source.suffix != ".csv" or type(table_number) is not int
            or not 1 <= table_number <= len(content.tables)):
        raise ValueError("Choose an imported CSV source table.")
    return tuple((index, str(index + 1) + " · " + title)
                 for index, title in enumerate(content.tables[table_number - 1].columns))


def mapped_columns(columns, choices: Mapping[str, int | None], *,
                   suggested: ColumnMapping | None = None):
    """Apply explicit per-field selections without guessing ambiguous columns.

    A None value deliberately leaves a field unmapped. A selected position
    wins over a duplicate header, while every other source cell is retained.
    """
    if not isinstance(choices, Mapping) or any(field not in FIELDS for field in choices):
        raise ValueError("Choose supported work-order columns.")
    suggestion = suggested if suggested is not None else suggest_mapping(columns)
    result = {}
    for field in FIELDS:
        index = choices.get(field, getattr(suggestion, field))
        if index is not None and (type(index) is not int or not 0 <= index < len(columns)):
            raise ValueError("Choose a source column within this CSV table.")
        result[field] = index
    taken = [value for value in result.values() if value is not None]
    if len(taken) != len(set(taken)):
        raise ValueError("One CSV column was assigned to multiple work-order fields.")
    ambiguous = tuple(field for field in suggestion.ambiguous if field not in choices)
    return ColumnMapping(**result, ambiguous=ambiguous)


def _interpreted_date(value: str, order: str):
    match = _NUMERIC_DATE.fullmatch(value)
    if not match or not order:
        return ""
    first, second, year = (int(part) for part in match.groups())
    month, day = (first, second) if order == "MDY" else (second, first)
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def review_csv(content: SourceContent, profile: ReportProfile, period: ReportPeriod, *,
               mapping: ColumnMapping | None = None, numeric_date_order: str = ""):
    if content.source.suffix != ".csv":
        raise ValueError("CSV work-order review requires a saved CSV source.")
    return review_spreadsheet(content, profile, period, mapping=mapping,
                              numeric_date_order=numeric_date_order)


def review_spreadsheet(content: SourceContent, profile: ReportProfile, period: ReportPeriod, *,
               mapping: ColumnMapping | None = None, numeric_date_order: str = "", table_number=1):
    """Interpret one vetted CSV with a deliberate mapping and date-locale choice.

    Numeric date corrections are batched: converting a 20,000-row input by
    repeatedly calling one-row CAS would be quadratic. Original source rows,
    leading zero IDs and unrecognized values remain byte-for-byte in origins.
    """
    if content.source.suffix not in (".csv", ".xlsx"):
        raise ValueError("Work-order review requires a saved CSV or workbook source.")
    if numeric_date_order not in DATE_ORDERS:
        raise ValueError("Choose MDY, DMY, or leave numeric dates for review.")
    review = normalize_table(content, table_number, profile, period, mapping=mapping)
    if not numeric_date_order or review.kind != "records":
        return CsvReview(review, numeric_date_order)

    rows = []
    for original in review.rows:
        changes = {}
        corrections = dict(original.corrections)
        for field in ("work_date", "completed_date"):
            position = getattr(review.mapping, field)
            if position is None:
                continue
            raw = original.origin.cells[position]
            interpreted = _interpreted_date(raw, numeric_date_order)
            if interpreted:
                changes[field] = interpreted
                # The explicit ISO choice is review data, not source text.
                corrections[field] = interpreted
        changed = replace(original, **changes,
                          corrections=tuple(sorted(corrections.items()))) if changes else original
        rows.append(replace(changed, issues=_issues(
            changed, review.allowed_sites, review.period_key)))
    return CsvReview(replace(review, rows=_mark_duplicates(rows)), numeric_date_order)


def correct_csv_row(review: CsvReview, key: str, changes: dict[str, str], *,
                    expected_revision: str):
    """Reuse normalized single-row CAS, additionally pinning the date policy."""
    if expected_revision != review.revision:
        raise ValueError("The CSV review changed. Reopen the current source and row.")
    revised = correct_row(review.workorders, key, changes,
                          expected_revision=review.workorders.revision)
    return replace(review, workorders=revised)


def exclude_csv_row(review: CsvReview, key: str, *, expected_revision: str,
                    excluded: bool):
    if expected_revision != review.revision:
        raise ValueError("The CSV review changed. Reopen the current source and row.")
    revised = exclude_row(review.workorders, key,
                          expected_revision=review.workorders.revision,
                          excluded=excluded)
    return replace(review, workorders=revised)


def reimport_csv_review(previous: CsvReview, freshly_parsed: CsvReview):
    """Idempotent exact same source; never replace a manual edit or scope."""
    left, right = previous.workorders, freshly_parsed.workorders
    if (previous.numeric_date_order != freshly_parsed.numeric_date_order
            or left.mapping != right.mapping
            or left.period_key != right.period_key
            or left.allowed_sites != right.allowed_sites):
        raise ValueError("CSV mapping, date interpretation, or site/month changed. Review it again.")
    return replace(freshly_parsed, workorders=reimport_review(left, right))


def csv_review_record(review: CsvReview):
    """Immutable portable record, not a saved-report publication."""
    return {
        "schema": 1, "numeric_date_order": review.numeric_date_order,
        "workorders": review_record(review.workorders), "sha256": review.revision,
    }


def restore_csv_review(value):
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("Unknown saved CSV work-order review schema.")
    try:
        result = CsvReview(
            restore_review(value["workorders"]), value["numeric_date_order"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("The saved CSV review is incomplete or invalid.") from exc
    if result.revision != value.get("sha256"):
        raise ValueError("The saved CSV review failed its integrity check.")
    return result
