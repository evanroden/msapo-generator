"""Explicit column mapping; incomplete CMMS history never becomes invented zeros."""

from dataclasses import dataclass
from datetime import date, datetime

from app.monthly_report_model import BlockSpec, ColumnSpec, ReportPeriod, ReportProfile, ResolvedBlock
from app.monthly_report_sources import SourceTable


@dataclass(frozen=True)
class CMMSMapping:
    finished: str
    work_order: str
    facility: str = ""
    assigned_facility: str = ""  # Explicit operator choice if the export lacks a site column.
    description: str = ""
    area: str = ""
    tag: str = ""
    category: str = ""
    status: str = ""
    completed_statuses: tuple[str, ...] = ()
    pm_values: tuple[str, ...] = ()
    cm_values: tuple[str, ...] = ()
    date_format: str = "ISO"
    complete_months: tuple[str, ...] = ()
    complete_facilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class CMMSResult:
    blocks: tuple[ResolvedBlock, ...]
    specs: tuple[BlockSpec, ...]
    notices: tuple[str, ...]


def month_window(period: ReportPeriod) -> tuple[str, ...]:
    end = period.year * 12 + period.month - 1
    return tuple(f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(end - 11, end + 1))


def parse_date(value: str, format: str) -> date | None:
    if format not in ("ISO", "MM/DD/YYYY", "DD/MM/YYYY"):
        raise ValueError("Choose an explicit CMMS date format.")
    # Excel dates become ISO during read; this unambiguous form is always valid.
    formats = ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]
    if format == "MM/DD/YYYY":
        formats += ["%m/%d/%Y", "%m/%d/%y"]
    elif format == "DD/MM/YYYY":
        formats += ["%d/%m/%Y", "%d/%m/%y"]
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None


def map_cmms(table: SourceTable, mapping: CMMSMapping, profile: ReportProfile,
             period: ReportPeriod, reference: str) -> CMMSResult:
    columns = {name: i for i, name in enumerate(table.columns)}
    selected = (mapping.finished, mapping.work_order, mapping.facility, mapping.description,
                mapping.area, mapping.tag, mapping.category, mapping.status)
    if not mapping.finished or not mapping.work_order or any(c not in columns for c in selected if c):
        raise ValueError("Map the finish date and work-order identity to actual columns.")
    if mapping.status and not mapping.completed_statuses:
        raise ValueError("Select which status values mean completed work.")
    if not mapping.facility and mapping.assigned_facility not in {f.key for f in profile.facilities}:
        raise ValueError("Map a facility column or explicitly assign this export to a profile facility.")
    windows = month_window(period)
    if set(mapping.complete_months) - set(windows):
        raise ValueError("Coverage confirmation must be within the twelve-month reporting window.")
    folded = lambda values: {v.strip().casefold() for v in values}
    pm, cm = folded(mapping.pm_values), folded(mapping.cm_values)
    if pm & cm:
        raise ValueError("PM and CM categories must be distinct.")
    aliases = {n.strip().casefold(): f.key for f in profile.facilities for n in (f.key, f.title, *f.aliases)}
    facilities = {f.key: f.title for f in profile.facilities}
    if set(mapping.complete_facilities) - set(facilities):
        raise ValueError("Coverage must name confirmed profile facilities.")
    records, conflicts, notices = {}, set(), []
    invalid = unknown = duplicates = 0
    for row in table.rows:
        def cell(column):
            return row[columns[column]].strip() if column and columns[column] < len(row) else ""
        if mapping.status and cell(mapping.status).casefold() not in folded(mapping.completed_statuses):
            continue
        finished, identity = parse_date(cell(mapping.finished), mapping.date_format), cell(mapping.work_order)
        if not finished or not identity:
            invalid += 1
            continue
        facility = aliases.get(cell(mapping.facility).casefold()) if mapping.facility else mapping.assigned_facility
        if not facility:
            unknown += 1
            continue
        category = cell(mapping.category).casefold()
        kind = "PM" if category in pm else "CM" if category in cm else ""
        value = (finished, kind, cell(mapping.description), cell(mapping.area), cell(mapping.tag))
        key = (facility, identity)
        if key in records:
            if records[key] == value:
                duplicates += 1
            else:
                conflicts.add(key)
        else:
            records[key] = value
    for key in conflicts:
        records.pop(key, None)
    if invalid:
        notices.append(f"{invalid} rows have a missing/invalid finish date or WO identity; excluded from mapped tables.")
    if unknown:
        notices.append(f"{unknown} rows name facilities outside this profile; review the source and membership mapping.")
    if duplicates:
        notices.append(f"{duplicates} identical WO rows were counted once.")
    if conflicts:
        notices.append(f"{len(conflicts)} WO identities have conflicting rows; excluded until the export is corrected.")
    service_rows = []
    for (facility, identity), (finished, _, description, area, tag) in sorted(records.items(), key=lambda pair: (pair[1][0], pair[0])):
        if period.start <= finished <= period.end:
            service_rows.append((facilities[facility], identity, finished.isoformat(), area, description, tag))
    outside = sum(not period.start <= v[0] <= period.end for v in records.values())
    if outside:
        notices.append(f"{outside} completed rows are outside {period.label}; retained as evidence/history, excluded from monthly service calls.")
    grid = []
    for month in windows:
        for facility, title in facilities.items():
            values = [v for (f, _), v in records.items() if f == facility and v[0].isoformat().startswith(month)]
            # Invalid or conflicting rows invalidate aggregate completeness. The
            # operator can correct the source instead of accepting false totals.
            complete = month in mapping.complete_months and facility in mapping.complete_facilities and not (invalid or unknown or conflicts)
            categories_known = bool(mapping.category) and all(v[1] for v in values)
            counts = tuple(str(sum(v[1] == kind for v in values)) if complete and categories_known else "" for kind in ("PM", "CM"))
            grid.append((month, title, *counts, str(len(values)) if complete else ""))
    if set(windows) - set(mapping.complete_months) or invalid or unknown or conflicts:
        notices.append("Unconfirmed or incomplete historical counts remain blank. Confirm complete export coverage only for months and all profile facilities actually covered.")
    specs = (
        BlockSpec("service_calls", "table", columns=(ColumnSpec("facility", "Facility"), ColumnSpec("wo", "WO #"),
            ColumnSpec("finished", "Finish Date", "date"), ColumnSpec("area", "Area"), ColumnSpec("task", "Task Code-Description"), ColumnSpec("tag", "Tag #"))),
        BlockSpec("work_orders", "work_order_grid", columns=(ColumnSpec("month", "Month"), ColumnSpec("facility", "Facility"),
            ColumnSpec("pm", "PM completed", "number"), ColumnSpec("cm", "CM completed", "number"), ColumnSpec("total", "Total completed", "number"))),
    )
    return CMMSResult((ResolvedBlock("service_calls", "This month", rows=tuple(service_rows), references=(reference,)),
                       ResolvedBlock("work_orders", "This month", rows=tuple(grid), references=(reference,))), specs, tuple(notices))
