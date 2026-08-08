"""Canonical purchase-order routing rules for the Smartsheet handoff.

Ashley Connolly's August 2026 correction supersedes both historical EPO logic
and the delivery-method version deployed in PR #33. Labor and rental take
priority. With neither present, items on the supplied Group A list are
Equipment and every other purchase is Materials; who delivers the item does
not determine the account.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.equipment_policy import group_a_equipment_match


ONSITE_LABOR = "onsite_labor"
ONSITE_RENTAL = "onsite_rental"
EQUIPMENT_PURCHASE = "equipment_purchase"
MATERIALS_PURCHASE = "materials_purchase"

PURCHASE_ROUTE_LABELS: dict[str, str] = {
    ONSITE_LABOR: "Vendor will perform labor onsite",
    ONSITE_RENTAL: (
        "Onsite rental service (for example, a rental chiller or scissor lift)"
    ),
    EQUIPMENT_PURCHASE: "Buying Group A equipment; no vendor labor onsite",
    MATERIALS_PURCHASE: "Buying materials or parts; no vendor labor onsite",
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
    if route == EQUIPMENT_PURCHASE:
        return POClassification(EQUIPMENT_ACCOUNT, EQUIPMENT_PO)
    if route == MATERIALS_PURCHASE:
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


def infer_purchase_route(text: object) -> str:
    """Make a reviewable fallback guess when the analyzer has no route value."""
    source = " ".join(str(text or "").lower().split())
    if re.search(r"\b(?:rental|rent|leased?|temporary chiller|scissor lift)\b", source):
        return ONSITE_RENTAL
    if re.search(
        r"\b(?:install|installation|repair|service|labor|technician|startup|"
        r"start-up|commission|inspect|troubleshoot|replace onsite|perform work)\b",
        source,
    ):
        return ONSITE_LABOR
    if group_a_equipment_match(source):
        return EQUIPMENT_PURCHASE
    return MATERIALS_PURCHASE


def normalize_asset_id(value: object) -> str:
    """Return the complete configured Asset ID, preserving every prefix.

    Ashley referenced a five-digit JDE code, but the account team does not have
    a verified mapping for it. The product owner explicitly directed the tool
    to continue exporting the full asset codes already configured for every
    site. Keep the historical function name for compatibility with callers.
    """
    text = str(value or "").strip()
    if not text or text.casefold() in {"none applicable", "n/a", "na"}:
        return ""
    return " ".join(text.split())


def asset_id_is_numeric(value: object) -> bool:
    """Compatibility helper: configured full asset codes are valid text IDs."""
    return len(normalize_asset_id(value)) <= 160
