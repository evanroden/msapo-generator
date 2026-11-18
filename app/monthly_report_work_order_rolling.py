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


def _recorded_status(review, row):
    """Use the reviewed source spelling when available, not a collapsed label."""
    origin = getattr(row, "origin", None)
    position = getattr(review.mapping, "status", None)
    if origin is None or type(position) is not int or not 0 <= position < len(origin.cells):
        return None
    corrections = dict(getattr(row, "corrections", ()))
    return corrections.get("status", origin.cells[position])


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
    closed_statuses: Iterable[str] = ("Closed", "Complete"),
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
    # Callers can supply a one-shot iterator. Preserve it for row counting
    # while checking that coverage actually references an included review.
    reviews = tuple(reviews)
    reviewed_sources = {review.source_reference for review in reviews}
    months = rolling_months(period)
    pm = {_review_category(value) for value in pm_categories if _key(value)}
    closed_statuses = tuple(closed_statuses)
    closed = {_review_closed_status(value) for value in closed_statuses if _key(value)}
    recorded_closed = {_key(value) for value in closed_statuses if _key(value)}
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
                or item.source_reference not in approved_revisions
                or item.source_reference not in reviewed_sources):
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
            # The normalizer reviews Activity for one month and labels valid
            # earlier received dates as outside that period. Those dates are
            # expected in a twelve-month grid; preserve every other issue and
            # require unambiguous ISO dates before treating a row as evidence.
            blocking_issues = tuple(issue for issue in row.issues
                                    if issue != "source date is outside this report period")
            if (blocking_issues or row.site not in sites or not row.work_order.strip()
                    or _month(row.work_date) is None
                    or (row.completed_date and _month(row.completed_date) is None)):
                notices.append(f"{ref}#{row.key}: unresolved row excluded")
                continue
            identities[(row.site, row.work_date, _key(row.work_order))].append((review, row))
    totals: dict[tuple[str, str, str], int] = defaultdict(int)
    members: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for (site, work_date, identity), records in sorted(identities.items()):
        facts = {(row.work_date, row.completed_date,
                  _key(_recorded_status(review, row) if _recorded_status(review, row) is not None else row.status),
                  _key(row.work_type), review.mapping.completed_date is not None)
                 for review, row in records}
        if len(facts) != 1:
            notices.append(f"{site}/{work_date}/{identity}: conflicting updates require review")
            continue
        review, row = records[0]
        kind = _key(row.work_type)
        if not pm and _review_category(kind) == "pm":
            # A known PM row must not block independent non-PM grids when
            # PM values were not selected; the PM cells remain unknown.
            continue
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
        raw_status = _recorded_status(review, row)
        selected_closed = (_key(raw_status) in recorded_closed if raw_status is not None
                           else _review_closed_status(row.status) in closed)
        completed = (_month(row.completed_date) if has_closed_date
                     else received if selected_closed else None)
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
    """Bind each physical frame to explicit site(s) and one reviewed metric.

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
    frame_bindings = []
    pairs = []
    for frame in frames:
        binding = bindings[frame.reference]
        if not isinstance(binding, (tuple, list)) or len(binding) != 2:
            raise ValueError("Native frames must cover each site/metric exactly once.")
        selected, metric = binding
        if isinstance(selected, str):
            selected = (selected,)
        elif isinstance(selected, (tuple, list)):
            selected = tuple(selected)
        else:
            raise ValueError("Native frames must cover each site/metric exactly once.")
        if not selected or any(not isinstance(site, str) for site in selected) or not isinstance(metric, str):
            raise ValueError("Native frames must cover each site/metric exactly once.")
        frame_bindings.append((selected, metric))
        pairs.extend((site, metric) for site in selected)
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
    for frame, (selected, metric) in zip(frames, frame_bindings):
        if frame.slot != "work_orders" or len(frame.columns) != 13:
            raise ValueError("Expected a recognized 13-column native work-order grid.")
        if _key(frame.columns[0]).replace("non pm ", "non-pm ") != headings[metric]:
            raise ValueError("The native heading disagrees with the reviewed PM/status mapping.")
        rows = tuple((sites[site].title, *(counts.cell(site, metric, month).value or ""
                     for month in counts.months)) for site in selected)
        tables.append(ReportTable((frame.columns[0], *rolling_labels(period)),
                                  rows, frame.reference))
    return tuple(tables)


def bind_six_month_bands(counts: RollingCounts, period, frames, facilities):
    """Bind verified site/category frames with separate received/closed bands."""
    from app.monthly_report_model import BandedWorkOrderTable, ReportTable

    sites = tuple(facilities)
    frames = tuple(frames)
    if (counts.review_notices or tuple(site.key for site in sites) != counts.sites):
        raise ValueError("Resolve source issues and confirm the work-order site order first.")
    if not 1 <= len(sites) <= 2:
        raise ValueError("Work-order locations need an approved overflow layout.")
    pairs = [(frame.band_site_index, frame.band_category) for frame in frames]
    expected = {(index, category) for index in (0, 1) for category in ("pm", "non_pm")}
    if (len(frames) != 4 or len(set(pairs)) != 4 or set(pairs) != expected
            or any(frame.slot != "work_orders" or len(frame.columns) != 7
                   for frame in frames)):
        raise ValueError("The master grid location and PM category mapping is missing or ambiguous.")
    labels = rolling_labels(period)
    tables = []
    for frame in frames:
        if frame.band_site_index >= len(sites):
            # Keep an unused location blank; never bind it to another site.
            tables.append(ReportTable(frame.columns, (), frame.reference))
            continue
        site = sites[frame.band_site_index].key
        def values(metric):
            return tuple(counts.cell(site, metric, month).value or "" for month in counts.months)
        received = values(frame.band_category + "_received")
        closed = values(frame.band_category + "_closed")
        rows = (("", *received[:6]), ("", *labels[6:]), ("", *received[6:]),
                ("Closed", *labels[:6]), ("", *closed[:6]),
                ("", *labels[6:]), ("", *closed[6:]))
        tables.append(BandedWorkOrderTable(("WO Received", *labels[:6]), rows,
                                           frame.reference, site, frame.band_category))
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


def explicit_band_period(table):
    """Recover a banded grid's period only from all four matching headers."""
    from app.monthly_report_model import BandedWorkOrderTable

    if (not isinstance(table, BandedWorkOrderTable) or len(table.columns) != 7
            or len(table.rows) != 7 or any(len(row) != 7 for row in table.rows)
            or _key(table.columns[0]) != "wo received"
            or _key(table.rows[3][0]) != "closed"
            or any(table.rows[index][0] for index in (0, 1, 2, 4, 5, 6))):
        return None
    first, last = table.columns[1:], table.rows[1][1:]
    if table.rows[3][1:] != first or table.rows[5][1:] != last:
        return None
    return explicit_grid_period(("PM Received", *first, *last))


def carry_six_month_band(previous, current, period, *, site_key, category):
    """Carry proven year/month cells without changing the previous report."""
    from app.monthly_report_model import BandedWorkOrderTable

    prior_period = explicit_band_period(previous)
    if (prior_period is None or previous.reference != current.reference or current.rows
            or (previous.band_site_key, previous.band_category) != (site_key, category)):
        raise ValueError("Historical work-order band identity or headings require review.")
    distance = (period.year - prior_period.year) * 12 + period.month - prior_period.month
    if not 1 <= distance <= 12:
        raise ValueError("Work-order rollover needs a later month within one reporting year.")
    old_months = rolling_months(prior_period)
    old_received = dict(zip(old_months, (*previous.rows[0][1:], *previous.rows[2][1:])))
    old_closed = dict(zip(old_months, (*previous.rows[4][1:], *previous.rows[6][1:])))
    months, labels = rolling_months(period), rolling_labels(period)
    received = tuple(old_received.get(month, "") for month in months)
    closed = tuple(old_closed.get(month, "") for month in months)
    rows = (("", *received[:6]), ("", *labels[6:]), ("", *received[6:]),
            ("Closed", *labels[:6]), ("", *closed[:6]), ("", *labels[6:]),
            ("", *closed[6:]))
    return BandedWorkOrderTable(("WO Received", *labels[:6]), rows,
                                current.reference, site_key, category)


def merge_carried_grid(previous, current, prior_period, period, *,
                       site_title: str | None = None, site_titles=None, site_aliases=()):
    """Merge two explicitly identified native frames by real year-month.

    Never alter the previous saved ReportTable. Conflicting manually entered
    or source-updated values require review, not last-writer-wins. The old
    reference must be exactly the same pinned physical master region.
    """
    if site_titles is None:
        titles = (site_title,) if isinstance(site_title, str) else ()
    elif site_title is None and isinstance(site_titles, (tuple, list)):
        titles = tuple(site_titles)
    else:
        titles = ()
    if (not titles or len(titles) > 2 or any(not isinstance(t, str) or not _key(t) for t in titles)
            or len({_key(t) for t in titles}) != len(titles)):
        raise ValueError("Work-order site identities are missing or ambiguous.")
    if not site_aliases:
        aliases = ((),) * len(titles)
    elif isinstance(site_aliases, (tuple, list)) and len(site_aliases) == len(titles):
        aliases = tuple(site_aliases)
    else:
        raise ValueError("Work-order site identities are missing or ambiguous.")
    if any(not isinstance(group, (tuple, list)) or any(not isinstance(v, str) for v in group)
           for group in aliases):
        raise ValueError("Work-order site identities are missing or ambiguous.")
    names = tuple({_key(value) for value in (title, *group) if _key(value)}
                  for title, group in zip(titles, aliases))
    if any(names[i] & names[j] for i in range(len(names)) for j in range(i)):
        raise ValueError("Work-order site identities are missing or ambiguous.")
    if (previous.reference != current.reference or not previous.reference
            or len(previous.columns) != 13 or len(current.columns) != 13
            or len(previous.rows) != len(titles)
            or len(current.rows) not in (0, len(titles))):
        raise ValueError("Review changed master regions or ambiguous work-order rows.")
    distance = ((period.year - prior_period.year) * 12
                + period.month - prior_period.month)
    if not 1 <= distance <= 12:
        raise ValueError("Work-order rollover needs a later month within one reporting year.")
    if (not _key(previous.columns[0])
            or _key(previous.columns[0]) != _key(current.columns[0])):
        raise ValueError("The work-order metric changed; review before carrying values.")
    if (previous.columns[1:] != rolling_labels(prior_period)
            or current.columns[1:] not in (rolling_labels(period), previous.columns[1:])):
        raise ValueError("Unverified month headings cannot be carried as known history.")
    if any(len(row) != 13 for row in previous.rows):
        raise ValueError("A historical month row has incomplete columns.")
    if any(_key(row[0]) not in allowed for row, allowed in zip(previous.rows, names)):
        raise ValueError("The previous work-order grid belongs to a different site.")
    if current.rows and any(len(row) != 13 or _key(row[0]) not in allowed
                            for row, allowed in zip(current.rows, names)):
        raise ValueError("Current month edits have ambiguous site identity.")
    if current.rows and current.columns[1:] != rolling_labels(period):
        raise ValueError("Edited current values require current year-month headings.")
    rows = []
    for index, (title, prior_row) in enumerate(zip(titles, previous.rows)):
        old_values = dict(zip(rolling_months(prior_period), prior_row[1:]))
        new_values = (dict(zip(rolling_months(period), current.rows[index][1:]))
                      if current.rows else {})
        merged = []
        for month in rolling_months(period):
            before, after = old_values.get(month, ""), new_values.get(month, "")
            if before and after and before != after:
                raise ValueError(f"{title} {month}: conflicting values require source review.")
            merged.append(after or before)
        rows.append((title, *merged))
    return replace(current, columns=(current.columns[0], *rolling_labels(period)),
                   rows=tuple(rows))
