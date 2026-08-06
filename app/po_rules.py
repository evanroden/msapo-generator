"""Canonical purchase-order routing rules for the Smartsheet handoff.

The former workflow classified requests from whether a vendor visited the site.
The current policy classifies them from the work/delivery relationship instead:
onsite labor, onsite rental, vendor delivery without labor, or third-party
shipping without a vendor visit.  Keep every UI and integration consumer on
these helpers so Object Account and Agreement Type cannot drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


ONSITE_LABOR = "onsite_labor"
ONSITE_RENTAL = "onsite_rental"
VENDOR_DELIVERY = "vendor_delivery"
THIRD_PARTY_SHIPPING = "third_party_shipping"

PURCHASE_ROUTE_LABELS: dict[str, str] = {
    ONSITE_LABOR: "Vendor will perform labor onsite",
    ONSITE_RENTAL: (
        "Onsite rental service (for example, a rental chiller or scissor lift)"
    ),
    VENDOR_DELIVERY: "Vendor will deliver/drop off onsite, with no labor",
    THIRD_PARTY_SHIPPING: (
        "Third-party shipping; vendor will not come onsite and will perform no labor"
    ),
}
PURCHASE_ROUTES: tuple[str, ...] = tuple(PURCHASE_ROUTE_LABELS)

MATERIALS_ACCOUNT = "5301-MATERIALS"
SUBCONTRACTOR_ACCOUNT = "5511-SUBCONTRACTOR"
EQUIPMENT_ACCOUNT = "5302-EQUIPMENT"
OUTSIDE_RENTALS_ACCOUNT = "5411-OUTSIDE RENTALS"

SERVICE_AGREEMENT = "03 - MSAPO (SERVICE)"
# The live Smartsheet option is MRAPO even though the business shorthand is
# commonly spoken as “MSAPO rental.”  The exact option must be sent to the form.
RENTAL_AGREEMENT = "03 - MRAPO (RENTAL)"
STANDARD_PO_UNDER_25K = "ON - STANDARD PO UNDER $25K"
STANDARD_PO_OVER_25K = "OR - STANDARD PO OVER $25K"
EQUIPMENT_PO = "OR - EQUIPMENT PO"

STANDARD_PO_THRESHOLD = Decimal("25000.00")


@dataclass(frozen=True)
class POClassification:
    object_account: str
    agreement_type: str


def parse_amount(value: object) -> Decimal | None:
    """Parse a currency-like amount without guessing malformed values."""
    text = re.sub(r"[^0-9.-]", "", str(value or ""))
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def classify_po(route: str, total: object) -> POClassification:
    """Return the exact Smartsheet Object Account and Agreement Type.

    The $25,000 boundary is intentionally conservative: only totals strictly
    below $25,000 use the under-$25K option; $25,000 and above use the other
    Standard PO option.
    """
    if route == ONSITE_LABOR:
        return POClassification(SUBCONTRACTOR_ACCOUNT, SERVICE_AGREEMENT)
    if route == ONSITE_RENTAL:
        return POClassification(OUTSIDE_RENTALS_ACCOUNT, RENTAL_AGREEMENT)
    if route == THIRD_PARTY_SHIPPING:
        return POClassification(EQUIPMENT_ACCOUNT, EQUIPMENT_PO)
    if route == VENDOR_DELIVERY:
        amount = parse_amount(total)
        if amount is None:
            raise ValueError(
                "A valid all-in PO/CO amount is required to choose the Standard PO tier."
            )
        agreement = (
            STANDARD_PO_UNDER_25K
            if amount < STANDARD_PO_THRESHOLD
            else STANDARD_PO_OVER_25K
        )
        return POClassification(MATERIALS_ACCOUNT, agreement)
    raise ValueError("Choose how the vendor will provide the goods or service.")


def normalize_asset_id(value: object) -> str:
    """Return only the numeric asset identifier, without a letter prefix.

    Asset registries often display values such as ``A001234`` or
    ``EEA-CWP-07``.  Smartsheet expects the numeric portion only.  Use the final
    numeric run because prefixes and equipment abbreviations can themselves
    contain separators; preserve leading zeroes because they may be significant.
    """
    text = str(value or "").strip()
    if not text or text.casefold() in {"none applicable", "n/a", "na"}:
        return ""
    matches = re.findall(r"\d+", text)
    return matches[-1] if matches else ""


def asset_id_is_numeric(value: object) -> bool:
    text = str(value or "").strip()
    return not text or text.isdigit()
