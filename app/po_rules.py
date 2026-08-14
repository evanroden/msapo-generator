"""Canonical purchase-order routing rules for the Smartsheet handoff.

The August 2026 product-owner correction supersedes both historical EPO logic
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


# Vendor boilerplate -- terms and conditions, warranty, indemnity -- is not the
# quoted scope, and on a real quote it DWARFS the scope. The Trane quote that
# exposed this is 45,866 characters of which the actual proposal is 3,563: the
# remaining 92% is standard legal text that happens to contain "by others",
# "parts", "repairs" and "materials".
#
# Classifying the whole document therefore classifies Trane's lawyers rather
# than the job. Two independent misreads came from that single cause:
#
#   * "modifications made by others to Company's equipment" -- inside the
#     warranty exclusions, three pages after the scope -- tripped the
#     document-level labour disclaimer and silenced the labour signal for the
#     entire quote;
#   * "the cost of transporting a part requiring service" and thirteen similar
#     phrases made _is_parts_purchase true.
#
# The realistic-quote corpus never caught this because its entries are scope
# text with no attached terms, which is not what OCR hands us in production.
#
# Cut at the first boilerplate heading, but only when a substantial proposal
# precedes it -- a document whose scope follows its terms keeps everything.
_BOILERPLATE_HEADING_RE = re.compile(
    r"\b(?:terms\s+(?:and|&)\s+conditions"
    r"|standard\s+terms"
    r"|general\s+terms"
    r"|limited\s+warranty"
    r"|warranty\s+(?:and\s+)?(?:disclaimer|limitations?|exclusions?)"
    r"|limitation\s+of\s+liability"
    r"|indemnif(?:y|ication)|indemnit(?:y|ies))\b",
    re.IGNORECASE,
)

# Below this, the "scope" is too short to be a proposal and the cut is more
# likely to have removed real content than boilerplate.
_MIN_SCOPE_CHARS = 200


def scope_region(text: object) -> str:
    """The proposal, with trailing vendor boilerplate removed.

    Routing reads what the vendor is selling. Terms and conditions describe what
    happens if it goes wrong, in language that reuses every keyword the routing
    rules depend on, so leaving them in lets the boilerplate outvote the scope.

    Conservative in both directions: no heading found, or too little text before
    the first one, and the original is returned unchanged.
    """
    source = str(text or "")
    match = _BOILERPLATE_HEADING_RE.search(source)
    if not match or match.start() < _MIN_SCOPE_CHARS:
        return source
    return source[: match.start()]


# A labour word used as a NOUN MODIFIER names a product, not vendor work:
# "valve repair kits", "service parts", "installation hardware". Measured
# against a corpus of realistic quotes, these were the only false onsite_labor
# results, and both sent a materials purchase to 5511-SUBCONTRACTOR.
_LABOR_AS_PRODUCT_RE = re.compile(
    r"\b(?:install(?:ation)?|repair|service|maintenance)\s+"
    r"(?:kit|kits|part|parts|component|components|hardware|material|materials|"
    r"manual|manuals|contract|agreement)\b"
)

# A document-level disclaimer that the vendor supplies no labour. Unlike the
# window-based negation below, these carry across a sentence boundary: "Supply
# replacement service parts for the boiler. Labor by others." negates the whole
# quote, not just the clause it sits in.
_LABOR_DISCLAIMED_RE = re.compile(
    r"\b(?:labou?r|installation|install|rigging|start-?up|commissioning)\s+"
    r"(?:is\s+)?(?:to be\s+)?(?:by\s+(?:others|owner|customer)|"
    r"not\s+included|excluded|by\s+owner)\b"
    r"|\bby\s+others\b"
    r"|\bno\s+(?:onsite\s+)?labou?r\b"
)


# Group A covers a COMPLETE equipment item. Parts, kits and components FOR such
# an item are materials, but the equipment noun still appears in the text, so a
# bare Group A keyword search sends "service parts for the boiler" to
# 5302-EQUIPMENT. Detected against the same corpus that exposed the labour bias.
_PARTS_OF_EQUIPMENT_RE = re.compile(
    r"\b(?:parts?|kits?|components?|spares?|consumables?|filters?|gaskets?|"
    r"seals?|belts?|bearings?)\b\s*(?:for|to suit|to fit)?\b"
    r"|\b(?:replacement|service|repair|spare)\s+(?:parts?|kits?|components?)\b"
)


# "part of the quoted scope" is an idiom, not a component. Without this the
# phrase turns "Installation is not part of the scope. Supply one new boiler."
# into a materials purchase.
_PART_OF_IDIOM_RE = re.compile(r"\bparts?\s+of\b")


def _is_parts_purchase(source: str) -> bool:
    """Whether the quote buys components rather than a complete unit."""
    return bool(_PARTS_OF_EQUIPMENT_RE.search(_PART_OF_IDIOM_RE.sub(" ", source)))


def _labor_signal(source: str) -> bool:
    """Whether the vendor is affirmatively providing onsite labour.

    Two corrections over a plain keyword search, both driven by measured
    misclassifications rather than theory:

    * product phrases are removed first, so "repair kits" cannot read as repair
      work;
    * a document-level disclaimer ("labor by others") suppresses the signal even
      when it sits in a different sentence from the labour word.
    """
    if _LABOR_DISCLAIMED_RE.search(source):
        return False
    return _has_affirmative_match(_LABOR_AS_PRODUCT_RE.sub(" ", source), _LABOR_RE)


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
    source = " ".join(scope_region(text).lower().split())
    if _has_affirmative_match(source, _RENTAL_RE):
        return ONSITE_RENTAL
    if _labor_signal(source):
        return ONSITE_LABOR
    # Parts for a Group A item are materials, not the item itself.
    if group_a_equipment_match(source) and not _is_parts_purchase(source):
        return EQUIPMENT_PURCHASE
    return MATERIALS_PURCHASE


def normalize_asset_id(value: object) -> str:
    """Return the complete configured Asset ID, preserving every prefix.

    An earlier review referenced a five-digit JDE code, but the account team does not have
    a verified mapping for it. The product owner explicitly directed the tool
    to continue exporting the full asset codes already configured for every
    site. Keep the historical function name for compatibility with callers.
    """
    text = str(value or "").strip()
    if (
        not text
        or text.casefold() in {"none applicable", "n/a", "na"}
        or text.startswith("— Choose an asset")
    ):
        return ""
    return " ".join(text.split())


def asset_id_is_numeric(value: object) -> bool:
    """Compatibility helper: configured full asset codes are valid text IDs."""
    return len(normalize_asset_id(value)) <= 160
