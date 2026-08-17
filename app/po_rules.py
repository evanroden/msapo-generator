"""Canonical purchase-order routing rules for the Smartsheet handoff.

The August 2026 product-owner correction supersedes both historical EPO logic
and the delivery-method version deployed in PR #33. Labor and rental take
priority. With neither present, items on the supplied Group A list are
Equipment and every other purchase is Materials; who delivers the item does
not determine the account.

What depends on this module
---------------------------
``app.po_context`` (Object Account and Agreement Type on every submission),
``app.web_ui`` (the route selector, the uncertainty cross-check, and its
``_parse_amount`` compatibility wrapper), ``app.smartsheet._money_number``, and
``app.workflow_review``. ``parse_amount`` is the ONE currency parser in the
repository; every other one delegates here so classification, reconciliation
and Smartsheet validation cannot disagree about what "$1,234.56" means.

Why a wrong answer here is invisible
------------------------------------
Nothing downstream can tell a confident wrong route from a right one. It simply
appears in Smartsheet as an authoritative 5511-SUBCONTRACTOR / 03 - MSAPO
(SERVICE), and contract administration has no signal that the tool guessed.
That is why the string constants below are the EXACT live Smartsheet option
spellings and why ``classify_po`` raises rather than defaulting: a blank field
with a blocking warning is recoverable, a plausible wrong value is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.equipment_policy import group_a_equipment_match


# These four strings are stored in session state under ``purchase_route_<tok>``
# and re-validated by po_context against PURCHASE_ROUTES. They are internal
# identifiers, never shown; the operator sees PURCHASE_ROUTE_LABELS.
ONSITE_LABOR = "onsite_labor"
ONSITE_RENTAL = "onsite_rental"
EQUIPMENT_PURCHASE = "equipment_purchase"
MATERIALS_PURCHASE = "materials_purchase"

# The dict is also the option ORDER of the selectbox in web_ui, via
# PURCHASE_ROUTES below. Reordering changes what the operator sees first.
PURCHASE_ROUTE_LABELS: dict[str, str] = {
    ONSITE_LABOR: "Vendor will perform labor onsite",
    ONSITE_RENTAL: (
        "Onsite rental service (for example, a rental chiller or scissor lift)"
    ),
    EQUIPMENT_PURCHASE: "Buying Group A equipment; no vendor labor onsite",
    MATERIALS_PURCHASE: "Buying materials or parts; no vendor labor onsite",
}
PURCHASE_ROUTES: tuple[str, ...] = tuple(PURCHASE_ROUTE_LABELS)

# Exact live-form picklist values, imported by smartsheet.OBJECT_ACCOUNT_OPTIONS
# and AGREEMENT_TYPE_OPTIONS. Smartsheet drops an unrecognised picklist value
# instead of rejecting the row, so a stray space or a changed hyphen here lands
# a submission with a BLANK account -- no error anywhere in this application.
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

# Decimal, not float: this is a boundary comparison on money, and $24,999.99
# versus $25,000.00 selects a different approval path. A float literal cannot
# represent either exactly and the corpus test pins both sides of the edge.
STANDARD_PO_THRESHOLD = Decimal("25000.00")


@dataclass(frozen=True)
class POClassification:
    """The two Smartsheet cells that a route plus an amount fully determine.

    Only ever produced by :func:`classify_po`. There is no "unknown" member and
    no default instance on purpose: the absence of a classification is
    represented by the ValueError, so no caller can accidentally submit a
    placeholder pair.
    """

    object_account: str
    agreement_type: str


def parse_amount(value: object) -> Decimal | None:
    """Parse a conventional currency value without repairing bad input.

    The old implementation removed every nonnumeric character, which could
    turn malformed values such as ``1e3`` into ``13``.  Accept the formats the
    quote analyzer and UI actually produce, while rejecting ambiguous text,
    repeated signs, and more than two decimal places.

    Returns ``None`` for anything it cannot read exactly, INCLUDING text a
    human would find obvious ("1,234.5 ea", "(1,234.56)", "1.234,56"). That is
    the contract: the caller must treat None as "ask the operator", never as
    zero. Negative values parse successfully -- rejecting them is
    ``classify_po``'s job, so the amount and the sign produce different
    messages.
    """
    text = str(value or "").strip()
    text = re.sub(r"(?i)\bUSD\b", "", text)
    text = text.replace("$", "").replace(",", "").strip()
    # Anchored with fullmatch, and the decimal group is capped at TWO digits:
    # "12.345" is more likely a typo or a unit rate than a currency amount, and
    # accepting it would silently change the value sent to Smartsheet. The
    # leading "-?" appears once, so "--5" and "+-5" are rejected rather than
    # normalised.
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

    RAISES ``ValueError`` rather than returning a default, and the message is
    shown to the operator verbatim by po_context. This is the whole point of
    the function: the reported production defect was Object Account and
    Agreement Type reading Subcontractor/MSAPO on every request, and any
    fallback value reintroduces it. The amount is required for EVERY route,
    including the three that do not consult it, so an unpriced request can
    never be classified at all.
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


# Every pattern from here down is compiled WITHOUT re.IGNORECASE and is applied
# only to text that infer_purchase_route has already lower-cased and
# whitespace-collapsed. Adding a caller that passes raw text is a silent
# no-match: the route quietly falls through to materials_purchase.
_RENTAL_RE = re.compile(
    r"\b(?:rental|rent(?:ed|ing)?|leased?|temporary chiller|scissor lift)\b"
)
_LABOR_RE = re.compile(
    r"\b(?:install(?:ation|ing|ed)?|repair(?:ing|ed)?|service|labor|technician|"
    r"start-?up|commission(?:ing|ed)?|inspect(?:ion|ing|ed)?|troubleshoot(?:ing|ed)?|"
    r"perform(?:ing|ed)? work)\b"
)
# Both negation patterns are anchored to the WINDOW, not to the sentence: the
# "before" one ends at $ so it only fires when the negator is within three words
# of the match, and the "after" one starts at ^ so it only fires immediately
# after it. That bounded reach is deliberate. An unbounded search would let a
# "not included" anywhere in a long quote cancel an unrelated affirmative
# clause -- the same class of error that reading vendor boilerplate produced.
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
# likely to have removed real content than boilerplate. 200 characters is a
# judgement call, not a measurement -- it was chosen so that a document whose
# terms PRECEDE its scope is returned whole. Raising it makes the cut rarer and
# reinstates the Trane misread; lowering it starts gutting short proposals.
_MIN_SCOPE_CHARS = 200

# A short proposal can still be complete. When an explicit scope heading AND a
# price total both precede the legal heading, there is enough structural
# evidence to cut even before _MIN_SCOPE_CHARS. Requiring both keeps a document
# whose terms genuinely precede its scope untouched.
_SHORT_PROPOSAL_SCOPE_RE = re.compile(
    r"\b(?:scope\s+of\s+(?:work|supply)|quoted\s+scope)\b", re.IGNORECASE
)
_SHORT_PROPOSAL_TOTAL_RE = re.compile(
    r"\b(?:total\s+(?:price|amount)|proposal\s+total)\b", re.IGNORECASE
)

# A heading OWNS ITS LINE. That is what separates the section marker
#
#     TERMS AND CONDITIONS - QUOTED SERVICE
#
# from the same words used as ordinary vendor prose
#
#     This proposal carries our standard limited warranty of one year.
#
# The first version of this function cut at the first keyword match anywhere,
# which truncated any proposal that mentioned its own warranty mid-body. That
# was measured, not theorised: an in-scope warranty line past character 200
# discarded the entire "Scope of Work" block below it, the labour signal died
# with it, and the quote routed to 5302-EQUIPMENT / OR - EQUIPMENT PO instead
# of 5511-SUBCONTRACTOR / 03 - MSAPO (SERVICE). It failed silently -- a partial
# proposal produces a confident answer.
#
# Requiring the heading to own its line fixes that WITHOUT narrowing the
# heading list, so the boilerplate detection this function exists for is
# untouched. Only the position test changed.
#
# Two conditions, because either alone is too weak:
#   * nothing but whitespace, numbering or bullet punctuation precedes the
#     match on its line -- "1. TERMS AND CONDITIONS" and "- Indemnity" are
#     headings, "...our standard limited warranty..." is not;
#   * the line is short. A long line starting with the keyword is a sentence
#     ("Limited warranty does not extend to parts supplied by others, and
#     Company shall...").
_MAX_HEADING_LINE_CHARS = 60

# What may sit between the start of the line and the heading word: indentation
# and bullets, then at most ONE enumerator closed by "." or ")".
#
# The enumerator alternative has to admit letters, because real contracts number
# clauses "(a)" and "iv." as readily as "1.". Letters are why it is bounded to
# four characters AND required to be followed by "." or ")": without both, the
# leading words of an ordinary sentence would qualify as an enumerator and every
# prose match would be treated as a heading again -- the exact bug this replaces.
# "This proposal carries our standard limited warranty..." fails because "This"
# is followed by a space, not a closer.
_HEADING_PREFIX_RE = re.compile(r"[\s\-–—#*•]*(?:\(?\w{1,4}[.)]\s*)?\Z")


def _boilerplate_cut(source: str) -> int | None:
    """Offset where vendor boilerplate begins, or None if it never clearly does.

    Returns the start of the HEADING'S LINE, so the heading itself is dropped
    along with the terms beneath it.

    Scans every match rather than only the first: an early keyword used in prose
    must not stop a genuine heading further down from being found.
    """
    for match in _BOILERPLATE_HEADING_RE.finditer(source):
        line_start = source.rfind("\n", 0, match.start()) + 1
        line_end = source.find("\n", match.start())
        if line_end == -1:
            line_end = len(source)
        if not _HEADING_PREFIX_RE.match(source, line_start, match.start()):
            continue
        if len(source[line_start:line_end].strip()) > _MAX_HEADING_LINE_CHARS:
            continue
        if match.start() < _MIN_SCOPE_CHARS:
            proposal = source[:line_start]
            if not (
                _SHORT_PROPOSAL_SCOPE_RE.search(proposal)
                and _SHORT_PROPOSAL_TOTAL_RE.search(proposal)
            ):
                continue
        return line_start
    return None


def scope_region(text: object) -> str:
    """The proposal, with trailing vendor boilerplate removed.

    Routing reads what the vendor is selling. Terms and conditions describe what
    happens if it goes wrong, in language that reuses every keyword the routing
    rules depend on, so leaving them in lets the boilerplate outvote the scope.

    Conservative in every direction. The original is returned unchanged when no
    heading is found, when one appears too early to be trailing boilerplate, or
    when the keyword occurs inside prose rather than as a section heading. A
    document with no line breaks at all therefore never gets cut -- returning too
    much text is a wrong-but-visible answer, while cutting real scope produces a
    confident answer from a partial proposal.

    Used ONLY by infer_purchase_route. It is deliberately not applied to the
    analyzer prompt -- see the notes for 2026-08-14, which record that as an
    untested question rather than a decision.
    """
    source = str(text or "")
    cut = _boilerplate_cut(source)
    return source if cut is None else source[:cut]


# A labour word used as a NOUN MODIFIER names a product, not vendor work:
# "valve repair kits", "service parts", "installation hardware". Measured
# against a corpus of realistic quotes, these were the only false onsite_labor
# results, and both sent a materials purchase to 5511-SUBCONTRACTOR.
_LABOR_AS_PRODUCT_RE = re.compile(
    r"\b(?:install(?:ation)?|repair|service|maintenance)\s+"
    r"(?:kit|kits|part|parts|component|components|hardware|material|materials|"
    r"manual|manuals|contract|agreement)\b"
)

def _labor_signal(source: str) -> bool:
    """Whether the vendor is affirmatively providing onsite labour.

    Product phrases are removed first, so "repair kits" cannot read as repair
    work. Negation remains clause-local: "installation by others" must suppress
    that installation occurrence without cancelling affirmative startup or
    technician labor sold in another clause of the same quote.

    The product phrases are replaced with a SPACE, not deleted. Deleting them
    would splice the surrounding words together and manufacture matches that
    the text never contained.
    """
    return _has_affirmative_match(_LABOR_AS_PRODUCT_RE.sub(" ", source), _LABOR_RE)


def _has_affirmative_match(source: str, pattern: re.Pattern[str]) -> bool:
    """Return true when a routing term is not locally negated.

    Quotes frequently list phrases such as ``installation excluded`` and
    ``rental by others``.  Looking only for the noun sends those purchases to
    the wrong account.  Examine a short window around every match and accept
    the route when at least one occurrence is affirmative.

    ANY affirmative occurrence wins. A quote that excludes installation in one
    line and sells labour in another is still a labour purchase, so the search
    cannot stop at the first negated hit.
    """
    for match in pattern.finditer(source):
        # 48 characters is roughly one clause. It is short ON PURPOSE: it cannot
        # reach across a sentence boundary. Widening it would let a negation in
        # a neighbouring sentence cancel an unrelated affirmative clause.
        before = source[max(0, match.start() - 48) : match.start()]
        after = source[match.end() : min(len(source), match.end() + 48)]
        # Trim to the clause actually containing the match. "but"/"however"
        # terminate the trailing clause because they reverse it: in "excluded,
        # however labor is included" the exclusion belongs to the other half.
        before_clause = re.split(r"[.;:\n]", before)[-1]
        after_clause = re.split(r"[.;:\n]|\bbut\b|\bhowever\b", after)[0]
        if not _NEGATION_BEFORE_RE.search(
            before_clause
        ) and not _NEGATION_AFTER_RE.search(after_clause):
            return True
    return False


def infer_purchase_route(text: object) -> str:
    """Make a reviewable fallback guess when the analyzer has no route value.

    ALWAYS returns one of the four routes; there is no "unknown". web_ui uses
    it two ways and both matter:

    * as the sole decider when ``analyze_quote`` returned nothing usable (API
      failure, timeout, unparseable response);
    * as the second opinion in ``route_uncertain`` -- when it disagrees with the
      analyzer, the route selector is promoted into the visible questions panel.

    The second use is why a systematically wrong fallback is expensive even
    though it rarely decides anything: it turns correct confident answers into
    nags and degrades the disagreement signal to noise.

    The order of the tests IS the policy, straight from the approved matrix:
    labour and rental take priority over what is being bought, so a rental
    chiller is a rental even though "chiller" is a Group A item. Reordering
    these four lines silently re-implements the superseded delivery-method
    logic.
    """
    # Lower-cased and whitespace-collapsed once, here, because every pattern
    # below is case-sensitive and several span a word gap that a line break in
    # OCR output would otherwise break.
    source = " ".join(scope_region(text).lower().split())
    if _has_affirmative_match(source, _RENTAL_RE):
        return ONSITE_RENTAL
    if _labor_signal(source):
        return ONSITE_LABOR
    # equipment_policy already distinguishes loose parts from a complete Group
    # A unit and deliberately preserves a complete unit in mixed purchases.
    # A second document-wide "parts" veto here would discard that distinction.
    if group_a_equipment_match(source):
        return EQUIPMENT_PURCHASE
    return MATERIALS_PURCHASE


def normalize_asset_id(value: object) -> str:
    """Return the complete configured Asset ID, preserving every prefix.

    An earlier review referenced a five-digit JDE code, but the account team does not have
    a verified mapping for it. The product owner explicitly directed the tool
    to continue exporting the full asset codes already configured for every
    site. Keep the historical function name for compatibility with callers.

    Returns "" for every "no asset chosen" spelling, which is what makes the
    Smartsheet Asset ID cell blank rather than carrying prompt text. This is a
    SIGNIFICANT reversal: do not reintroduce five-digit truncation without a
    documented instruction and a verified mapping.
    """
    text = str(value or "").strip()
    if (
        not text
        # These four spellings are duplicated from other modules and nothing
        # links them: "None Applicable" is written by web_ui.ASSET_NONE and by
        # po_context._asset_value, and the prefix below is the start of
        # web_ui.ASSET_PLACEHOLDER. startswith rather than equality so the
        # placeholder's trailing wording can drift; the LEADING words cannot.
        # Change the placeholder's opening in web_ui and this test stops
        # matching -- the prompt string itself is then exported as the Asset ID,
        # with no error at any layer.
        or text.casefold() in {"none applicable", "n/a", "na"}
        or text.startswith("— Choose an asset")
    ):
        return ""
    # Internal whitespace collapsed so the same asset never produces two
    # different context IDs because of a double space.
    return " ".join(text.split())


def asset_id_is_numeric(value: object) -> bool:
    """Compatibility helper: configured full asset codes are valid text IDs.

    NOT CALLED ANYWHERE -- neither app code nor tests. It survives from the
    era when the Asset ID was expected to be a five-digit JDE number; the name
    is now actively misleading, since it returns True for "EEA-CWP-07" and for
    "". Kept because removal is a separate verified phase.

    The 160 is the same cell limit build_po_context warns on, duplicated rather
    than shared.
    """
    return len(normalize_asset_id(value)) <= 160
