"""Word maintenance-table bridge using existing bounded DOCX inspection.

No second heading router or lossy native table rewrite. Ambiguous Word tables
are candidate data only; the user must confirm native layout and completion
before any service-call block may be created.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from app.monthly_report_import import inspect_docx
from app.monthly_report_model import ReportPeriod, ReportProfile
from app import monthly_report_sources as sources
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_service_call_mapping import (
    UnmatchedRow, ServiceCallReview, review_service_calls,
    suggest_call_mapping, _normalize, TITLES,
)

MAX_HEADER_LOOK = 6


@dataclass(frozen=True)
class WordMaintenanceTable:
    item_id: str
    word_position: int
    item_number: int
    original: tuple[tuple[str, ...], ...]
    header_row_number: int
    title_rows: tuple[UnmatchedRow, ...]
    review: ServiceCallReview | None
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class WordMaintenanceReview:
    source_id: str
    source_sha256: str
    tables: tuple[WordMaintenanceTable, ...]
    ignored_item_ids: tuple[str, ...]
    cross_table_duplicates: tuple[tuple[str, str], ...] = ()


def _source_headers(rows):
    hits = []
    for number, values in enumerate(rows[:MAX_HEADER_LOOK], 1):
        mapping = suggest_call_mapping(values)
        if mapping.wo is not None and mapping.task is not None:
            hits.append((number, values))
    if not hits:
        return None, ("No supported work-order ID/task column header was found.",)
    if len({tuple(_normalize(value) for value in row) for _, row in hits}) != 1:
        return None, ("Two conflicting service-call headers need column review.",)
    return hits[0], ()


def _word_table(content, item, item_number, profile, period):
    original = tuple(tuple(cell for cell in row) for row in item.rows)
    identity = {"item_id": item.id, "word_position": item.position,
                "item_number": item_number, "original": original}
    if not original or len(original) > 20_000:
        return WordMaintenanceTable(**identity, header_row_number=0,
            title_rows=(), review=None,
            notices=("The native Word table is blank or too long to review safely.",))
    header, warning = _source_headers(original)
    if warning:
        return WordMaintenanceTable(**identity, header_row_number=0,
                                    title_rows=(), review=None, notices=warning)
    header_n, labels = header
    titles, unmatched = [], []
    for n, cells in enumerate(original[:header_n - 1], 1):
        nonempty = [value for value in cells if value.strip()]
        if len(nonempty) == 1 and _normalize(nonempty[0]) in TITLES:
            titles.append(UnmatchedRow(n, cells, "Recognized native title band."))
        else:
            unmatched.append(UnmatchedRow(n, cells,
                "Unrecognized content before source header; inspect original."))
    data, numbers = [], []
    for n, cells in enumerate(original[header_n:], header_n + 1):
        if tuple(_normalize(v) for v in cells) == tuple(_normalize(v) for v in labels):
            titles.append(UnmatchedRow(n, cells, "Repeated column header; not a record."))
            continue
        data.append(cells)
        numbers.append(n)
    table = SourceTable(item.id, tuple(labels), tuple(data))
    result = review_service_calls(content, profile, period,
        table_number=item_number, source_table=table, source_rows=table.rows,
        original_numbers=tuple(numbers), native_layout_confirmed=False)
    # Unrecognized title/preamble data cannot disappear from a selected table.
    if unmatched:
        result = replace(result, unmatched=(*unmatched, *result.unmatched))
    return WordMaintenanceTable(**identity, header_row_number=header_n,
                                title_rows=tuple(titles), review=result)


def review_word_maintenance(profile: ReportProfile, content: SourceContent,
                            period: ReportPeriod):
    """Select only Word inspector-confirmed Maintenance/Service Call table items."""
    source = content.source
    if source.suffix != ".docx":
        raise ValueError("Only a saved Word source can use native maintenance review.")
    raw = sources.source_bytes(profile, source)  # fingerprint check + original read bound
    if not raw:
        raise ValueError("Saved Word source is unavailable.")
    inspection = inspect_docx(sources._path(profile, source.sha256, source.suffix))
    if inspection.sha256 != source.sha256 or len(inspection.items) != len(source.page_texts):
        raise ValueError("The Word inspection changed; reread the original before reviewing.")
    tables, ignored = [], []
    for number, item in enumerate(inspection.items, 1):
        if item.kind != "table":
            continue
        if (item.part != "word/document.xml" or item.section != "maintenance"
                or item.suggested_slot != "service_calls"):
            ignored.append(item.id)
            continue
        tables.append(_word_table(content, item, number, profile, period))
    seen = {}
    for table in tables:
        if table.review is None:
            continue
        for row in table.review.rows:
            if row.wo and row.site:
                seen.setdefault((row.site, row.wo.casefold()), set()).add(table.item_id)
    duplicates = tuple(sorted(key for key, ids in seen.items() if len(ids) > 1))
    return WordMaintenanceReview(source.id, source.sha256, tuple(tables),
                                 tuple(ignored), duplicates)
