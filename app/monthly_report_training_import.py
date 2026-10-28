"""Review prior Training tables without inventing current-month completion.

The intake layer already stores original DOCX/CSV/XLSX bytes and identifies
Word section/table items. This module reads those *saved* sources, creates
source/row-bound review proposals and only changes a report-scoped Training
block upon an explicit, compare-and-swap accept. It never writes shared annual
training, changes original sources, or starts an external reader/model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from hashlib import sha256
import json
import math
import re

from app.monthly_report_model import ReportTable, ReportPeriod, ReportProfile, ResolvedBlock
from app.monthly_report_sources import SourceContent, source_reference
from app.monthly_report_training import (
    EVENT_COLUMNS, EVENT_REF, FORMATS, MATRIX_REF, STATUSES,
    add_event, apply_tables, events_for_period, session_row_tokens, validate_matrix,
)


EVENT_HEADERS = {
    "title": {"training", "topic", "trainingtopic", "session", "sessionname", "course"},
    "when": {"date", "trainingdate", "sessiondate", "completiondate", "completedon"},
    "mode": {"format", "method", "mode", "deliverymethod"},
    "participants": {"participants", "attendees", "learners", "staffattending"},
    "hours": {"hours", "durationhours", "traininghours"},
    "status": {"status", "trainingstatus", "completionstatus"},
}
PERSON = {"teammember", "person", "staffmember", "employee", "employee name", "staffname"}
SITE = {"site", "facility", "hospital", "location"}
COMPLETE = {"complete", "completed", "attended", "done"}
UNFINISHED = {"scheduled", "planned", "pending", "open", "cancelled", "canceled", "notcompleted"}
MAX_ROWS = 500
MAX_COLUMNS = 55
MAX_CELLS = 12_000
MAX_REVIEW_BYTES = 1_500_000
MAX_HEADER_ROWS = 4


def _name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


@dataclass(frozen=True)
class TrainingTableSource:
    filename: str
    source_id: str
    source_sha256: str
    source_fingerprint: str
    number: int                  # 1-based input table or DOCX item number
    reference: str
    columns: tuple[str, ...]     # Entire raw header (no silent column trimming)
    rows: tuple[tuple[str, ...], ...]
    word_item_id: str = ""
    word_section: str = ""
    native_word: bool = False


@dataclass(frozen=True)
class TrainingOrigin:
    source_id: str
    source_sha256: str
    source_fingerprint: str
    source_reference: str
    table_number: int
    row_number: int
    columns: tuple[str, ...]
    cells: tuple[str, ...]

    @property
    def key(self):
        identity = (self.source_sha256, self.table_number, self.row_number)
        return sha256(json.dumps(identity).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class TrainingImportRow:
    origin: TrainingOrigin
    values: tuple[str, ...]
    status: str = ""
    issues: tuple[str, ...] = ()
    corrections: tuple[tuple[str, str], ...] = ()
    excluded: bool = False

    @property
    def key(self):
        return self.origin.key


@dataclass(frozen=True)
class TrainingImportReview:
    source: TrainingTableSource
    period_key: str
    kind: str                   # events / requirements / unresolved
    source_year: int | None
    original_columns: tuple[str, ...]
    original_rows: tuple[tuple[str, ...], ...]
    normalized_columns: tuple[str, ...]
    rows: tuple[TrainingImportRow, ...]
    issues: tuple[str, ...] = ()
    unmatched: tuple[tuple[int, tuple[str, ...], str], ...] = ()
    native_layout_confirmed: bool = True

    @property
    def revision(self):
        return sha256(json.dumps(asdict(self), ensure_ascii=False,
                                 sort_keys=True).encode()).hexdigest()

    @property
    def ready_for_import(self):
        return (self.kind in ("events", "requirements")
                and bool(self.rows)
                and not self.issues and not self.unmatched
                and self.native_layout_confirmed
                and any(not row.excluded for row in self.rows)
                and all(not row.issues or row.excluded for row in self.rows))

    def unresolved_counts(self):
        return {
            "source_rows": len(self.original_rows),
            "accepted_candidates": sum(not row.issues and not row.excluded for row in self.rows),
            "needs_review": sum(bool(row.issues) and not row.excluded for row in self.rows),
            "excluded": sum(row.excluded for row in self.rows),
            "unmatched": len(self.unmatched),
        }

    def unmapped_cells(self, key):
        row = next((item for item in self.rows if item.key == key), None)
        if row is None:
            raise ValueError("Choose a source row from this Training review.")
        used = _recognized_positions(self.original_columns, self.kind)
        return tuple((index, heading, row.origin.cells[index])
                     for index, heading in enumerate(self.original_columns)
                     if index not in used)


def _column_positions(columns, aliases):
    return tuple(n for n, heading in enumerate(columns) if _name(heading) in aliases)


def _event_mapping(columns):
    return {key: matches[0] if len(matches := _column_positions(columns, names)) == 1
            else None for key, names in EVENT_HEADERS.items()}


def _matrix_header(columns):
    return (len(columns) >= 3
            and _name(columns[0]) in {_name(x) for x in PERSON}
            and _name(columns[1]) in {_name(x) for x in SITE}
            and len({_name(c) for c in columns}) == len(columns))


def _recognized_positions(columns, kind):
    if kind == "events":
        return {index for index in _event_mapping(columns).values() if index is not None}
    return set(range(len(columns))) if kind == "requirements" else set()


def _header_kind(columns):
    if _matrix_header(columns):
        return "requirements"
    mapping = _event_mapping(columns)
    if all(mapping[key] is not None for key in ("title", "when", "participants")):
        return "events"
    return "unresolved"


def _title_band(row):
    tokens = tuple(v.strip() for v in row if v.strip())
    return len(tokens) == 1 and bool(re.fullmatch(
        r"(?:annual )?training(?: requirements| summary| sessions| records)?(?:\s+20\d{2})?",
        tokens[0], re.IGNORECASE))


def _rows_and_header(raw_rows):
    """One supported header after optional recognized title, never arbitrary prose."""
    possibilities = [(n, row, _header_kind(row))
                     for n, row in enumerate(raw_rows[:MAX_HEADER_ROWS])
                     if _header_kind(row) != "unresolved"]
    if not possibilities:
        return None, ("No supported Training sessions or annual requirements headers.",)
    patterns = {tuple(_name(v) for v in row) for _, row, _ in possibilities}
    if len(patterns) != 1:
        return None, ("Conflicting Training table headers require source review.",)
    return possibilities[0], ()


def _bounds(columns, rows):
    if (len(columns) == 0 or len(columns) > MAX_COLUMNS or len(rows) > MAX_ROWS
            or len(columns) * max(1, len(rows)) > MAX_CELLS):
        raise ValueError("Training source table exceeds safe review limits.")
    if sum(len(cell) for row in rows for cell in row) > MAX_REVIEW_BYTES:
        raise ValueError("Training source table is too large to review safely.")
    if any(len(row) != len(columns) for row in rows):
        raise ValueError("Training source rows have different physical cell counts.")


def training_tables(content: SourceContent, profile: ReportProfile):
    """Only verified, stored originals; Word requires section-confirmed tables."""
    from app import monthly_report_sources as sources
    source = content.source
    if source.suffix not in {".csv", ".xlsx", ".docx"}:
        raise ValueError("Import Training from an original Word, CSV or XLSX file.")
    raw = sources.source_bytes(profile, source)  # rejects changed/missing bytes
    if sha256(raw).hexdigest() != source.sha256:
        raise ValueError("The Training original changed; reopen its source.")
    selected = []
    if source.suffix in {".csv", ".xlsx"}:
        for number, table in enumerate(content.tables, 1):
            columns = tuple(str(x) for x in table.columns)
            rows = tuple(tuple(str(cell) for cell in row) for row in table.rows)
            _bounds(columns, rows)
            selected.append(TrainingTableSource(
                source.filename, source.id, source.sha256, source.fingerprint,
                number, source_reference(source, number), columns, rows))
    else:
        from app.monthly_report_import import inspect_docx
        original = sources._path(profile, source.sha256, source.suffix)
        inspection = inspect_docx(original)
        if inspection.sha256 != source.sha256 or len(inspection.items) != len(source.page_texts):
            raise ValueError("The Word inspection changed; review the saved original again.")
        for number, item in enumerate(inspection.items, 1):
            if (item.kind != "table" or item.part != "word/document.xml"
                    or item.section != "training"):
                continue
            rows = tuple(tuple(str(cell) for cell in row) for row in item.rows)
            if not rows:
                continue
            _bounds(rows[0], rows)
            selected.append(TrainingTableSource(
                source.filename, source.id, source.sha256, source.fingerprint,
                number, source_reference(source, number), rows[0], rows,
                item.id, item.section, True))
    return tuple(selected)


def _normalize_site(value, profile):
    matches = []
    name = _name(value)
    if not name:
        return ""
    for site in profile.facilities:
        if name in {_name(v) for v in (site.key, site.title, *site.aliases)}:
            matches.append(site.title)
    return matches[0] if len(matches) == 1 else ""


def _event_issues(row, period):
    title, when, mode, people, hours = row.values
    errors = []
    if not title:
        errors.append("Training topic is missing.")
    try:
        date_value = date.fromisoformat(when)
    except ValueError:
        errors.append("Training date is missing or ambiguous.")
    else:
        if not period.start <= date_value <= period.end:
            errors.append("Historical/other-month session: not completed this month.")
    if mode not in FORMATS:
        errors.append("Training format needs review.")
    if not people or "," in people:
        errors.append("Participants are missing or ambiguously separated.")
    if hours:
        try:
            number = float(hours)
            if not math.isfinite(number) or number <= 0:
                raise ValueError()
        except ValueError:
            errors.append("Hours must be positive or left blank.")
    if row.status and _name(row.status) not in COMPLETE:
        errors.append("Source status does not show completed training.")
    return tuple(errors)


def _matrix_issues(row, source_year, profile):
    values = row.values
    issues = []
    if not values[0]:
        issues.append("Training staff member is missing.")
    if not values[1] or not _normalize_site(values[1], profile):
        issues.append("Training site is missing or outside selected sites.")
    if any(v not in STATUSES for v in values[2:]):
        issues.append("Unknown standing-training status needs review.")
    if source_year is None:
        issues.append("The requirements' source year must be confirmed.")
    return tuple(issues)


def review_training_table(source: TrainingTableSource, profile: ReportProfile,
                          period: ReportPeriod, *, source_year: int | None = None):
    """Produce immutable candidate rows, retaining all source values and places.

    A prior *report* month is never inferred from a file title. Requirements
    need an explicitly reviewed year; dated events use their real dates, not
    the report's selected month or annual completion statuses.
    """
    if source_year is not None and (type(source_year) is not int
                                    or not 1000 <= source_year <= 9999):
        raise ValueError("Choose an explicit four-digit requirements source year.")
    # Word candidates carry a title/header inside their full native row list.
    physical = source.rows if source.native_word else (source.columns, *source.rows)
    head, header_error = _rows_and_header(physical)
    if head is None:
        return TrainingImportReview(source, period.key, "unresolved", source_year,
                                    source.columns, tuple(physical), (), (),
                                    tuple(header_error), (), not source.native_word)
    header_index, columns, kind = head
    _bounds(columns, physical)
    header_map = _event_mapping(columns) if kind == "events" else None
    questions, unresolved, candidates = [], [], []
    for index, values in enumerate(physical):
        number = index + 1
        if index < header_index:
            if not _title_band(values):
                unresolved.append((number, values, "Unknown row before Training headers."))
            continue
        if index == header_index:
            continue
        if not any(str(cell).strip() for cell in values):
            continue
        if tuple(_name(v) for v in values) == tuple(_name(v) for v in columns):
            continue
        if kind == "events":
            assert header_map is not None
            def value(key):
                position = header_map[key]
                return values[position].strip() if position is not None else ""
            current = (
                value("title"), value("when"), value("mode"),
                value("participants"), value("hours"))
            status = value("status")
        else:
            current = (
                values[0].strip(), _normalize_site(values[1], profile),
                *(value.strip() for value in values[2:]))
            status = ""
        origin = TrainingOrigin(
            source.source_id, source.source_sha256, source.source_fingerprint,
            source.reference, source.number, number, tuple(columns), tuple(values))
        row = TrainingImportRow(origin, tuple(current), status)
        row = replace(row, issues=_event_issues(row, period) if kind == "events"
                      else _matrix_issues(row, source_year, profile))
        candidates.append(row)
    # One source row may appear again after a repeated heading or copying.
    # Conflicting real training rows stay visible, not silently deduplicated.
    groups = {}
    for index, row in enumerate(candidates):
        if kind == "events" and row.values[0] and row.values[1]:
            identity = (row.values[0].casefold(), row.values[1], row.values[3].casefold())
        elif kind == "requirements" and row.values[0] and row.values[1]:
            identity = (row.values[0].casefold(), row.values[1].casefold())
        else:
            continue
        groups.setdefault(identity, []).append(index)
    duplicate_indices = {index for indices in groups.values() if len(indices) > 1
                         for index in indices}
    candidates = [replace(row, issues=(*row.issues, "Duplicate Training source row needs review."))
                  if index in duplicate_indices else row
                  for index, row in enumerate(candidates)]
    normalized_cols = EVENT_COLUMNS if kind == "events" else (
        "Team member", "Site", *columns[2:])
    if kind == "events":
        for name in ("title", "when", "mode", "participants"):
            if header_map[name] is None:
                questions.append("Map " + name + " from the original header before accepting sessions.")
        for name, aliases in EVENT_HEADERS.items():
            if len(_column_positions(columns, aliases)) > 1:
                questions.append("Multiple " + name + " columns need a deliberate choice.")
    if kind == "requirements" and source_year is None:
        questions.append("Confirm which calendar year the original requirements belong to.")
    if source.native_word:
        questions.append("Confirm the native Word table's merged cells and layout before import.")
    return TrainingImportReview(
        source, period.key, kind, source_year, tuple(columns), tuple(physical),
        tuple(normalized_cols), tuple(candidates), tuple(questions),
        tuple(unresolved), native_layout_confirmed=not source.native_word)


def correct_training_row(review: TrainingImportReview, key: str, changes: dict[str, str],
                         *, expected_revision: str, profile: ReportProfile,
                         period: ReportPeriod):
    """CAS-bound row review; do not rewrite original source cells."""
    if review.revision != expected_revision or review.period_key != period.key:
        raise ValueError("The Training review changed. Reopen its current rows.")
    if review.kind not in ("events", "requirements") or not isinstance(changes, dict):
        raise ValueError("Only a mapped Training row can be corrected.")
    matches = [i for i, row in enumerate(review.rows) if row.key == key]
    if len(matches) != 1:
        raise ValueError("The original Training row is missing or ambiguous.")
    index = matches[0]
    row = review.rows[index]
    permitted = review.normalized_columns if review.kind == "requirements" else (
        *EVENT_COLUMNS, "Completion status")
    if not changes or any(name not in permitted or not isinstance(value, str)
                          or len(value) > 1000 for name, value in changes.items()):
        raise ValueError("Choose supported Training fields for correction.")
    values = dict(zip(review.normalized_columns, row.values))
    status = row.status
    for name, value in changes.items():
        if name == "Completion status":
            status = value.strip()
        elif name == "Site":
            values[name] = _normalize_site(value, profile)
        else:
            values[name] = value.strip()
    updated = replace(row, values=tuple(values[name] for name in review.normalized_columns),
                      status=status,
                      corrections=tuple(sorted({**dict(row.corrections), **changes}.items())))
    updated = replace(updated,
                      issues=_event_issues(updated, period) if review.kind == "events"
                      else _matrix_issues(updated, review.source_year, profile))
    rows = list(review.rows)
    rows[index] = updated
    return replace(review, rows=tuple(rows))


def exclude_training_row(review: TrainingImportReview, key: str, *,
                         expected_revision: str):
    if review.revision != expected_revision:
        raise ValueError("The Training review changed. Reopen its current rows.")
    matches = [index for index, row in enumerate(review.rows) if row.key == key]
    if len(matches) != 1:
        raise ValueError("This source Training row is unavailable.")
    rows = list(review.rows)
    rows[matches[0]] = replace(rows[matches[0]], excluded=True)
    return replace(review, rows=tuple(rows))


def confirm_training_word_layout(review: TrainingImportReview, *,
                                 expected_revision: str):
    if review.revision != expected_revision:
        raise ValueError("The Training review changed. Reopen the source layout.")
    if not review.source.native_word:
        return review
    issues = tuple(item for item in review.issues if not item.startswith(
        "Confirm the native Word table's merged cells"))
    return replace(review, native_layout_confirmed=True, issues=issues)


def reimport_training_review(previous: TrainingImportReview,
                             incoming: TrainingImportReview):
    """Same source, table, year and reporting scope: preserve manual decisions."""
    fields = ("source", "original_columns", "original_rows", "period_key",
              "kind", "source_year")
    if any(getattr(previous, name) != getattr(incoming, name) for name in fields):
        raise ValueError("Training source, period or year changed. Compare before replacing edits.")
    return previous


def accepted_training_block(review: TrainingImportReview, block: ResolvedBlock,
                            *, expected_block_fingerprint: str,
                            carry_prior_requirements: bool = False):
    """Explicit report-only accept; never write the contract's shared matrix.

    The current interface's one monthly event table and one standing matrix
    are reused. Existing notes, photos, native imported tables and user events
    are authoritative. Old events cannot be relabeled current by this function.
    """
    if block.key != "training_summary" or block.source == "Omit":
        raise ValueError("Include Training in this report before importing it.")
    if block.fingerprint != expected_block_fingerprint:
        raise ValueError("Training changed. Review the current saved edits before importing.")
    if not review.ready_for_import:
        raise ValueError("Review unknown Training rows, dates, sites and source layout first.")
    selected = [row for row in review.rows if not row.excluded]
    # An existing native/plain mapped source table is visible report content.
    # Do not add a second copy of its rows or erase authored changes silently.
    if any(table.reference in (review.source.reference,
                               "docx:" + review.source.source_sha256 + ":" + review.source.word_item_id)
           for table in block.extra_tables):
        raise ValueError("This Training source table is already in the report. "
                         "Review its replacement before importing normalized rows.")
    if review.kind == "events":
        table = next((t for t in block.extra_tables if t.reference == EVENT_REF), None)
        for item in selected:
            name, iso, mode, people, hours = item.values
            existing = table.rows if table else ()
            identity = (name.casefold(), iso, people.casefold())
            if any((old[0].casefold(), old[1], old[3].casefold()) == identity
                   and old != (name, iso, mode, people, hours) for old in existing):
                raise ValueError("A manually edited Training session conflicts with the imported row.")
            table = add_event(table, title=name, when=date.fromisoformat(iso),
                              mode=mode, participants=tuple(p.strip() for p in re.split(r";\s*", people) if p.strip()), hours=hours,
                              period=ReportPeriod(int(review.period_key[:4]),
                                                  int(review.period_key[-2:])))
        updated = apply_tables(block, None, table)
    else:
        year = review.source_year
        report_year = int(review.period_key[:4])
        if year is None:
            raise ValueError("Confirm the source's annual Training requirements year.")
        if year != report_year and not carry_prior_requirements:
            raise ValueError("Review older requirements before carrying them into another year.")
        values = []
        for item in selected:
            if year == report_year:
                values.append(item.values)
            else:
                values.append((item.values[0], item.values[1],
                               *("" if status == "" else "Not recorded"
                                 for status in item.values[2:])))
        matrix = validate_matrix(ReportTable(
            review.normalized_columns, tuple(values), MATRIX_REF))
        existing = next((t for t in block.extra_tables if t.reference == MATRIX_REF), None)
        if existing is not None and existing != matrix:
            raise ValueError("The report already has different standing requirements. Review replacement.")
        updated = apply_tables(block, matrix, None)
    if review.source.reference not in updated.references:
        updated = replace(updated, references=(*updated.references, review.source.reference))
    return updated
