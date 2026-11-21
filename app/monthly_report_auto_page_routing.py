"""Conservative, source-bound page destinations for a Monthly report.

Routing is an advisory decision, not content, site or client-output approval.
Every page keeps its exact source identity; unresolved pages remain visible and
no routine import makes paid model calls or modifies saved source records.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from app.monthly_report_content_policy import (
    contains_price, page_allowed, page_fingerprint, page_status,
)
from app.monthly_report_mbcx_financial_pages import has_financial_page_review
from app.monthly_report_source_scope import reviewed_scope


# A heading must be at the start of a real line. Passing references to a
# different section in body prose cannot move the page between report sections.
_HEADINGS = (
    ("water", "water_reports", re.compile(
        r"^(?:water[ -]treatment(?:\s+(?:report|log|analysis|results?))?|"
        r"chemical[ -]treatment(?:\s+(?:report|log))?|water[ -]analysis)\b", re.I)),
    ("mbcx", "mbcx_report", re.compile(
        r"^(?:mbcx(?:\s+(?:report|results?|summary))?|"
        r"monitoring[ -]based commissioning(?:\s+report)?|system performance report)\b", re.I)),
    ("utility", "utility_analysis", re.compile(
        r"^(?:utility(?:\s+(?:analysis|results?|scorecard|report|usage|consumption))|"
        r"monthly (?:utility|energy) (?:report|scorecard|analysis))\b", re.I)),
    ("activity", "improvements", re.compile(
        r"^(?:(?:vendor|service|maintenance|technical)\s+(?:service |visit |activity |activities )?report|"
        r"service visit|monthly activity(?: summary)?)\b", re.I)),
    ("photos", "improvements", re.compile(
        r"^(?:progress (?:photos?|images?)|site work photos?)\b", re.I)),
    ("proposals", None, re.compile(
        r"^(?:proposals?(?:\s+summary)?|quotation|quote(?:\s+summary)?|scope of work)\b", re.I)),
    ("capital", None, re.compile(
        r"^(?:capital (?:renewal|replacement|plan|projects?)|equipment replacement plan)\b", re.I)),
    ("training", None, re.compile(
        r"^(?:training (?:record|summary|log|attendance)|completed training)\b", re.I)),
    ("work_orders", None, re.compile(
        r"^(?:work[ -]orders?(?:\s+(?:summary|status|report|log))?|cmms export)\b", re.I)),
    ("standing", None, re.compile(
        r"^(?:organizational? chart|contact (?:directory|matrix)|workflow diagram|"
        r"thermal capacity|standing (?:data|information))\b", re.I)),
)
_CLASSIFICATION = {
    "Vendor service": ("activity", "improvements"),
    "Water treatment": ("water", "water_reports"),
    "MBCx": ("mbcx", "mbcx_report"),
    "Utility results": ("utility", "utility_analysis"),
    "Improvement / training photo": ("photos", "improvements"),
    "Proposal / quote": ("proposals", None),
    "Capital renewal": ("capital", None),
    "Training": ("training", None),
    "CMMS export": ("work_orders", None),
}
_PAGE_DESTINATIONS = frozenset({"vendor_reports", "water_reports", "mbcx_report",
                                "utility_analysis", "improvements"})


@dataclass(frozen=True)
class PageRoute:
    source_id: str
    filename: str
    page: int
    section: str
    destination: str | None
    action: str  # ready, review, reference, blocked, excluded, retained
    reason: str = ""


def _heading(text):
    matches = set()
    # Only actual headings near the top of the page establish a role; model
    # guesses and filenames never supply unverified evidence.
    for line in (line.strip() for line in text.splitlines()[:4]):
        if not line or len(line) > 150:
            continue
        for section, destination, pattern in _HEADINGS:
            if pattern.match(line):
                matches.add((section, destination))
    if len(matches) == 1:
        return next(iter(matches)), False
    return None, bool(matches)


def _valid_site(source, profile):
    if profile is None:
        return True
    names = {" ".join(value.casefold().split()) for facility in profile.facilities
             for value in (facility.key, facility.title, *facility.aliases)}
    label = " ".join(source.facility.casefold().split())
    if label and label not in names:
        return False
    # A stale explicit scope receipt must never be rescued by a plausible
    # extracted facility label. Unknown sites require a current sites receipt.
    if source.scope_review:
        return (reviewed_scope(source, profile) or {}).get("kind") == "sites"
    return True


def _page_site_ok(text, profile):
    """An explicit foreign page-level site label overrides a mixed-file hint."""
    if profile is None:
        return True
    known = {" ".join(name.casefold().split()) for facility in profile.facilities
             for name in (facility.key, facility.title, *facility.aliases)}
    labels = re.findall(
        r"(?im)^[ \t]*(?:facility|site|building)[ \t]*[:=][ \t]*([^\r\n]{1,160})", text)
    return all(" ".join(label.casefold().split()) in known for label in labels)


def _valid_period(source, period):
    if period is None or not source.service_date:
        return True
    try:
        observed = date.fromisoformat(source.service_date)
    except (TypeError, ValueError):
        return False
    return (observed.year, observed.month) == (period.year, period.month)


BLOCKED_PAGE = "Client output excludes priced, legal-only, blank or signature-only pages."


def route_pages(contents, profile=None, *, period=None, overrides=None, owned=None):
    """Choose one destination for each source image/PDF page or a named exception.

    `overrides` is an *explicitly chosen* source-level destination, not a
    suggested default. `owned` is report asset provenance by (source_id, page).
    An existing page is never moved or added again. A repeated source in an
    import batch is processed once, while conflicting same-ID bytes fail closed.
    """
    from app.monthly_report_sources import image_numbers

    overrides = {} if overrides is None else overrides
    owned = {} if owned is None else owned
    result, seen = [], {}
    for content in contents:
        source = content.source
        previous = seen.get(source.id)
        if previous is not None:
            if previous != source.fingerprint:
                raise ValueError("Conflicting revisions for the same source identity; review the saved original again.")
            continue
        seen[source.id] = source.fingerprint
        if any(type(n) is not int or n < 1 or n > len(source.page_texts)
               for n in source.selected_pages):
            raise ValueError("Selected source page does not exist.")
        override = overrides.get(source.id)
        if override is not None and override not in _PAGE_DESTINATIONS | {"Do not embed"}:
            raise ValueError("Unknown explicit page destination.")
        site_ok, period_ok = _valid_site(source, profile), _valid_period(source, period)
        for number in image_numbers(content):
            text = source.page_texts[number - 1]
            hint, ambiguous = _heading(text)
            section, destination = hint or _CLASSIFICATION.get(
                source.classification, ("unclassified", None))
            owner = set(owned.get((source.id, number), ()))
            if owner:
                if len(owner) != 1 or next(iter(owner)) not in _PAGE_DESTINATIONS:
                    result.append(PageRoute(source.id, source.filename, number, section,
                                            None, "blocked", "Existing page has conflicting destinations; review ownership."))
                else:
                    result.append(PageRoute(source.id, source.filename, number, section,
                                            next(iter(owner)), "retained"))
                continue
            base = (source.id, source.filename, number, section)
            if not site_ok or not _page_site_ok(text, profile):
                result.append(PageRoute(*base, None, "blocked", "Confirm this page's exact site before including it."))
                continue
            if not period_ok:
                result.append(PageRoute(*base, None, "blocked", "Confirm this file's report month before including its pages."))
                continue
            if dict(source.client_page_exclusions).get(number) == page_fingerprint(source, number):
                result.append(PageRoute(*base, None, "excluded", "Explicitly left out of this report."))
                continue
            # Even auto-unselected unsafe pages are named. The adjacent
            # technical page remains independently eligible for inclusion.
            kind, _ = page_status(text, unreadable=number in source.needs_vision)
            # A priced ENFRA MBCx page with its own financial-page review is
            # decided by the destination-aware policy below (MBCx only), not
            # by this generic pricing veto. Captions and other kinds still veto.
            financial = kind == "pricing" and has_financial_page_review(source, number)
            if ((kind in {"pricing", "legal", "blank", "signature"} and not financial)
                    or contains_price(dict(source.captions).get(number, ""))):
                result.append(PageRoute(*base, None, "blocked", BLOCKED_PAGE))
                continue
            if number not in source.selected_pages:
                result.append(PageRoute(*base, None, "excluded", "Not selected for this report."))
                continue
            if ambiguous and override is None:
                result.append(PageRoute(*base, None, "review", "Multiple section headings; choose a destination for this page."))
                continue
            if override == "Do not embed":
                result.append(PageRoute(*base, None, "excluded", "Explicit destination: keep as reference only."))
                continue
            if override is not None:
                destination = override
                section = next((name for name, slot, _ in _HEADINGS if slot == override), "activity")
                base = (source.id, source.filename, number, section)
            if destination is None:
                result.append(PageRoute(*base, None,
                                        "reference" if section != "unclassified" else "review",
                                        "Use the corresponding structured report editor; this source page is retained."))
                continue
            if not page_allowed(source, number, profile=profile, destination=destination):
                if financial:
                    # Reviewed financial pages belong only in the MBCx section.
                    result.append(PageRoute(*base, None, "blocked", BLOCKED_PAGE))
                else:
                    result.append(PageRoute(*base, destination, "review",
                                            "Confirm this page and caption before inclusion."))
                continue
            result.append(PageRoute(*base, destination, "ready"))
    return tuple(result)


def batch_destinations(choices, section_page_owners=(), omitted=()):
    """Pages to prepare in this batch.

    Ready and review pages are new additions. A retained page already belongs
    to a report block, and preparing it again re-merges the same page. That is
    harmless for an included block, but a block whose section was deliberately
    left out takes the incoming copy in the merge and its section is switched
    back on. Retained pages of omitted blocks therefore stay where they are.
    """
    return [(choice.source_id, choice.destination, choice.page) for choice in choices
            if choice.destination
            and (choice.action in {"ready", "review"}
                 or (choice.action == "retained" and choice.destination not in omitted))
            and not (choice.source_id in section_page_owners and choice.destination == "water_reports")]
