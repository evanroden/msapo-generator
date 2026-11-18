"""Typed, source-bound comparisons for reviewed Monthly work-order assertions.

A match is a *candidate* for reconciliation, not authority to mark a task done.
Only the report's explicitly reviewed work-order rows enter this adapter. Raw
source cells and their immutable source identity remain available for audit.
Neither this module nor its caller writes contract standing data.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json


def _normal(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class WorkOrderClaim:
    source_id: str
    source_sha256: str
    source_fingerprint: str
    source_reference: str
    filename: str
    row_key: str
    row_number: int
    site: str
    work_order: str
    work_date: str
    completed_date: str
    status: str
    work_type: str
    trade: str
    original_cells: tuple[str, ...]

    @property
    def event(self) -> tuple[str, str]:
        return (_normal(self.site), _normal(self.work_order))

    @property
    def statement(self) -> tuple[str, ...]:
        return tuple(_normal(value) for value in (
            self.work_date, self.completed_date, self.status, self.work_type, self.trade))

    @property
    def locator(self) -> str:
        return f"{self.filename} row {self.row_number}"


@dataclass(frozen=True)
class CrossSourceCandidate:
    """One exact pair. Identical claims are safe duplicates, not two completed WOs."""
    existing: WorkOrderClaim
    incoming: WorkOrderClaim
    kind: str  # "duplicate" or "conflict"
    binding: str


def claim(review, row) -> WorkOrderClaim:
    """Do not normalize away raw status, dates, source cells or provenance."""
    return WorkOrderClaim(
        source_id=review.source_id, source_sha256=review.source_sha256,
        source_fingerprint=review.source_fingerprint,
        source_reference=review.source_reference,
        filename=row.origin.filename, row_key=row.key,
        row_number=row.origin.row_number, site=row.site,
        work_order=row.work_order, work_date=row.work_date,
        completed_date=row.completed_date, status=row.status,
        work_type=row.work_type, trade=row.trade,
        original_cells=row.origin.cells,
    )


def compare(existing: WorkOrderClaim, incoming: WorkOrderClaim, *,
            report_scope: str) -> CrossSourceCandidate | None:
    """A site + explicit WO is an identity; differing dates/status are never guessed.

    The period and contract are bound by the caller's immutable report scope.
    Both assertion revisions and original cells bind every human decision.
    """
    if (not report_scope or existing.source_id == incoming.source_id
            or not existing.work_order.strip() or not incoming.work_order.strip()
            or not existing.site.strip() or not incoming.site.strip()
            or existing.event != incoming.event):
        return None
    kind = "duplicate" if existing.statement == incoming.statement else "conflict"
    def evidence(value):
        return (value.source_id, value.source_sha256, value.source_fingerprint,
                value.source_reference, value.row_key, value.row_number,
                value.site, value.work_order, value.work_date,
                value.completed_date, value.status, value.work_type, value.trade,
                value.original_cells)
    binding = sha256(json.dumps(
        (report_scope, evidence(existing), evidence(incoming)),
        ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return CrossSourceCandidate(existing, incoming, kind, binding)
