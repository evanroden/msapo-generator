"""Reviewable CMMS -> Section 5 service-call adapter.

This does not modify the source importer, native Word design, or saved drafts.
Only an explicitly reviewed, source-bound set of *completed* onsite-call rows
can be turned into the established five-column Service Calls block. Unknown,
scheduled, priced or incomplete work is never silently marked completed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Mapping

from app.monthly_report_model import ReportPeriod, ReportProfile, ResolvedBlock
from app.monthly_report_sources import SourceContent, SourceTable, source_reference
from app.monthly_report_work_order_normalized import SourceRow
from app.monthly_report_content_policy import contains_price, price_column

FIELDS = ("wo", "finished", "area", "task", "tag", "site", "status")
OUTPUT_COLUMNS = ("WO #", "Finish Date", "Area", "Task Code-Description", "Tag #")
HEADERS = {
    "wo": ("wo", "wonumber", "workorder", "workordernumber", "workorderid",
           "ticketnumber", "ticket", "jobnumber", "servicerequestnumber"),
    "finished": ("finishdate", "completiondate", "datecompleted", "actualfinish",
                 "closeddate", "completedon", "workcompleteddate"),
    "area": ("area", "room", "location", "zone", "workarea", "buildingarea"),
    "task": ("taskcodedescription", "taskdescription", "taskcode", "description",
             "workdescription", "jobdescription", "workperformed",
             "task", "serviceperformed", "servicework"),
    "tag": ("tagnumber", "tag", "equipmenttag", "assettag", "assetid",
             "equipmentid", "equipmentnumber"),
    "site": ("site", "facility", "hospital", "campus", "sitecode"),
    "status": ("status", "workorderstatus", "wostatus", "currentstatus", "state"),
}
COMPLETE = {"closed", "complete", "completed", "finished", "done"}
UNFINISHED = {"open", "new", "scheduled", "planned", "pending", "inprogress",
              "notstarted", "awaitingparts", "onhold", "deferred"}
TITLES = {"maintenanceschedule", "inhousemaintenance", "workorderstatus",
          "pmstatus", "servicecalls", "maintenanceworkorders"}
MAX_ROWS = 20_000
MAX_CELLS = 200_000


def _normalize(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


@dataclass(frozen=True)
class CallMapping:
    wo: int | None = None
    finished: int | None = None
    area: int | None = None
    task: int | None = None
    tag: int | None = None
    site: int | None = None
    status: int | None = None
    ambiguous: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnmatchedRow:
    number: int
    cells: tuple[str, ...]
    reason: str
    excluded: bool = False


@dataclass(frozen=True)
class ServiceCallRow:
    origin: SourceRow
    wo: str = ""
    finished: str = ""
    area: str = ""
    task: str = ""
    tag: str = ""
    site: str = ""
    status: str = ""
    issues: tuple[str, ...] = ()
    corrections: tuple[tuple[str, str], ...] = ()
    excluded: bool = False

    @property
    def key(self):
        return self.origin.key


@dataclass(frozen=True)
class ServiceCallReview:
    source_id: str
    source_sha256: str
    source_fingerprint: str
    filename: str
    table_number: int
    source_reference: str
    period_key: str
    facilities: tuple[tuple[str, str, tuple[str, ...]], ...]
    original_columns: tuple[str, ...]
    original_rows: tuple[tuple[str, ...], ...]
    mapping: CallMapping
    rows: tuple[ServiceCallRow, ...]
    unmatched: tuple[UnmatchedRow, ...] = ()
    notes: tuple[str, ...] = ()
    financial_columns: tuple[int, ...] = ()
    financial_exclusion_confirmed: bool = False
    native_layout_confirmed: bool = True

    @property
    def revision(self):
        return sha256(json.dumps(asdict(self), sort_keys=True,
                                 ensure_ascii=False).encode()).hexdigest()

    @property
    def ready_for_inclusion(self):
        return (bool(self.rows) and all(item.excluded for item in self.unmatched) and not self.notes
                and all(not r.issues or r.excluded for r in self.rows)
                and any(not r.excluded for r in self.rows)
                and (not self.financial_columns or self.financial_exclusion_confirmed)
                and self.native_layout_confirmed)

    def counts(self):
        return {"original": len(self.original_rows),
                "reviewed_candidates": len(self.rows),
                "ready": sum(not r.issues and not r.excluded for r in self.rows),
                "unresolved": sum(bool(r.issues) and not r.excluded for r in self.rows),
                "excluded": sum(r.excluded for r in self.rows),
                "unmatched": sum(not item.excluded for item in self.unmatched)}

    def unmapped(self, row):
        used = {getattr(self.mapping, key) for key in FIELDS}
        return tuple((n, label, row.origin.cells[n])
                     for n, label in enumerate(self.original_columns) if n not in used)


def suggest_call_mapping(columns, overrides: Mapping[str, int | None] | None = None):
    values = tuple(_normalize(v) for v in columns)
    overrides = {} if overrides is None else overrides
    if any(name not in FIELDS for name in overrides):
        raise ValueError("Unknown CMMS service-call column.")
    fields, ambiguous = {}, []
    for name in FIELDS:
        indices = [i for i, header in enumerate(values) if header in HEADERS[name]]
        if len(indices) > 1 and name not in overrides:
            ambiguous.append(name)
        choice = overrides.get(name, indices[0] if len(indices) == 1 else None)
        if choice is not None and (type(choice) is not int or not 0 <= choice < len(values)):
            raise ValueError("Choose a physical source column from this table.")
        fields[name] = choice
    used = [index for index in fields.values() if index is not None]
    if len(set(used)) != len(used):
        raise ValueError("One source column cannot fill two service-call fields.")
    return CallMapping(**fields, ambiguous=tuple(ambiguous))


def _date(text):
    text = str(text).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""  # Never assume MDY or DMY for numeric dates.


def _facilities(profile):
    return tuple((site.key, site.title, tuple(_normalize(s) for s in
                  (site.key, site.title, *site.aliases)))
                 for site in profile.facilities)


def _site(value, facilities):
    matches = [key for key, title, aliases in facilities
               if _normalize(value) and _normalize(value) in aliases]
    return matches[0] if len(matches) == 1 else ""


def _status(value):
    n = _normalize(value)
    return "Completed" if n in COMPLETE else "Unfinished" if n in UNFINISHED else ""


def _row_issues(row, period_key, facilities):
    result = []
    if not row.wo:
        result.append("Missing work-order identifier.")
    if not row.task:
        result.append("Task description missing.")
    if not row.area:
        result.append("Area is missing; check original.")
    if not row.site or row.site not in {key for key, _, _ in facilities}:
        result.append("Site scope needs review.")
    if not row.finished:
        result.append("Finish date missing or ambiguous; not a completed call.")
    elif row.finished[:7] != period_key:
        result.append("Finish date is outside the selected report month.")
    if row.status != "Completed":
        result.append("Completion status is not verified.")
    if contains_price(row.task):
        result.append("Task text contains price-related content.")
    return tuple(result)


def _duplicates(rows):
    counts = {}
    for row in rows:
        if row.wo and row.site and not row.excluded:
            key = row.site, row.wo.casefold()
            counts[key] = counts.get(key, 0) + 1
    result = []
    for row in rows:
        issues = tuple(issue for issue in row.issues
                       if issue != "Duplicate work-order identity.")
        if (row.wo and row.site and not row.excluded
                and counts.get((row.site, row.wo.casefold()), 0) > 1):
            issues += ("Duplicate work-order identity.",)
        result.append(replace(row, issues=issues))
    return tuple(result)


def review_service_calls(content: SourceContent, profile: ReportProfile,
                         period: ReportPeriod, *, table_number=1,
                         mapping: CallMapping | None = None,
                         native_layout_confirmed: bool | None = None,
                         source_table: SourceTable | None = None,
                         source_rows: tuple[tuple[str, ...], ...] | None = None,
                         original_numbers: tuple[int, ...] | None = None):
    """Adapt a supported source table while preserving every physical cell.

    DOCX callers supply the Word-inspected table explicitly, with its actual
    source item index. The default CSV/XLSX path reuses existing SourceContent
    from the saved importer. No external parsing or source mutation happens.
    """
    if type(table_number) is not int or table_number < 1:
        raise ValueError("Choose a valid source table identity.")
    if source_table is None:
        if table_number > len(content.tables):
            raise ValueError("Choose a table from the saved source.")
        source_table = content.tables[table_number - 1]
    if native_layout_confirmed is None:
        native_layout_confirmed = content.source.suffix in (".csv", ".xlsx")
    columns = tuple(str(v) for v in source_table.columns)
    rows = tuple(tuple(str(v) if v is not None else "" for v in row)
                 for row in (source_rows if source_rows is not None else source_table.rows))
    if (not columns or len(columns) > 200 or len(rows) > MAX_ROWS
            or len(rows) * len(columns) > MAX_CELLS
            or any(len(row) > len(columns) for row in rows)):
        raise ValueError("CMMS table exceeds safe source-row/column review bounds.")
    if mapping is None:
        mapping = suggest_call_mapping(columns)
    positions = [getattr(mapping, name) for name in FIELDS]
    if (any(x is not None and (type(x) is not int or x < 0 or x >= len(columns))
            for x in positions) or len([x for x in positions if x is not None])
            != len({x for x in positions if x is not None})):
        raise ValueError("Invalid CMMS source column mapping.")
    if original_numbers is None:
        original_numbers = tuple(range(2, len(rows) + 2))  # header + data
    if len(original_numbers) != len(rows) or len(set(original_numbers)) != len(rows):
        raise ValueError("Original CMMS source-row identities are invalid.")
    facilities = _facilities(profile)
    candidates, unmatched = [], []
    source = content.source
    for row_no, original in zip(original_numbers, rows):
        cells = original + ("",) * (len(columns) - len(original))
        if not any(cell.strip() for cell in cells):
            continue  # Empty source rows are preserved in original_rows.
        wo_index = mapping.wo
        if wo_index is None or not cells[wo_index].strip():
            unmatched.append(UnmatchedRow(row_no, cells, "No unambiguous work-order ID; review continuation or group row."))
            continue
        if any("\n" in cell or "\r" in cell for cell in cells):
            unmatched.append(UnmatchedRow(row_no, cells, "Multiline source row needs review before insertion."))
            continue
        def value(name):
            index = getattr(mapping, name)
            return cells[index].strip() if index is not None else ""
        origin = SourceRow(source.id, source.sha256, source.fingerprint,
                           source.filename, table_number, row_no, columns, cells)
        status_value = value("status")
        row = ServiceCallRow(
            origin, wo=value("wo"), finished=_date(value("finished")),
            area=value("area"), task=value("task"), tag=value("tag"),
            site=_site(value("site"), facilities), status=_status(status_value))
        candidates.append(replace(row, issues=_row_issues(row, period.key, facilities)))
    from app.monthly_report_content_policy import table_price_columns, ambiguous_price_columns
    financial = tuple(sorted(set(table_price_columns(columns, rows)) |
                             set(ambiguous_price_columns(columns, rows)) |
                             {n for n, title in enumerate(columns) if price_column(title)}))
    notes = tuple(
        ["Choose or correct the " + name + " column before including this table."
         for name in ("wo", "task") if getattr(mapping, name) is None] +
        ["Ambiguous source header: " + name for name in mapping.ambiguous]
    )
    return ServiceCallReview(
        source.id, source.sha256, source.fingerprint, source.filename,
        table_number, source_reference(source, table_number), period.key,
        facilities, columns, rows, mapping, _duplicates(candidates),
        tuple(unmatched), notes, financial, native_layout_confirmed=native_layout_confirmed)


def correct_service_call(review: ServiceCallReview, key, changes: Mapping[str, str], *,
                         expected_revision):
    if review.revision != expected_revision:
        raise ValueError("Maintenance source changed. Review the current rows before applying edits.")
    if not isinstance(changes, Mapping) or not changes or any(
            name not in FIELDS or not isinstance(value, str) or len(value) > 4000
            for name, value in changes.items()):
        raise ValueError("Choose supported service-call fields for correction.")
    matches = [n for n, row in enumerate(review.rows) if row.key == key]
    if len(matches) != 1:
        raise ValueError("The service-call source row is missing or ambiguous.")
    number = matches[0]
    current = review.rows[number]
    fields = {}
    for name, value in changes.items():
        if name == "finished":
            fields[name] = _date(value)
        elif name == "site":
            fields[name] = _site(value, review.facilities)
        elif name == "status":
            fields[name] = _status(value)
        else:
            fields[name] = value.strip()
    revised = replace(current, **fields,
        corrections=tuple(sorted({**dict(current.corrections), **changes}.items())))
    revised = replace(revised, issues=_row_issues(
        revised, review.period_key, review.facilities))
    rows = list(review.rows)
    rows[number] = revised
    return replace(review, rows=_duplicates(rows))


def exclude_service_call(review: ServiceCallReview, key, *, expected_revision, excluded=True):
    if review.revision != expected_revision or type(excluded) is not bool:
        raise ValueError("Maintenance review changed. Reopen its current rows.")
    matches = [n for n, row in enumerate(review.rows) if row.key == key]
    if len(matches) != 1:
        raise ValueError("The source row is no longer selectable.")
    rows = list(review.rows)
    rows[matches[0]] = replace(rows[matches[0]], excluded=excluded)
    return replace(review, rows=_duplicates(rows))


def exclude_unmatched_call(review: ServiceCallReview, row_number: int, *,
                           expected_revision):
    """Explicit report-only exclusion of an unlinked/partial CMMS source row."""
    if review.revision != expected_revision:
        raise ValueError("Maintenance review changed; inspect the current rows.")
    matches = [n for n, row in enumerate(review.unmatched)
               if row.number == row_number and not row.excluded]
    if len(matches) != 1:
        raise ValueError("The unmatched source row is missing or already excluded.")
    unresolved = list(review.unmatched)
    unresolved[matches[0]] = replace(unresolved[matches[0]], excluded=True)
    return replace(review, unmatched=tuple(unresolved))


def confirm_financial_exclusion(review: ServiceCallReview, *, expected_revision):
    """A reviewed omission of price columns, not approval to output prices."""
    if review.revision != expected_revision:
        raise ValueError("Maintenance review changed; inspect the current source.")
    return replace(review, financial_exclusion_confirmed=True)


def confirm_word_layout(review: ServiceCallReview, *, expected_revision):
    if review.revision != expected_revision:
        raise ValueError("Maintenance review changed; inspect the current Word layout.")
    return replace(review, native_layout_confirmed=True)


def reimport_service_calls(previous: ServiceCallReview, incoming: ServiceCallReview):
    """Only the identical source/table/header/scope can preserve corrected rows."""
    stable = ("source_sha256", "source_fingerprint", "source_id", "table_number",
              "period_key", "facilities", "original_columns", "original_rows", "mapping")
    if any(getattr(previous, field) != getattr(incoming, field) for field in stable):
        raise ValueError("The maintenance source or mapping changed. Compare its rows before replacing edits.")
    return previous


def reviewed_service_call_block(review: ServiceCallReview, *, existing=None):
    """Produce a report-scoped result only after explicit mapping/review.

    Never merge automatically into a manually edited or intentionally omitted
    Service Calls block, and never append a duplicate on the same import.
    """
    if not review.ready_for_inclusion:
        raise ValueError("Review unresolved onsite calls, source layout and excluded financial columns first.")
    selected = [row for row in review.rows if not row.excluded]
    sites = {key: title for key, title, _ in review.facilities}
    values = []
    for row in selected:
        area = row.area
        if len(sites) > 1:
            area = sites[row.site] + " — " + row.area
        values.append((row.wo, row.finished, area, row.task, row.tag))
    from app.monthly_report_content_policy import table_has_pricing
    if table_has_pricing(OUTPUT_COLUMNS, tuple(values), work_orders=True):
        raise ValueError("Reviewed service calls contain pricing; remove it before report inclusion.")
    result = ResolvedBlock(
        "service_calls", "This month", rows=tuple(values),
        references=(review.source_reference,))
    if existing is not None:
        if existing.key != "service_calls":
            raise ValueError("Wrong report destination for service-call rows.")
        if existing == result:
            return existing
        if (existing.source == "Omit" or existing.rows or existing.extra_tables
                or existing.text.strip() or existing.asset_hashes):
            raise ValueError("Service Calls already has edited content. Review a replacement instead of overwriting it.")
    return result


def service_call_review_record(review):
    return {"schema": 1, "review": asdict(review), "sha256": review.revision}


def restore_service_call_review(value):
    """Pure round-trip for future durable UI; original source bytes stay separate."""
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("Invalid CMMS review schema.")
    try:
        data = value["review"]
        mapping = CallMapping(**{**{name: data["mapping"][name] for name in FIELDS},
                                 "ambiguous": tuple(data["mapping"]["ambiguous"])})
        rows = []
        for candidate in data["rows"]:
            original = candidate["origin"]
            origin = SourceRow(
                original["source_id"], original["source_sha256"],
                original["source_fingerprint"], original["filename"],
                original["table_number"], original["row_number"],
                tuple(original["columns"]), tuple(original["cells"]))
            rows.append(ServiceCallRow(origin, **{
                name: candidate[name] for name in FIELDS
            }, issues=tuple(candidate["issues"]),
                corrections=tuple(tuple(v) for v in candidate["corrections"]),
                excluded=candidate["excluded"]))
        review = ServiceCallReview(
            data["source_id"], data["source_sha256"], data["source_fingerprint"],
            data["filename"], data["table_number"], data["source_reference"],
            data["period_key"], tuple(
                (key, title, tuple(aliases)) for key, title, aliases in data["facilities"]),
            tuple(data["original_columns"]),
            tuple(tuple(row) for row in data["original_rows"]), mapping, tuple(rows),
            tuple(UnmatchedRow(item["number"], tuple(item["cells"]), item["reason"],
                               item.get("excluded", False))
                  for item in data["unmatched"]), tuple(data["notes"]),
            tuple(data["financial_columns"]), data["financial_exclusion_confirmed"],
            data["native_layout_confirmed"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Incomplete or damaged CMMS review record.") from exc
    if review.revision != value.get("sha256"):
        raise ValueError("The CMMS review failed its integrity check.")
    if (len(review.original_rows) > MAX_ROWS
            or len(review.original_rows) * len(review.original_columns) > MAX_CELLS
            or len(review.rows) > len(review.original_rows)):
        raise ValueError("The CMMS review exceeds safe row/cell bounds.")
    if (len({row.key for row in review.rows}) != len(review.rows)
            or any(row.origin.source_sha256 != review.source_sha256
                   or row.origin.source_fingerprint != review.source_fingerprint
                   or row.origin.source_id != review.source_id
                   or row.origin.table_number != review.table_number
                   or row.origin.columns != review.original_columns
                   or row.origin.row_number < 1
                   or row.origin.cells not in review.original_rows
                   for row in review.rows)):
        raise ValueError("The CMMS review lost source-row provenance.")
    return review
