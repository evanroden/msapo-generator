"""Auditable row-derived metrics from one explicitly reviewed work-order table.

The reporting cohort uses work_date, not completed_date. Completed/Open are the
reviewed source's recorded statuses, not claims about when completion happened
or a month-end backlog. This module neither publishes nor changes a report.
Manual and annual aggregate totals are deliberately outside this contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import re

from app.monthly_report_model import ReportPeriod, ReportTable
from app.monthly_report_work_order_normalized import (
    WorkOrderReview, WorkOrderRow, restore_review, review_record,
)


@dataclass(frozen=True)
class CountGroup:
    """Each subtotal exposes the exact source rows that justify it."""
    key: str
    label: str
    row_keys: tuple[str, ...]
    completed: int
    open: int

    @property
    def total(self) -> int:
        return len(self.row_keys)


@dataclass(frozen=True)
class RowDisposition:
    row_key: str
    disposition: str  # counted, excluded, outside_scope, needs_review
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkOrderCounts:
    review_revision: str
    source_reference: str
    period_key: str
    selected_sites: tuple[str, ...]
    include_trades: bool
    overall: CountGroup
    work_types: tuple[CountGroup, ...]
    sites: tuple[CountGroup, ...]
    trades: tuple[CountGroup, ...]
    dispositions: tuple[RowDisposition, ...]
    notices: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        # Includes corrected values through review_revision and every option;
        # a later UI must not reuse a result after any of these change.
        return sha256(json.dumps((self.review_revision, self.period_key,
            self.selected_sites, self.include_trades),
            separators=(",", ":")).encode()).hexdigest()

    def summary_table(self) -> ReportTable:
        """Optional candidate table; caller still owns review/output placement."""
        groups = (self.overall, *self.work_types)
        return ReportTable(
            ("Uploaded row sample", "Total", "Recorded completed", "Recorded open"),
            tuple((g.label, str(g.total), str(g.completed), str(g.open)) for g in groups),
            self.source_reference,
        )


def _group(key: str, label: str, rows: tuple[WorkOrderRow, ...]) -> CountGroup:
    return CountGroup(key, label, tuple(row.key for row in rows),
                      sum(row.status == "Completed" for row in rows),
                      sum(row.status == "Open" for row in rows))


def _trade(row: WorkOrderRow) -> tuple[str, str]:
    value = row.trade.strip()
    if not value:
        return "unknown", "Unclassified trade"
    # Do not split one work order into several subtotals or guess its primary
    # trade. Keep the exact supplied string in the source/review row.
    if re.search(r"[/&,;+\n]|\band\b", value, flags=re.IGNORECASE):
        return "multiple", "Multiple or unresolved trades"
    return "named:" + value, value


def count_reviewed_work_orders(review: WorkOrderReview, *, approved_revision: str,
                              period: ReportPeriod, selected_sites: tuple[str, ...],
                              include_trades: bool = False) -> WorkOrderCounts:
    """Count eligible rows only from the exact review the caller approved.

    Missing category is counted in Unclassified; supplied invalid categories,
    unresolved dates/statuses and duplicate site/WO identities stay in review.
    Excluding one duplicate does not silently approve its sibling: the shared
    normalized contract's remaining duplicate warning must also be resolved.
    This is one source table, never a union of overlapping CMMS exports.
    """
    if approved_revision != review.revision:
        raise ValueError("The approved work-order review changed. Review the current rows.")
    restore_review(review_record(review))  # Verify original row identities.
    if review.kind != "records":
        raise ValueError("Aggregate or unresolved tables are not row-derived work-order counts.")
    if period.key != review.period_key:
        raise ValueError("Review work orders for the selected report period first.")
    allowed = {key for key, _ in review.allowed_sites}
    if (not isinstance(selected_sites, tuple)
            or any(not isinstance(site, str) or site not in allowed for site in selected_sites)
            or len(selected_sites) != len(set(selected_sites))):
        raise ValueError("Select unique sites from this reviewed source scope.")
    if type(include_trades) is not bool:
        raise ValueError("Choose whether to include trade subtotals.")

    # Site order has no bearing on evidence/cache identity.
    selected_sites = tuple(sorted(selected_sites))
    dispositions, accepted = [], []
    identity_counts: dict[tuple[str, str], int] = {}
    for row in review.rows:
        if row.work_order:
            identity = (row.site, row.work_order.casefold())
            identity_counts[identity] = identity_counts.get(identity, 0) + 1
    for row in review.rows:
        reasons = list(dict.fromkeys((*review.questions, *row.issues)))
        if not row.work_order.strip() or row.status not in ("Open", "Completed"):
            reasons.append("Work-order identity or recorded status needs review")
        if row.work_type not in ("", "PM", "Non-PM"):
            reasons.append("Work type needs review")
        try:
            in_period = date.fromisoformat(row.work_date).strftime("%Y-%m") == period.key
        except ValueError:
            in_period = False
        if not in_period:
            reasons.append("Work date is unresolved or outside the selected reporting month")
        if row.site not in allowed:
            reasons.append("Site needs review")
        if identity_counts.get((row.site, row.work_order.casefold()), 0) > 1:
            reasons.append("Duplicate site/work-order identity needs review")
        if row.excluded:
            disposition = "excluded"
        elif reasons:
            disposition = "needs_review"
        elif row.site not in selected_sites:
            disposition = "outside_scope"
        else:
            disposition = "counted"
            accepted.append(row)
        dispositions.append(RowDisposition(row.key, disposition, tuple(dict.fromkeys(reasons))))

    rows = tuple(accepted)
    overall = _group("all", "All reviewed rows in scope", rows)
    categories = tuple(_group(key or "unknown", key or "Unclassified work type",
        tuple(row for row in rows if row.work_type == key)) for key in ("PM", "Non-PM", ""))
    sites = tuple(_group(key, key, tuple(row for row in rows if row.site == key))
                  for key in selected_sites)
    trade_groups = ()
    if include_trades:
        labels, members = {}, {}
        for row in rows:
            key, label = _trade(row)
            labels[key] = label
            members.setdefault(key, []).append(row)
        trade_groups = tuple(_group(key, labels[key], tuple(members[key]))
                             for key in sorted(labels))
    notices = [
        "Row-derived counts cover only this reviewed uploaded table; complete CMMS coverage is not established.",
        "The cohort uses work dates in the reporting month. Recorded statuses are not completion-event or month-end backlog counts.",
        "Manual and supplied aggregate totals are separate and have not been added to these counts.",
    ]
    unresolved = sum(item.disposition == "needs_review" for item in dispositions)
    if unresolved:
        notices.append(f"{unresolved} source rows need review and are not included in counts.")
    if any(row.work_type == "" for row in rows):
        notices.append("Unclassified work types contribute to the total but are neither PM nor Non-PM.")
    if include_trades and any(_trade(row)[0] == "multiple" for row in rows):
        notices.append("Rows with multiple or unresolved trades are counted once in their own subtotal; review the original trade values.")
    if not selected_sites:
        notices.append("No sites selected; no rows included.")
    return WorkOrderCounts(review.revision, review.source_reference, period.key,
        selected_sites, include_trades, overall, categories, sites, trade_groups,
        tuple(dispositions), tuple(notices))
