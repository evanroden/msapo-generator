"""Read-only, source-bound evidence for the single Monthly file workspace.

A card describes existing source/status decisions; it cannot approve a source,
infer a site/date, start a reader, or replace a native correction control.
"""
from dataclasses import dataclass

from app.monthly_report_section_uploads import SECTION_UPLOADS
from app.monthly_report_source_details import source_date


@dataclass(frozen=True)
class SourceCardEvidence:
    source_type: str
    site: str
    month: str
    destination: str
    contribution: str
    warning: str


def source_card_evidence(source, status, draft):
    """Display only recorded metadata and the existing authoritative status."""
    when = source_date(source.service_date)
    site = source.facility.strip() if source.facility else ""
    if not site:
        site = "Recorded multi-site/contract scope" if source.scope_review else "Not established"
    titles = {spec.key: section.title
              for section in draft.sections for spec in section.blocks}
    destinations = tuple(dict.fromkeys(
        titles.get(key, SECTION_UPLOADS[key][0] if key in SECTION_UPLOADS
                   else key.replace("_", " ").capitalize())
        for key in status.destinations))
    return SourceCardEvidence(
        source_type=(source.classification or "Unclassified") + " (" +
                    (source.suffix.lstrip(".").upper() or "FILE") + ")",
        site=site,
        month=when.strftime("%B %Y") if when else "Not established",
        destination=", ".join(destinations) if destinations else "Not included",
        contribution=status.summary or "Not included",
        warning=status.reason if status.needs_correction else "",
    )
