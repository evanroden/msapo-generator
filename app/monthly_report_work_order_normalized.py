"""Source-bound, reviewable work-order records shared by future CSV/PDF/DOCX adapters.

No parser may silently convert an aggregate grid into individual work orders,
invent a site/date/status/category, or discard unknown source cells. These
immutable values are *candidates*, not accepted monthly report claims. A
separate explicit review step must approve corrections before publication.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from hashlib import sha256
import json
import re

from app.monthly_report_model import ReportPeriod, ReportProfile, ReportTable
from app.monthly_report_sources import SourceContent, SourceTable, source_reference

FIELDS = ("work_order", "site", "work_date", "completed_date", "status", "work_type", "trade")
REQUIRED = ("work_order", "site", "work_date", "status")
REVIEW_COLUMNS = ("Source row", "Work order", "Site", "Work date", "Completed date",
                  "Status", "PM / non-PM", "Trade", "Review needed")
ALIASES = {
    "work_order": {"workorder", "workordernumber", "workorderid", "wonumber",
                   "wo", "woid", "ticketnumber", "requestid"},
    "site": {"facility", "site", "location", "building", "hospital", "campus"},
    "work_date": {"date", "workdate", "reporteddate", "servicedate", "eventdate",
                  "createddate", "requestdate", "openeddate"},
    "completed_date": {"completiondate", "finishdate", "finisheddate", "closeddate"},
    "status": {"status", "workorderstatus", "state", "currentstatus", "wostatus"},
    "work_type": {"worktype", "type", "maintenancecategory", "category",
                  "pmnonpm", "preventivemaintenance", "tasktype"},
    "trade": {"trade", "discipline", "craft", "skill", "department"},
}
COMPLETE = {"completed", "complete", "closed", "finished", "done"}
OPEN = {"open", "pending", "inprogress", "notstarted", "unresolved", "awaitingparts"}
PM = {"pm", "preventive", "preventivemaintenance", "plannedmaintenance"}
NON_PM = {"nonpm", "corrective", "correctivemaintenance", "repair",
          "reactive", "emergency", "breakdown", "cm"}
MONTHS = {name.casefold() for name in (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    "January", "February", "March", "April", "June", "July", "August",
    "September", "October", "November", "December")}


def _name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _date(value):
    # A short date such as 03/04/26 is intentionally not guessed.
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


@dataclass(frozen=True)
class ColumnMapping:
    """Physical column positions; duplicate header text never collapses cells."""
    work_order: int | None = None
    site: int | None = None
    work_date: int | None = None
    completed_date: int | None = None
    status: int | None = None
    work_type: int | None = None
    trade: int | None = None
    ambiguous: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceRow:
    """Exact original row and identity, including zero/blank and unknown fields."""
    source_id: str
    source_sha256: str
    source_fingerprint: str
    filename: str
    table_number: int
    row_number: int
    columns: tuple[str, ...]
    cells: tuple[str, ...]

    @property
    def key(self):
        return sha256(json.dumps((self.source_sha256, self.table_number, self.row_number),
                                 separators=(",", ":")).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class WorkOrderRow:
    origin: SourceRow
    work_order: str = ""
    site: str = ""
    work_date: str = ""
    completed_date: str = ""
    status: str = ""
    work_type: str = ""
    trade: str = ""
    issues: tuple[str, ...] = ()
    corrections: tuple[tuple[str, str], ...] = ()
    excluded: bool = False

    @property
    def key(self):
        return self.origin.key

    @property
    def unmapped(self):
        return tuple((index, heading, self.origin.cells[index])
                     for index, heading in enumerate(self.origin.columns))


@dataclass(frozen=True)
class WorkOrderReview:
    source_id: str
    source_sha256: str
    source_fingerprint: str
    source_reference: str
    table_number: int
    kind: str  # records, aggregate, or unresolved
    mapping: ColumnMapping
    allowed_sites: tuple[tuple[str, tuple[str, ...]], ...]
    period_key: str
    rows: tuple[WorkOrderRow, ...]
    original_columns: tuple[str, ...]
    original_rows: tuple[tuple[str, ...], ...]
    questions: tuple[str, ...] = ()

    @property
    def revision(self):
        return sha256(json.dumps(asdict(self), sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @property
    def needs_review(self):
        return bool(self.questions or any(row.issues for row in self.rows))

    def counts(self):
        # Each source row has one auditable disposition; no loss or duplication.
        return {
            "source_rows": len(self.original_rows),
            "included": sum(not row.issues and not row.excluded for row in self.rows),
            "needs_review": sum(bool(row.issues) and not row.excluded for row in self.rows),
            "excluded": sum(row.excluded for row in self.rows),
            "unmapped_rows": len(self.original_rows) - len(self.rows),
        }

    def review_table(self):
        # For a read-only or explicitly reviewed edit UI. No automatic publish.
        rows = tuple((str(row.origin.row_number), row.work_order, row.site,
                      row.work_date, row.completed_date, row.status,
                      row.work_type, row.trade, "; ".join(row.issues))
                     for row in self.rows)
        return ReportTable(REVIEW_COLUMNS, rows, self.source_reference)


def suggest_mapping(columns):
    values = tuple(_name(v) for v in columns)
    picks, ambiguous = {}, []
    for name in FIELDS:
        positions = [n for n, title in enumerate(values) if title in ALIASES[name]]
        picks[name] = positions[0] if len(positions) == 1 else None
        if len(positions) > 1:
            ambiguous.append(name)
    # A physical column cannot silently stand for two unrelated facts.
    used = [p for p in picks.values() if p is not None]
    if len(used) != len(set(used)):
        raise ValueError("Source column identities overlap. Review the mapping.")
    return ColumnMapping(**picks, ambiguous=tuple(ambiguous))


def _sites(profile):
    return tuple((site.key, tuple(dict.fromkeys(_name(value) for value in
                  (site.key, site.title, *site.aliases))))
                 for site in profile.facilities)


def _site(value, sites):
    if not value:
        return ""
    matches = [key for key, labels in sites if _name(value) in labels]
    return matches[0] if len(matches) == 1 else ""


def _classified(field, value, sites):
    if field == "site":
        return _site(value, sites)
    if field in ("work_date", "completed_date"):
        return _date(value)
    name = _name(value)
    if field == "status":
        return "Completed" if name in COMPLETE else "Open" if name in OPEN else ""
    if field == "work_type":
        return "PM" if name in PM else "Non-PM" if name in NON_PM else ""
    return value.strip()


def _issues(row, sites, period_key):
    questions = []
    for field in REQUIRED:
        if not getattr(row, field):
            questions.append(field + " needs review")
    for optional in ("completed_date", "work_type"):
        # Missing optional source values remain blank, never numeric zero.
        value = dict(row.corrections).get(optional)
        if value is not None and value.strip() and not getattr(row, optional):
            questions.append(optional + " needs review")
    if row.site and row.site not in {key for key, _ in sites}:
        questions.append("site needs review")
    if row.work_date:
        try:
            if date.fromisoformat(row.work_date).strftime("%Y-%m") != period_key:
                questions.append("source date is outside this report period")
        except ValueError:
            questions.append("work_date needs review")
    return tuple(dict.fromkeys(questions))


def _aggregate(columns, rows):
    headings = tuple(_name(v) for v in columns)
    return (any(value in MONTHS or re.fullmatch(r"20\d\d(?:0?[1-9]|1[0-2])", value)
                for value in headings)
            or ("count" in " ".join(headings) or "total" in " ".join(headings))
            and not any(value in ALIASES["work_order"] for value in headings))


def normalize_table(content: SourceContent, table_number: int,
                    profile: ReportProfile, period: ReportPeriod, *,
                    mapping: ColumnMapping | None = None) -> WorkOrderReview:
    """Interpret any table without discarding rows or accepting unknown facts."""
    if type(table_number) is not int or not 1 <= table_number <= len(content.tables):
        raise ValueError("Choose an existing source table.")
    source, table = content.source, content.tables[table_number - 1]
    columns = tuple(str(v) for v in table.columns)
    if not columns or len(columns) > 256 or len(table.rows) > 20_000:
        raise ValueError("Source table exceeds the normalized review budget.")
    rows = tuple(tuple(str(v) if v is not None else "" for v in row)
                 for row in table.rows)
    if any(len(row) > len(columns) for row in rows):
        raise ValueError("Source table has more cells than declared columns.")
    if mapping is None:
        mapping = suggest_mapping(columns)
    positions = [getattr(mapping, field) for field in FIELDS]
    if (any(pos is not None and (type(pos) is not int or not 0 <= pos < len(columns))
            for pos in positions)
            or len([pos for pos in positions if pos is not None])
               != len({pos for pos in positions if pos is not None})):
        raise ValueError("The reviewed source column positions are invalid.")
    sites = _sites(profile)
    kind = ("records" if mapping.work_order is not None
            else "aggregate" if _aggregate(columns, rows) else "unresolved")
    questions = tuple(dict.fromkeys((
        *("Ambiguous " + field + " column" for field in mapping.ambiguous),
        *("Map " + field + " before including records" for field in REQUIRED
          if getattr(mapping, field) is None),
        *("Aggregate counts are not individual work-order records",) if kind == "aggregate" else (),
    )))
    records = []
    if kind == "records":
        for number, values in enumerate(rows, 1):
            cells = values + ("",) * (len(columns) - len(values))
            origin = SourceRow(source.id, source.sha256, source.fingerprint, source.filename,
                               table_number, number, columns, cells)
            parsed = {}
            corrections = []
            for field in FIELDS:
                index = getattr(mapping, field)
                raw = cells[index] if index is not None else ""
                parsed[field] = _classified(field, raw, sites)
                # Invalid supplied data must not turn into a valid zero/blank.
                if raw.strip() and not parsed[field]:
                    corrections.append((field, raw))
            row = WorkOrderRow(origin, **parsed, corrections=tuple(corrections))
            records.append(replace(row, issues=_issues(row, sites, period.key)))
    return WorkOrderReview(
        source.id, source.sha256, source.fingerprint,
        source_reference(source, table_number), table_number, kind, mapping,
        sites, period.key, tuple(records), columns, rows, questions,
    )


def correct_row(review: WorkOrderReview, key: str, changes: dict[str, str], *,
                expected_revision: str) -> WorkOrderReview:
    """CAS-bound corrections; old review widgets cannot overwrite newer rows."""
    if review.revision != expected_revision:
        raise ValueError("Work-order review changed. Reopen the current rows before editing.")
    if review.kind != "records" or not isinstance(changes, dict):
        raise ValueError("Only a reviewed work-order row can be corrected.")
    if not changes or any(field not in FIELDS or not isinstance(value, str)
                          or len(value) > 1000 for field, value in changes.items()):
        raise ValueError("Choose supported work-order fields for this correction.")
    matches = [i for i, row in enumerate(review.rows) if row.key == key]
    if len(matches) != 1:
        raise ValueError("The work-order row is missing or ambiguous.")
    index = matches[0]
    original = review.rows[index]
    parsed = {field: _classified(field, value, review.allowed_sites)
              for field, value in changes.items()}
    edits = dict(original.corrections)
    edits.update(changes)
    revised = replace(original, **parsed, corrections=tuple(sorted(edits.items())))
    revised = replace(revised, issues=_issues(revised, review.allowed_sites, review.period_key))
    updated = list(review.rows)
    updated[index] = revised
    return replace(review, rows=tuple(updated))


def exclude_row(review: WorkOrderReview, key: str, *, expected_revision: str,
                excluded: bool) -> WorkOrderReview:
    if review.revision != expected_revision or type(excluded) is not bool:
        raise ValueError("Work-order review changed. Reopen the current rows.")
    positions = [i for i, row in enumerate(review.rows) if row.key == key]
    if len(positions) != 1:
        raise ValueError("The work-order row is missing or ambiguous.")
    rows = list(review.rows)
    rows[positions[0]] = replace(rows[positions[0]], excluded=excluded)
    return replace(review, rows=tuple(rows))


def reimport_review(previous: WorkOrderReview, current: WorkOrderReview) -> WorkOrderReview:
    """Idempotent exact-source reimport; another source needs deliberate review."""
    if (previous.source_sha256 != current.source_sha256 or
            previous.table_number != current.table_number or
            previous.original_columns != current.original_columns or
            previous.original_rows != current.original_rows):
        raise ValueError("The work-order source changed. Compare its rows before replacing your reviewed edits.")
    # Preserve explicit corrections/exclusions and their current target period.
    return previous
