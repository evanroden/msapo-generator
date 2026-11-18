"""Strict, bounded source-page facts; independent of model and UI availability.

New AI facts bind to immutable source bytes and to the exact extracted page
revision. Older human/pasted facts remain readable without implicit migration.
"""
from __future__ import annotations

from hashlib import sha256
import re


_NEGATION = re.compile(
    r"\b(?:not|no|never|without|unable|failed|didn['’]t|wasn['’]t|hasn['’]t|"
    r"couldn['’]t|wouldn['’]t|cannot|can't)\b", re.I
)
_PLANNED = re.compile(
    r"\b(?:scheduled|pending|planned|proposed|recommended|awaiting|anticipated)\b", re.I
)
_APPROX = re.compile(
    r"\b(?:about|approx\.?|approximately|roughly|estimated|around|"
    r"at least|at most|up to|more than|less than|between)\b|~(?=\s*\d)", re.I
)
_MONTH_NAMES = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", re.I
)
_UNITS = (
    "psig", "psia", "psi", "gpm", "cfm", "fpm", "rpm", "kwh", "mwh", "kw", "mw",
    "btu", "btuh", "mbh", "tons", "ton", "ppm", "pct", "kva", "kvah",
    "vac", "vdc", "amps", "amp", "kvar", "sqft", "gal", "lbs",
    "mm", "cm", "ft", "lb", "hz", "hp", "hr", "hrs", "min", "mins", "v", "w",
    "%", "°f", "°c",
)
_UNIT_RE = re.compile(
    r"(?<![\w.])([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*("
    + "|".join(re.escape(u) for u in _UNITS)
    + r")(?![\w])", re.I
)


def page_digest(page_text: str) -> str:
    return sha256(page_text.encode("utf-8")).hexdigest()


def verify_claim_qualifiers(text: str, quote: str) -> None:
    """Prevent a concise reader summary from changing source epistemic status."""
    if _NEGATION.search(quote) and not _NEGATION.search(text):
        raise ValueError("A suggested fact lost source negation; no facts were accepted.")
    if _PLANNED.search(quote) and not _PLANNED.search(text):
        raise ValueError("A suggested fact lost scheduled/pending source status; no facts were accepted.")
    if _APPROX.search(quote) and re.search(r"\d", text) and not _APPROX.search(text):
        raise ValueError("A suggested fact lost an approximate source quantity; no facts were accepted.")
    # A summary may omit dates held in the date field, but it may not
    # introduce a different month or year absent from its exact quote.
    stated_months = {m[:3].lower() for m in _MONTH_NAMES.findall(text)}
    cited_months = {m[:3].lower() for m in _MONTH_NAMES.findall(quote)}
    stated_years = set(re.findall(r"\b(?:19|20)\d{2}\b", text))
    cited_years = set(re.findall(r"\b(?:19|20)\d{2}\b", quote))
    if stated_months - cited_months or stated_years - cited_years:
        raise ValueError("A suggested fact changed a source date qualifier; no facts were accepted.")
    quote_units = {(n.replace(",", ""), u.casefold()) for n, u in _UNIT_RE.findall(quote)}
    text_units = {(n.replace(",", ""), u.casefold()) for n, u in _UNIT_RE.findall(text)}
    for _, unit in text_units - quote_units:
        # Preserve an already cited unit when the source expressed its number
        # in words ("five point two psi" -> "5.2psi"). Quantity equivalence
        # itself is separately enforced by normalize_facts.numbers().
        if not re.search(r"(?<![a-z])" + re.escape(unit) + r"(?![a-z])", quote, re.I):
            raise ValueError("A suggested fact changed a source engineering unit; no facts were accepted.")
    for amount, _unit in quote_units:
        if re.search(r"(?<![\d.])" + re.escape(amount) + r"(?![\d.])", text) and not any(
            n == amount for n, _ in text_units
        ):
            raise ValueError("A suggested fact omitted a source engineering unit; no facts were accepted.")


# A model may cite a real, accurately quoted inspection yet fabricate a repair
# in its final prose. These completion assertions require the same affirmative
# action in at least one cited fact AND its own source excerpt.
_COMPLETED_ASSERTIONS = (
    re.compile(r"\breplaced\b", re.I),
    re.compile(r"\brepaired\b", re.I),
    re.compile(r"\bcompleted\b", re.I),
    re.compile(r"\bresolved\b", re.I),
    re.compile(r"\binstalled\b", re.I),
    re.compile(r"\brestored\b", re.I),
    re.compile(r"\bcommissioned\b", re.I),
)


def _asserted_without_negation(text: str, assertion) -> bool:
    # Only positive assertions need completed-work proof. A linked negative
    # outcome ("no repair was completed") must not be converted to success or
    # rejected merely because the verb "completed" occurs in that sentence.
    for match in assertion.finditer(text):
        clause = re.split(r"[.;,\n]", text[:match.start()])[-1]
        if not _NEGATION.search(clause):
            return True
    return False


def verify_draft_outcomes(text: str, facts) -> None:
    for assertion in _COMPLETED_ASSERTIONS:
        if not _asserted_without_negation(text, assertion):
            continue
        if not any(
            _asserted_without_negation(fact.text, assertion)
            and _asserted_without_negation(fact.quote, assertion)
            and not _PLANNED.search(fact.quote)
            for fact in facts
        ):
            raise ValueError(
                "A draft asserted unsupported completed work or resolution; "
                "the cited quotation does not confirm that outcome."
            )


def anchored_fact_problem(fact, source, *, allow_legacy: bool = True) -> str:
    """Return a concrete reason, not approval. Never mutate existing facts."""
    if source is None or source.id != fact.source_id:
        return "A cited fact has the wrong source identity."
    if type(fact.page) is not int or not 1 <= fact.page <= len(source.page_texts):
        return "A cited fact has no valid source page."
    if fact.source_sha256 and fact.source_sha256 != source.sha256:
        return "A cited fact's original source SHA-256 changed."
    native = source.page_texts[fact.page - 1]
    if fact.page_sha256 and fact.page_sha256 != page_digest(native):
        return "A cited fact's source page text changed since it was read."
    if not fact.quote.strip():
        return "A cited fact has no source quotation."
    if fact.source_sha256 or fact.page_sha256:
        if fact.quote not in native:
            return "A cited fact's exact source page quotation changed."
    elif allow_legacy:
        # Legacy human/Copilot facts have no immutable anchor. The caller's
        # historical quote check remains in force; never silently add anchors.
        value = " ".join(native.split()).casefold()
        quote = " ".join(fact.quote.split()).casefold()
        if quote not in value:
            return "A legacy cited fact's source quotation changed."
    return ""
