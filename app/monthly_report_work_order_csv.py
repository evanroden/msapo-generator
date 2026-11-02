"""Deterministic, provenance-linked metrics from explicit work-order CSV/XLSX rows.

Never infer complete monthly CMMS coverage or site allocation from a bare
filename. Only unambiguous status, identity and dated source rows contribute.
"""
from dataclasses import dataclass
from datetime import date, datetime
import re

from app.monthly_report_sources import SourceContent, source_reference
from app.monthly_report_model import ReportPeriod, ReportProfile


@dataclass(frozen=True)
class WorkOrderEvidence:
    source_id: str
    filename: str
    reference: str
    text: str
    total: int
    completed: int
    open: int
    rows: tuple[tuple[str, str, str], ...]
    needs_site_confirmation: bool
    notices: tuple[str, ...] = ()


_HEADERS = {
    "identity": {"workorder", "workordernumber", "workorderid", "wonumber", "wo", "woid", "id"},
    "status": {"status", "workorderstatus", "state", "currentstatus"},
    "date": {"date", "workdate", "reporteddate", "servicedate", "completiondate", "finishdate",
             "finisheddate", "eventdate"},
    "facility": {"facility", "site", "location", "building", "hospital"},
}
_COMPLETE = {"completed", "complete", "closed", "finished", "done"}
_OPEN = {"open", "pending", "inprogress", "notstarted", "unresolved", "awaitingparts"}


def _name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _column(columns, kind):
    positions = [i for i, title in enumerate(columns) if _name(title) in _HEADERS[kind]]
    return positions[0] if len(positions) == 1 else None


def _date(value):
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def is_work_order_source(content: SourceContent) -> bool:
    return (content.source.suffix in (".csv", ".xlsx")
            and any(all(_column(table.columns, kind) is not None
                        for kind in ("identity", "status", "date"))
                    for table in content.tables))


def work_order_evidence(content: SourceContent, period: ReportPeriod,
                        profile: ReportProfile) -> tuple[WorkOrderEvidence, ...]:
    if content.source.suffix not in (".csv", ".xlsx"):
        return ()
    output = []
    sites = {}
    for facility_profile in profile.facilities:
        for label in (facility_profile.key, facility_profile.title, *facility_profile.aliases):
            # CSV normalization removes punctuation, unlike profile validation.
            # Distinct valid aliases can therefore collide here. Do not choose
            # whichever selected facility happened to be visited last.
            normalized = _name(label)
            if normalized:
                sites.setdefault(normalized, set()).add(facility_profile.key)
    for number, table in enumerate(content.tables, 1):
        wo, status, dated = (_column(table.columns, kind)
                             for kind in ("identity", "status", "date"))
        if None in (wo, status, dated):
            continue
        facility = _column(table.columns, "facility")
        if len(table.rows) > 20000:
            continue  # existing upload limits should reject oversized tables
        observations, notices = {}, []
        conflicts = set()
        unrecognized = outside_sites = ambiguous_sites = undated = 0
        for row in table.rows:
            def cell(index):
                return str(row[index]).strip() if index is not None and index < len(row) else ""
            identity = cell(wo)
            state = _name(cell(status))
            when = _date(cell(dated))
            if not identity or state not in _COMPLETE | _OPEN:
                unrecognized += 1
                continue
            if when is None:
                undated += 1
                continue
            if (when.year, when.month) != (period.year, period.month):
                continue
            site_key = ""
            if facility is not None:
                matches = sites.get(_name(cell(facility)), set())
                if not matches:
                    outside_sites += 1
                    continue
                if len(matches) != 1:
                    ambiguous_sites += 1
                    continue
                site_key = next(iter(matches))
            # A CMMS may number orders independently at each site. Keep the
            # same-site duplicate/conflict rules without collapsing siblings
            # from another selected site. Missing site retains one unassigned
            # cohort and still requires explicit site confirmation below.
            scoped_identity = (site_key, identity)
            value = (identity, when.isoformat(), "Completed" if state in _COMPLETE else "Open")
            if scoped_identity in observations and observations[scoped_identity] != value:
                conflicts.add(scoped_identity)
            else:
                observations[scoped_identity] = value
        for identity in conflicts:
            observations.pop(identity, None)
        if unrecognized:
            notices.append(f"{unrecognized} rows had an unrecognized status or missing work-order ID.")
        if undated:
            notices.append(f"{undated} rows had an unrecognized or missing date.")
        if outside_sites:
            notices.append(f"{outside_sites} source rows did not match the selected sites and were excluded.")
        if ambiguous_sites:
            notices.append(f"{ambiguous_sites} source rows had an ambiguous site label and were excluded.")
        if conflicts:
            notices.append(f"{len(conflicts)} work-order identities conflicted and were excluded.")
        if not observations:
            continue
        rows = tuple(sorted(observations.values(), key=lambda v: (v[1], v[0])))
        completed = sum(row[2] == "Completed" for row in rows)
        opened = sum(row[2] == "Open" for row in rows)
        total = len(rows)
        pct = f"{completed / total * 100:.1f}"
        label = f"{period.label} work orders in the uploaded {content.source.filename}"
        text = (f"{label}: {total} total, {completed} completed, {opened} open; "
                f"{pct}% of these recorded work orders completed.")
        output.append(WorkOrderEvidence(content.source.id, content.source.filename,
            source_reference(content.source, number), text, total, completed, opened,
            rows, facility is None, tuple(notices)))
    return tuple(output)
