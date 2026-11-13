"""Auditable, twelve-month work-order grids from approved normalized source rows.

The uploaded sample is not automatically complete CMMS coverage. A blank is
unknown; the literal zero is emitted only for source-bound approved coverage.
No report is mutated here, and every counted value retains source row keys.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
import re
from typing import Iterable


METRICS = ("pm_received", "non_pm_received", "pm_closed", "non_pm_closed")


def rolling_months(period) -> tuple[str, ...]:
    last = period.year * 12 + period.month - 1
    return tuple(f"{index // 12:04d}-{index % 12 + 1:02d}"
                 for index in range(last - 11, last + 1))


def rolling_labels(period) -> tuple[str, ...]:
    return tuple(date(int(month[:4]), int(month[5:]), 1).strftime("%b %Y")
                 for month in rolling_months(period))


def _month(value: str) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).strftime("%Y-%m")
    except (TypeError, ValueError):
        return None


def _key(value) -> str:
    return " ".join(str(value).casefold().split())


def _review_category(value: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", str(value).casefold())
    if compact in {"pm", "preventive", "preventivemaintenance", "plannedmaintenance"}:
        return "pm"
    return _key(value)


def _review_closed_status(value: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", str(value).casefold())
    if compact in {"completed", "complete", "closed", "finished", "done"}:
        return "completed"
    return _key(value)


@dataclass(frozen=True)
class CoveredMonth:
    """A reviewed assertion that a particular source covers an entire cell."""
    site: str
    metric: str
    month: str
    source_reference: str


@dataclass(frozen=True)
class RollingCell:
    site: str
    metric: str
    month: str
    value: str | None
    covered: bool
    source_rows: tuple[str, ...] = ()


@dataclass(frozen=True)
class RollingCounts:
    months: tuple[str, ...]
    sites: tuple[str, ...]
    cells: tuple[RollingCell, ...]
    review_notices: tuple[str, ...]

    def cell(self, site: str, metric: str, month: str) -> RollingCell:
        matches = [cell for cell in self.cells
                   if (cell.site, cell.metric, cell.month) == (site, metric, month)]
        if len(matches) != 1:
            raise ValueError("A grid cell must have one site, metric and year-month.")
        return matches[0]


def tally_reviewed_months(
    reviews: Iterable,
    period,
    facilities: Iterable,
    *,
    approved_revisions: dict[str, str],
    pm_categories: Iterable[str] = (),
    closed_statuses: Iterable[str] = (),
    covered_months: Iterable[CoveredMonth] = (),
    coverage_approvals: dict[tuple[str, str, str], str] | None = None,
) -> RollingCounts:
    """Derive received/closed PM/non-PM counts with explicit source semantics.

    Received uses work_date. Closed uses completed_date if that source column
    exists, even when a particular value is blank. Only when that column is
    absent may a selected closed status use work_date as the closed event.
    """
    sites = tuple(f.key for f in facilities)
    if not sites or len(set(sites)) != len(sites):
        raise ValueError("Explicit unique facility keys are required.")
    months = rolling_months(period)
    pm = {_review_category(value) for value in pm_categories if _key(value)}
    closed = {_review_closed_status(value) for value in closed_statuses if _key(value)}
    coverage: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    coverage_approvals = coverage_approvals or {}
    for item in covered_months:
        key = item.site, item.metric, item.month
        if (item.site not in sites or item.metric not in METRICS
                or item.month not in months or not item.source_reference.strip()):
            raise ValueError("Coverage must name a known site, metric, month and source.")
        # A source with approved rows is not by itself proof of a complete
        # monthly export. Require a separate month/site/metric coverage approval
        # tied to the exact same reviewed source identity.
        if (coverage_approvals.get(key) != item.source_reference
                or item.source_reference not in approved_revisions):
            raise ValueError("Coverage needs an independently approved, current source receipt.")
        coverage[key].add(item.source_reference)
    identities = defaultdict(list)
    notices = []
    for review in reviews:
        ref = review.source_reference
        if (review.kind != "records" or review.questions or not ref
                or approved_revisions.get(ref) != review.revision):
            raise ValueError("Approve the exact normalized work-order review first.")
        if len(review.rows) > 20_000 or not review.period_key:
            raise ValueError("Invalid or oversized source review.")
        for row in review.rows:
            if row.excluded:
                continue
            if row.issues or row.site not in sites or not row.work_order.strip():
                notices.append(f"{ref}#{row.key}: unresolved row excluded")
                continue
            identities[(row.site, _key(row.work_order))].append((review, row))
    totals: dict[tuple[str, str, str], int] = defaultdict(int)
    members: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for (site, identity), records in sorted(identities.items()):
        facts = {(row.work_date, row.completed_date, _key(row.status),
                  _key(row.work_type), review.mapping.completed_date is not None)
                 for review, row in records}
        if len(facts) != 1:
            notices.append(f"{site}/{identity}: conflicting updates require review")
            continue
        review, row = records[0]
        kind = _key(row.work_type)
        if pm and _review_category(kind) in pm:
            category = "pm"
        elif kind in ("non-pm", "non pm", "nonpm"):
            category = "non_pm"
        else:
            notices.append(f"{site}/{identity}: unselected or unknown PM category")
            continue
        origins = {f"{rev.source_reference}#{r.key}" for rev, r in records}
        received = _month(row.work_date)
        if received in months:
            key = (site, f"{category}_received", received)
            totals[key] += 1
            members[key].update(origins)
        has_closed_date = review.mapping.completed_date is not None
        completed = (_month(row.completed_date) if has_closed_date
                     else received if _review_closed_status(row.status) in closed else None)
        if has_closed_date and row.completed_date and completed is None:
            notices.append(f"{site}/{identity}: invalid completion date requires review")
        if completed in months:
            key = (site, f"{category}_closed", completed)
            totals[key] += 1
            members[key].update(origins)
    cells = []
    for site in sites:
        for metric in METRICS:
            for month in months:
                key = (site, metric, month)
                # PM classification has not been approved: no PM count or zero.
                active = not metric.startswith("pm_") or bool(pm)
                # A partial export can contain rows without proving the month
                # complete. Keep those row receipts for review, but never
                # present their subtotal as the month's actual count.
                covered = bool(active and coverage[key])
                value = (str(totals[key]) if totals[key] else "0") if covered else None
                cells.append(RollingCell(site, metric, month, value,
                    covered, tuple(sorted(members[key]))))
    return RollingCounts(months, sites, tuple(cells), tuple(dict.fromkeys(notices)))


def bind_template_grids(counts: RollingCounts, period, frames, bindings, facilities):
    """Bind each physical frame to an explicitly resolved site and metric.

    More than two sites are retained in counts but require an approved
    overflow layout; this routine refuses a partial or duplicated output.
    """
    from app.monthly_report_model import ReportTable

    if counts.review_notices:
        raise ValueError("Resolve unclassified, conflicting or unsupported work-order rows before Word/PDF binding.")
    sites = {facility.key: facility for facility in facilities}
    if tuple(sites) != counts.sites:
        raise ValueError("Grid site order has changed; review the binding.")
    if len(sites) > 2:
        raise ValueError("Three or more locations need an overflow layout; no totals were dropped.")
    frames = tuple(frames)
    if len(frames) != len(bindings) or set(bindings) != {f.reference for f in frames}:
        raise ValueError("Each native frame needs one site/metric binding.")
    pairs = tuple(bindings[f.reference] for f in frames)
    expected = {(site, metric) for site in sites for metric in METRICS}
    if len(set(pairs)) != len(pairs) or set(pairs) != expected:
        raise ValueError("Native frames do not cover each site/metric exactly once.")
    headings = {
        "pm_received": "pm received",
        "pm_closed": "pm closed",
        "non_pm_received": "non-pm received",
        "non_pm_closed": "non-pm closed",
    }
    tables = []
    for frame in frames:
        if frame.slot != "work_orders" or len(frame.columns) != 13:
            raise ValueError("Expected a recognized 13-column native work-order grid.")
        site, metric = bindings[frame.reference]
        if _key(frame.columns[0]).replace("non pm ", "non-pm ") != headings[metric]:
            raise ValueError("The native heading disagrees with the reviewed PM/status mapping.")
        values = tuple(counts.cell(site, metric, month).value or "" for month in counts.months)
        tables.append(ReportTable((frame.columns[0], *rolling_labels(period)),
                    ((sites[site].title, *values),), frame.reference))
    return tuple(tables)


def explicit_grid_period(columns):
    """Recover a historical period ONLY from twelve explicit year/month labels."""
    if len(columns) != 13:
        return None
    import calendar
    from app.monthly_report_model import ReportPeriod

    last = columns[-1]
    try:
        tokens = last.strip().split()
        if len(tokens) != 2 or not tokens[1].isdigit() or len(tokens[1]) != 4:
            return None
        month = tuple(calendar.month_abbr).index(tokens[0].title())
        period = ReportPeriod(int(tokens[1]), month)
    except (ValueError, IndexError):
        return None
    return period if columns[1:] == rolling_labels(period) else None


def merge_carried_grid(previous, current, prior_period, period, *, site_title: str):
    """Merge two explicitly identified native frames by real year-month.

    Never alter the previous saved ReportTable. Conflicting manually entered
    or source-updated values require review, not last-writer-wins. The old
    reference must be exactly the same pinned physical master region.
    """
    if (previous.reference != current.reference or not previous.reference
            or len(previous.columns) != 13 or len(current.columns) != 13
            or len(previous.rows) != 1 or len(current.rows) > 1):
        raise ValueError("Review changed master regions or ambiguous work-order rows.")
    distance = ((period.year - prior_period.year) * 12
                + period.month - prior_period.month)
    if not 1 <= distance <= 12:
        raise ValueError("Work-order rollover needs a later month within one reporting year.")
    if (previous.columns[1:] != rolling_labels(prior_period)
            or current.columns[1:] not in (rolling_labels(period), previous.columns[1:])):
        raise ValueError("Unverified month headings cannot be carried as known history.")
    if _key(previous.rows[0][0]) != _key(site_title):
        raise ValueError("The previous work-order grid belongs to a different site.")
    if len(previous.rows[0]) != 13:
        raise ValueError("A historical month row has incomplete columns.")
    if current.rows and (len(current.rows[0]) != 13
                         or _key(current.rows[0][0]) != _key(site_title)):
        raise ValueError("Current month edits have ambiguous site identity.")
    if current.rows and current.columns[1:] != rolling_labels(period):
        raise ValueError("Edited current values require current year-month headings.")
    old_values = dict(zip(rolling_months(prior_period), previous.rows[0][1:]))
    new_values = dict(zip(rolling_months(period), current.rows[0][1:])) if current.rows else {}
    merged = []
    for month in rolling_months(period):
        before, after = old_values.get(month, ""), new_values.get(month, "")
        if before and after and before != after:
            raise ValueError(f"{site_title} {month}: conflicting values require source review.")
        merged.append(after or before)
    return replace(current, columns=(current.columns[0], *rolling_labels(period)),
                   rows=((site_title, *merged),))
