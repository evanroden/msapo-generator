"""Pure review-state rules for the streamlined quote-to-Smartsheet flow.

The Streamlit page uses these helpers to decide which values need to be shown
as questions and which already-filled values can stay in the correction panel.
Keeping the decision independent from widget rendering makes the behavior easy
to regression-test across reruns and viewport-specific layouts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.po_rules import parse_amount


_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


@dataclass(frozen=True)
class ReviewNeeds:
    """Values that must be presented outside the collapsed correction panel."""

    routing: bool
    original_po_number: bool
    job_number: bool
    asset: bool
    total: bool
    vendor: bool
    description: bool
    contact_email: bool

    @property
    def any(self) -> bool:
        return any(
            (
                self.routing,
                self.original_po_number,
                self.job_number,
                self.asset,
                self.total,
                self.vendor,
                self.description,
                self.contact_email,
            )
        )


def retain_review_needs(
    previous: object,
    current: ReviewNeeds,
) -> ReviewNeeds:
    """Keep every question that has needed operator input for this quote.

    Streamlit reruns after an input is committed. Without retained placement,
    a just-completed field can immediately move into the collapsed correction
    panel, which looks like the answer disappeared. New dependency-driven gaps
    (for example, an ambiguous asset after a site is chosen) are added as they
    become knowable.
    """
    if not isinstance(previous, ReviewNeeds):
        return current
    return ReviewNeeds(
        routing=previous.routing or current.routing,
        original_po_number=(
            previous.original_po_number or current.original_po_number
        ),
        job_number=previous.job_number or current.job_number,
        asset=previous.asset or current.asset,
        total=previous.total or current.total,
        vendor=previous.vendor or current.vendor,
        description=previous.description or current.description,
        contact_email=previous.contact_email or current.contact_email,
    )


def email_is_valid_or_blank(value: object) -> bool:
    """Return whether an optional email is empty or conservatively well formed."""
    text = str(value or "").strip()
    return not text or _EMAIL_RE.fullmatch(text) is not None


def tax_alert_message(status: object) -> str:
    """Return the prominent, non-blocking tax alert for a quote analysis."""
    normalized = str(status or "").strip().casefold()
    if normalized == "included":
        return ""
    if normalized == "excluded":
        return (
            "The quote says tax is not included. Make sure the PO/CO amount "
            "includes any applicable tax before generating the package."
        )
    return (
        "No tax was found in the quote. Verify whether tax applies and make sure "
        "the PO/CO amount is the final payable total."
    )


def review_needs(
    *,
    routing_ready: bool,
    request_type: object,
    original_po_number: object,
    job_number: object,
    asset_resolved: bool,
    total: object,
    vendor: object,
    description: object,
    contact_email: object,
) -> ReviewNeeds:
    """Classify unresolved/invalid values for exception-only visible prompts."""
    amount = parse_amount(total)
    return ReviewNeeds(
        routing=not routing_ready,
        original_po_number=(
            str(request_type or "").strip() == "CHANGE ORDER"
            and not str(original_po_number or "").strip()
        ),
        job_number=not str(job_number or "").strip(),
        asset=not asset_resolved,
        total=amount is None or amount <= 0,
        vendor=not str(vendor or "").strip(),
        description=not str(description or "").strip(),
        contact_email=not email_is_valid_or_blank(contact_email),
    )
