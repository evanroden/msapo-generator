"""Deterministic page roles before paid Monthly section reading.

This is a reading filter, NOT an export/page-inclusion approval. Decisions are
source-id/page bound and cannot change original files or reviewed report blocks.
Ambiguous pages remain available to an operator for one explicit correction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import re


# Anchored evidence only. Mentioning a quote, water sample or commissioning in
# the body of a technical service report does not change the report destination.
_HEADINGS = (
    ("activity_summary", re.compile(
        r"^(?:vendor (?:service|technical) report|service (?:report|visit)|"
        r"maintenance (?:service )?report|technical service report|"
        r"monthly activity(?: summary)?)(?:\b|\s*[:\-])", re.I)),
    ("water_reports", re.compile(
        r"^(?:water[ -]treatment(?:\s+(?:report|log|results?|analysis))?|"
        r"water[ -]analysis|chemical[ -]treatment(?:\s+(?:report|log))?)(?:\b|\s*[:\-])", re.I)),
    ("mbcx_report", re.compile(
        r"^(?:mbcx(?:\s+(?:report|results?|summary))?|"
        r"monitoring[ -]based commissioning(?:\s+report)?|"
        r"system performance report)(?:\b|\s*[:\-])", re.I)),
    ("utility_analysis", re.compile(
        r"^(?:utility (?:scorecard|results?|report|analysis|consumption|usage)|"
        r"monthly (?:energy|utility) (?:scorecard|results?|report|analysis))\b", re.I)),
    ("work_orders", re.compile(
        r"^(?:work[ -]orders?(?:\s+(?:summary|status|report|log|export))?|"
        r"cmms (?:export|report))\b", re.I)),
    ("training", re.compile(
        r"^(?:training (?:attendance|records?|log|summary|roster)|"
        r"completed training|safety training roster)\b", re.I)),
    ("capital_renewal", re.compile(
        r"^(?:capital (?:renewal|replacement|plan|projects?)|"
        r"equipment replacement plan)\b", re.I)),
    ("proposals", re.compile(
        r"^(?:proposals?(?:\s+(?:scope|summary|report))?|"
        r"quotation|quote(?:\s+(?:summary|scope))?|scope of work)\b", re.I)),
)
_SOURCE_TYPES = {
    "Vendor service": "activity_summary",
    "Improvement / training photo": "activity_summary",
    "Water treatment": "water_reports",
    "MBCx": "mbcx_report",
    "Utility results": "utility_analysis",
    "CMMS export": "work_orders",
    "Training": "training",
    "Capital renewal": "capital_renewal",
    "Proposal / quote": "proposals",
}
_READER_DESTINATIONS = frozenset({"activity_summary", "capital_renewal", "proposals"})
_SITE_LABEL = re.compile(r"(?im)^\s*(?:facility|site|building)\s*[:=]\s*([^\r\n]{1,160})")


@dataclass(frozen=True)
class PageRole:
    source_id: str
    page: int
    destinations: tuple[str, ...]
    rule: str
    page_sha256: str

    @property
    def ambiguous(self) -> bool:
        return len(self.destinations) > 1


def _table_role(content, number):
    # The table index is the spreadsheet page identity. Do not allow an
    # unrelated worksheet to give a second page its table/role.
    if number > len(content.tables):
        return ""
    table = content.tables[number - 1]
    headings = {"".join(re.findall(r"[a-z0-9]+", label.casefold()))
                for label in table.columns}
    if (headings & {"workorder", "wonumber", "wo", "taskcode"}
            and headings & {"finishdate", "completeddate", "status", "taskcodedescription"}):
        return "work_orders"
    if "scope" in headings and (headings & {"vendor", "status", "decision"}):
        return "proposals"
    if "recommendation" in headings and (headings & {"priority", "facility", "site"}):
        return "capital_renewal"
    if "training" in headings and (headings & {"hours", "date", "attendee"}):
        return "training"
    return ""


def classify_page(content, number: int) -> PageRole:
    source = content.source
    if type(number) is not int or not 1 <= number <= len(source.page_texts):
        raise ValueError("Source page is missing or out of range.")
    value = source.page_texts[number - 1]
    found = set()
    for line in (line.strip() for line in value.splitlines()[:6]):
        if 0 < len(line) <= 150:
            found.update(destination for destination, pattern in _HEADINGS if pattern.match(line))
    # Strong per-page headings override broad file-level classification.
    if found:
        targets = tuple(sorted(found))
        rule = "page heading" if len(targets) == 1 else "conflicting page headings"
    elif table_role := _table_role(content, number):
        targets, rule = (table_role,), "native table columns"
    elif fallback := _SOURCE_TYPES.get(source.classification):
        targets, rule = (fallback,), "reviewable source type"
    else:
        targets, rule = (), "unclassified source page"
    return PageRole(source.id, number, targets, rule, sha256(value.encode()).hexdigest())


def _site_matches(source, text, profile) -> bool:
    if profile is None:
        return True
    names = {" ".join(name.casefold().split())
             for facility in profile.facilities
             for name in (facility.key, facility.title, *facility.aliases)}
    source_site = " ".join(source.facility.casefold().split())
    if source_site and source_site not in names:
        return False
    # Unknown site stays unresolved in later report preflight; an explicit
    # foreign page label blocks unnecessary AI transmission immediately.
    return all(" ".join(label.casefold().split()) in names for label in _SITE_LABEL.findall(text))


def _period_matches(source, period) -> bool:
    if period is None or not source.service_date:
        return True
    try:
        observed = date.fromisoformat(source.service_date)
    except (TypeError, ValueError):
        return False
    return (observed.year, observed.month) == (period.year, period.month)


def choose_reader_pages(profile, contents, destination, *, period=None, corrections=None,
                        accepted_pages=(), native_mapped=()):
    """Return exact eligible (source id, page) pairs without modifying evidence.

    Corrections are source/id/page/immutable SHA scoped and can only select one
    of the page's observed candidate roles. One mixed page requires one choice,
    not multiple independent classification/drop-down prompts. Native mapped
    table pages and report-accepted pages are omitted from model input only.
    """
    if destination not in _READER_DESTINATIONS:
        raise ValueError("Unknown reader destination.")
    corrections = corrections or {}
    accepted = set(accepted_pages)
    native = set(native_mapped)
    seen, result = {}, []
    for content in contents:
        source = content.source
        previous = seen.get(source.id)
        if previous is not None:
            if previous != source.fingerprint:
                raise ValueError("Conflicting revisions for the same source identity.")
            continue
        seen[source.id] = source.fingerprint
        if not _period_matches(source, period):
            continue
        for number, text in enumerate(source.page_texts, 1):
            identity = (source.id, number)
            if identity in accepted or identity in native or not _site_matches(source, text, profile):
                continue
            role = classify_page(content, number)
            choice = corrections.get((source.id, number, source.sha256))
            if choice is not None and choice not in role.destinations:
                raise ValueError("The corrected destination is not a candidate for this source page.")
            if role.ambiguous:
                if choice != destination:
                    continue
            elif role.destinations and destination not in role.destinations:
                continue
            elif choice is not None and choice != destination:
                continue
            # No confident role remains eligible under the legacy reader path:
            # never misclassify an unscanned/unstructured unknown by filename.
            result.append(identity)
    return tuple(result)
