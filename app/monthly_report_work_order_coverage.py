"""Explicit source coverage for existing reviewed work-order records.

Earliest/latest source rows are never evidence that intermediate months were exported.\nUnverified export metadata cannot self-authorize coverage; only a deliberate\nAM confirmation is currently supported.
This module prepares source-bound review evidence, not annual report grids.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import re

_MONTH = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")


def _month(value: str) -> str:
    if not isinstance(value, str) or not _MONTH.fullmatch(value):
        raise ValueError("Coverage months must use YYYY-MM.")
    return value


def month_window(end_month: str, length: int = 12) -> tuple[str, ...]:
    """Previous calendar months, including the selected end month."""
    end = _month(end_month)
    if type(length) is not int or not 1 <= length <= 24:
        raise ValueError("Choose a one-to-24-month coverage window.")
    index = int(end[:4]) * 12 + int(end[5:]) - 1
    return tuple(f"{n // 12:04d}-{n % 12 + 1:02d}" for n in range(index - length + 1, index + 1))


@dataclass(frozen=True)
class CoverageDecision:
    """Explicit AM attestation for one source, contract and site."""
    contract: str
    profile_key: str
    site: str
    source_sha256: str
    source_fingerprint: str
    table_number: int
    start_month: str
    end_month: str
    basis: str
    evidence: str

    def __post_init__(self):
        a, b = _month(self.start_month), _month(self.end_month)
        if (a > b or not all(isinstance(v, str) and v.strip() for v in
                            (self.contract, self.profile_key, self.site,
                             self.source_sha256, self.source_fingerprint, self.evidence))
                or len(self.evidence) > 500
                or type(self.table_number) is not int or self.table_number < 1
                or self.basis != "am_confirmed"):
            raise ValueError("Coverage requires a specific source, site, period and evidence.")

    def to_record(self) -> dict:
        return {"schema": 1, **asdict(self)}


def restore_decision(value: dict) -> CoverageDecision:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("Unknown work-order coverage receipt.")
    try:
        return CoverageDecision(**{name: value[name] for name in
                                  CoverageDecision.__dataclass_fields__})
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid source-bound coverage receipt.") from exc


@dataclass(frozen=True)
class MonthCoverage:
    month: str
    covered: bool
    total: int | None
    completed: int | None
    open: int | None
    pm: int | None
    non_pm: int | None
    row_keys: tuple[str, ...]
    issues: tuple[str, ...]


def summarize_coverage(review, decisions: tuple[CoverageDecision, ...], *,
                       contract: str, profile_key: str, site: str,
                       months: tuple[str, ...], as_of: date) -> tuple[MonthCoverage, ...]:
    """Return blank for missing coverage or unresolved source rows.

    No source rows are mutated; row counts reflect reviewed uploaded records,
    not independent proof of complete CMMS activity.
    """
    if not isinstance(as_of, date) or type(months) is not tuple or len(months) > 24:
        raise ValueError("Choose a bounded coverage window and as-of date.")
    if len(set(months)) != len(months):
        raise ValueError("Coverage window repeats a month.")
    for month in months:
        _month(month)
    if site not in {key for key, _ in review.allowed_sites}:
        raise ValueError("The selected site is outside this review's profile.")
    active = []
    for decision in decisions:
        if not isinstance(decision, CoverageDecision):
            raise ValueError("Unverified coverage decision.")
        if (decision.contract != contract or decision.profile_key != profile_key
                or decision.site != site
                or decision.source_sha256 != review.source_sha256
                or decision.source_fingerprint != review.source_fingerprint
                or decision.table_number != review.table_number):
            raise ValueError("Coverage belongs to a different contract, site or source.")
        active.append(decision)
    results = []
    for month in months:
        confirmed = any(v.start_month <= month <= v.end_month for v in active)
        if not confirmed:
            results.append(MonthCoverage(month, False, None, None, None, None, None, (),
                                         ("Source coverage is not demonstrated for this month.",)))
            continue
        unresolved, valid = [], []
        unclassified = False
        if review.kind != "records" or review.questions:
            unresolved.append("Source columns or record type require review.")
        for row in review.rows:
            # A missing site or date could affect any claimed month. A known
            # different site cannot affect this site's covered cohort.
            if row.site and row.site != site:
                continue
            if not row.site or not row.work_date:
                if not row.excluded:
                    unresolved.append(f"Source row {row.origin.row_number}: site/date unresolved")
                continue
            if row.work_date[:7] != month:
                continue
            issues = tuple(i for i in row.issues
                           if i != "source date is outside this report period")
            if row.excluded or issues:
                unresolved.append(f"Source row {row.origin.row_number}: excluded or unresolved")
                continue
            try:
                when = date.fromisoformat(row.work_date)
            except ValueError:
                unresolved.append(f"Source row {row.origin.row_number}: invalid date")
                continue
            if when > as_of:
                unresolved.append(f"Source row {row.origin.row_number}: future date")
                continue
            if row.status not in ("Completed", "Open") or not row.work_order.strip():
                unresolved.append(f"Source row {row.origin.row_number}: identity/status unresolved")
                continue
            if row.work_type not in ("PM", "Non-PM"):
                unclassified = True
            valid.append(row)
        if unresolved:
            results.append(MonthCoverage(month, True, None, None, None, None, None,
                                         tuple(row.key for row in valid),
                                         tuple(dict.fromkeys(unresolved))))
            continue
        results.append(MonthCoverage(month, True, len(valid),
                                     sum(row.status == "Completed" for row in valid),
                                     sum(row.status == "Open" for row in valid),
                                     None if unclassified else sum(row.work_type == "PM" for row in valid),
                                     None if unclassified else sum(row.work_type == "Non-PM" for row in valid),
                                     tuple(row.key for row in valid),
                                     (("Unclassified PM/non-PM type; category counts unknown.",)
                                      if unclassified else ())))
    return tuple(results)
