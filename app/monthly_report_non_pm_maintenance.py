"""Conservative Maintenance projection from an existing reviewed work-order export.

This consumes the *same* saved WorkOrderReview used by Activity; it never reads a
second upload, changes an accepted receipt, or publishes another report section.
A caller must explicitly integrate proposed tables using its existing
optimistic-concurrency and manual-edit preservation rules.

Only source-verified completed Non-PM work in the selected month can reach the
onsite ENFRA five-column table. Vendor/leased evidence is returned separately
for Activity, and unknown performers remain in review. A dated source work event
is a documented fallback ONLY when no closed/completion column exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Mapping

from app.monthly_report_content_policy import contains_price, table_has_pricing
from app.monthly_report_model import ReportPeriod, ReportProfile, ReportTable
from app.monthly_report_service_call_mapping import OUTPUT_COLUMNS
from app.monthly_report_work_order_normalized import (
    SourceRow, WorkOrderReview, restore_review, review_record,
)

FIELD_HEADERS = {
    "area": {"area", "room", "workarea", "buildingarea", "zone", "equipmentlocation"},
    "task": {"taskcodedescription", "taskdescription", "taskcode", "description",
             "workdescription", "jobdescription", "workperformed", "task",
             "serviceperformed", "servicework"},
    "tag": {"tagnumber", "tag", "equipmenttag", "assettag", "assetid",
            "equipmentid", "equipmentnumber"},
    "performer": {"performedby", "workperformedby", "performer", "performerorganization",
                  "performedbyorganization", "servicedby", "serviceprovider",
                  "performertype", "workerorganization"},
}
# These are source-described organizational categories, never person names.
CLASSIFICATIONS = {
    "enfra": "ENFRA onsite",
    "enfraonsite": "ENFRA onsite",
    "enfratechnician": "ENFRA onsite",
    "enfraonsitetechnician": "ENFRA onsite",
    "vendor": "Vendor/leased",
    "vendorstaff": "Vendor/leased",
    "vendorperformed": "Vendor/leased",
    "contractor": "Vendor/leased",
    "subcontractor": "Vendor/leased",
    "thirdparty": "Vendor/leased",
    "leased": "Vendor/leased",
    "leasedstaff": "Vendor/leased",
    "agency": "Vendor/leased",
}
CLOSED_DATE_HEADERS = {"closeddate", "dateclosed", "closedon", "completedon",
                       "completiondate", "completiondatetime", "datecompleted",
                       "finishdate", "finisheddate", "actualfinish", "workcompleteddate"}
ACTIVITY_COLUMNS = (
    "Work order", "Site", "Recorded completion date", "Performer category",
    "Work performed", "Area", "Equipment tag",
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).casefold())


def _column(columns: tuple[str, ...], key: str, occupied: set[int]) -> tuple[int | None, bool]:
    matches = [n for n, value in enumerate(columns)
               if _norm(value) in FIELD_HEADERS[key] and n not in occupied]
    return (matches[0], False) if len(matches) == 1 else (None, len(matches) > 1)


@dataclass(frozen=True)
class MaintenanceCandidate:
    key: str
    original: SourceRow
    work_order: str
    site: str
    completed_date: str
    date_basis: str
    area: str
    task: str
    tag: str
    performer: str
    performer_basis: str
    trade: str
    disposition: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class MaintenanceProjection:
    review_revision: str
    source_reference: str
    period_key: str
    candidates: tuple[MaintenanceCandidate, ...]
    onsite_table: ReportTable | None
    vendor_activity_table: ReportTable | None

    @property
    def needs_review(self):
        return tuple(row for row in self.candidates if row.disposition == "needs_review")

    @property
    def excluded(self):
        return tuple(row for row in self.candidates if row.disposition == "not_eligible")


def project_completed_non_pm(
    review: WorkOrderReview,
    profile: ReportProfile,
    period: ReportPeriod,
    *,
    expected_revision: str,
    corrections: Mapping[str, Mapping[str, str]] | None = None,
    site_performer_rules: Mapping[str, Mapping[str, str]] | None = None,
) -> MaintenanceProjection:
    """Return editable source-bound proposals, never automatic approval.

    `corrections` is a report-scoped, reviewable mapping keyed by original source
    row identity. Callers must store it with CAS before publishing. A performer
    correction is an explicit classification decision, not a guessed employee.
    Site-specific mappings classify exact recorded organization values only.
    Unknown classification is not treated as ENFRA in-house labor.
    """
    if expected_revision != review.revision or review.period_key != period.key:
        raise ValueError("Work-order review or month changed; reopen the reviewed source.")
    restore_review(review_record(review))  # Verify all immutable source row identities.
    if review.kind != "records":
        raise ValueError("Maintenance requires individual work-order records, not a summary grid.")
    allowed = {site.key: site.title for site in profile.facilities}
    if {key for key, _ in review.allowed_sites} != set(allowed):
        raise ValueError("Maintenance review belongs to a different site profile.")
    corrections = corrections or {}
    rules = site_performer_rules or {}
    if any(site not in allowed for site in rules):
        raise ValueError("Unknown site-specific performer rule.")
    if any(not isinstance(items, Mapping) or any(
        not isinstance(key, str) or value not in ("ENFRA onsite", "Vendor/leased")
        for key, value in items.items()) for items in rules.values()):
        raise ValueError("Site rules must explicitly classify recorded performer values.")
    if any(key not in {row.key for row in review.rows}
           or not isinstance(changes, Mapping)
           or any(name not in ("area", "task", "tag", "performer")
                  or not isinstance(value, str) or len(value) > 4000
                  for name, value in changes.items())
           for key, changes in corrections.items()):
        raise ValueError("Correction does not match the reviewed source row or field.")

    # Physical column identities are used; duplicate/ambiguous headings
    # cannot be resolved by silently taking the first column.
    occupied = {getattr(review.mapping, name)
                for name in ("work_order", "site", "work_date", "completed_date",
                             "status", "work_type", "trade")
                if getattr(review.mapping, name) is not None}
    indices = {name: _column(review.original_columns, name, occupied)
               for name in FIELD_HEADERS}
    excluded = set()
    candidates = []
    for row in review.rows:
        changed = corrections.get(row.key, {})
        def cell(field):
            index, _ = indices[field]
            return (row.origin.cells[index].strip() if index is not None else "")
        area = changed.get("area", cell("area")).strip()
        task = changed.get("task", cell("task")).strip()
        tag = changed.get("tag", cell("tag")).strip()
        performer_raw = changed.get("performer", cell("performer")).strip()
        performer = (CLASSIFICATIONS.get(_norm(performer_raw), "")
                     if "performer" not in changed else
                     {"ENFRA onsite": "ENFRA onsite",
                      "Vendor/leased": "Vendor/leased",
                      "Unknown": ""}.get(performer_raw, ""))
        performer_basis = ("reviewer-classified" if "performer" in changed and performer else
                           "source-stated" if performer else "unknown")
        if "performer" in changed and performer_raw not in (
                "ENFRA onsite", "Vendor/leased", "Unknown"):
            raise ValueError("Choose ENFRA onsite, Vendor/leased or Unknown explicitly.")
        # Site policies may clarify source-specific *organization codes*.
        if "performer" not in changed and row.site in rules:
            aliases = {_norm(k): v for k, v in rules[row.site].items()}
            rule_performer = aliases.get(_norm(performer_raw))
            if rule_performer:
                performer = rule_performer
                performer_basis = "site-rule"
        explicit_closed = review.mapping.completed_date is not None
        # A physically present but unmapped completion column is NOT absence.
        # A fallback in that case would silently attribute the wrong month.
        unmapped_closed = not explicit_closed and any(
            _norm(label) in CLOSED_DATE_HEADERS for label in review.original_columns)
        completion = (row.completed_date if explicit_closed else
                      "" if unmapped_closed else row.work_date)
        basis = ("closed date" if explicit_closed else
                 "closed-date mapping required" if unmapped_closed else
                 "work-date fallback (no closed-date column)")
        reasons = []
        disposition = ""
        if row.excluded or row.work_type == "PM" or row.status == "Open":
            disposition = "not_eligible"
        elif row.status != "Completed":
            reasons.append("Completion status is unresolved.")
        elif row.work_type != "Non-PM":
            reasons.append("Non-PM category is not verified.")
        if not row.work_order:
            reasons.append("Work-order identifier is missing.")
        if row.site not in allowed:
            reasons.append("Facility identity needs review.")
        if not completion:
            reasons.append("Explicit closed date is missing, invalid or unmapped."
                           if explicit_closed or unmapped_closed else
                           "Work date fallback is missing or invalid.")
        elif completion[:7] != period.key:
            disposition = "not_eligible" if not reasons else "needs_review"
        if not task:
            reasons.append("Work description is missing.")
        for field, (_, ambiguous) in indices.items():
            if ambiguous and field not in changed:
                reasons.append(f"Ambiguous {field} source columns need mapping.")
        if not performer:
            reasons.append("Performer is unknown; cannot attribute work to ENFRA.")
        # Do not export source financial values from any table/metadata.
        if any(contains_price(value) for value in (area, task, tag)):
            reasons.append("Output description/area/tag contains pricing.")
        if any(issue not in (
                "source date is outside this report period", "work_date needs review")
               for issue in row.issues):
            reasons.append("Underlying work-order source row needs review.")
        if any(question for question in review.questions
               if not (explicit_closed and question == "Map work_date before including records")):
            reasons.append("Unresolved source column mapping.")
        if reasons and disposition != "not_eligible":
            disposition = "needs_review"
        elif not disposition:
            disposition = "onsite" if performer == "ENFRA onsite" else "vendor_activity"
        candidates.append(MaintenanceCandidate(
            row.key, row.origin, row.work_order, row.site, completion, basis,
            area, task, tag, performer, performer_basis, row.trade, disposition,
            tuple(dict.fromkeys(reasons))))
    # One WO identity is unique only *within* a site. Duplicates are never
    # silently dropped; a duplicate across different sites remains distinct.
    groups = {}
    for n, candidate in enumerate(candidates):
        if candidate.disposition in ("onsite", "vendor_activity"):
            groups.setdefault((candidate.site, candidate.work_order.casefold()), []).append(n)
    for group in groups.values():
        if len(group) > 1:
            excluded.update(group)
    if excluded:
        from dataclasses import replace
        candidates = [replace(row, disposition="needs_review",
                     reasons=(*row.reasons, "Duplicate site/work-order identity needs review."))
                      if n in excluded else row for n, row in enumerate(candidates)]
    onsite = []
    vendor = []
    for row in candidates:
        if row.disposition == "onsite":
            location = row.area
            if len(allowed) > 1:
                location = f"{allowed[row.site]} — {location}" if location else allowed[row.site]
            onsite.append((row.work_order, row.completed_date, location, row.task, row.tag))
        elif row.disposition == "vendor_activity":
            vendor.append((row.work_order, allowed[row.site], row.completed_date,
                           f"Vendor/leased ({row.performer_basis})", row.task, row.area, row.tag))
    if onsite and table_has_pricing(OUTPUT_COLUMNS, tuple(onsite), work_orders=True):
        raise ValueError("Pricing requires correction before including Maintenance calls.")
    if vendor and table_has_pricing(ACTIVITY_COLUMNS, tuple(vendor), work_orders=True):
        raise ValueError("Pricing requires correction before including vendor Activity evidence.")
    return MaintenanceProjection(
        review.revision, review.source_reference, period.key, tuple(candidates),
        ReportTable(OUTPUT_COLUMNS, tuple(onsite), review.source_reference) if onsite else None,
        ReportTable(ACTIVITY_COLUMNS, tuple(vendor), review.source_reference) if vendor else None,
    )
