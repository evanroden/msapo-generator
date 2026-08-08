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
    """Parse a conventional currency value without repairing bad input.

    The old implementation removed every nonnumeric character, which could
    turn malformed values such as ``1e3`` into ``13``.  Accept the formats the
    quote analyzer and UI actually produce, while rejecting ambiguous text,
    repeated signs, and more than two decimal places.
    """
    text = str(value or "").strip()
    text = re.sub(r"(?i)\bUSD\b", "", text)
    text = text.replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"-?(?:\d+(?:\.\d{1,2})?|\.\d{1,2})", text):
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
    if route not in PURCHASE_ROUTES:
        raise ValueError("Choose how the vendor will provide the goods or service.")

    amount = parse_amount(total)
    if amount is None or amount <= 0:
        raise ValueError("Enter a valid all-in PO/CO amount greater than $0.00.")

    if route == ONSITE_LABOR:
        return POClassification(SUBCONTRACTOR_ACCOUNT, SERVICE_AGREEMENT)
    if route == ONSITE_RENTAL:
        return POClassification(OUTSIDE_RENTALS_ACCOUNT, RENTAL_AGREEMENT)
    if route == EQUIPMENT_PURCHASE:
        return POClassification(EQUIPMENT_ACCOUNT, EQUIPMENT_PO)
    if route == MATERIALS_PURCHASE:
        agreement = (
            STANDARD_PO_UNDER_25K
            if amount < STANDARD_PO_THRESHOLD
            else STANDARD_PO_OVER_25K
        )
        return POClassification(MATERIALS_ACCOUNT, agreement)

    # ``route`` is guarded above.  Keep an explicit fail-closed tail so a
    # future enum addition cannot silently bypass classification.
    raise ValueError("Choose how the vendor will provide the goods or service.")


_RENTAL_RE = re.compile(
    r"\b(?:rental|rent(?:ed|ing)?|leased?|temporary chiller|scissor lift)\b"
)
_LABOR_RE = re.compile(
    r"\b(?:install(?:ation|ing|ed)?|repair(?:ing|ed)?|service|labor|technician|"
    r"start-?up|commission(?:ing|ed)?|inspect(?:ion|ing|ed)?|troubleshoot(?:ing|ed)?|"
    r"perform(?:ing|ed)? work)\b"
)
_NEGATION_BEFORE_RE = re.compile(
    r"(?:\bno\b|\bnot\b|\bwithout\b|\bexclude(?:d|s|ing)?\b|"
    r"\bowner[- ]provided\b|\bcustomer[- ]provided\b)"
    r"(?:\W+\w+){0,3}\W*$"
)
_NEGATION_AFTER_RE = re.compile(
    r"^\W*(?:(?:and|or|equipment|service|work|labor|installation|rental|"
    r"start-?up|commissioning)\W+){0,4}"
    r"(?:(?:is|are|will\W+be|to\W+be)\W+)?"
    r"(?:not\W+included|excluded|by\W+(?:others|owner|customer)|"
    r"provided\W+by\W+(?:others|owner|customer)|"
    r"not\W+(?:part\W+of|in)\W+(?:the\W+)?(?:quote|quoted\W+scope|scope))\b"
)


def _has_affirmative_match(source: str, pattern: re.Pattern[str]) -> bool:
    """Return true when a routing term is not locally negated.

    Quotes frequently list phrases such as ``installation excluded`` and
    ``rental by others``.  Looking only for the noun sends those purchases to
    the wrong account.  Examine a short window around every match and accept
    the route when at least one occurrence is affirmative.
    """
    for match in pattern.finditer(source):
        before = source[max(0, match.start() - 48) : match.start()]
        after = source[match.end() : min(len(source), match.end() + 48)]
        before_clause = re.split(r"[.;:\n]", before)[-1]
        after_clause = re.split(r"[.;:\n]|\bbut\b|\bhowever\b", after)[0]
        if not _NEGATION_BEFORE_RE.search(
            before_clause
        ) and not _NEGATION_AFTER_RE.search(after_clause):
            return True
    return False


def infer_purchase_route(text: object) -> str:
    """Make a reviewable fallback guess when the analyzer has no route value."""
    source = " ".join(str(text or "").lower().split())
    if _has_affirmative_match(source, _RENTAL_RE):
        return ONSITE_RENTAL
    if _has_affirmative_match(source, _LABOR_RE):
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
