"""Validation and normalization for Claude quote-analysis JSON.

The model is prompted for a fixed JSON shape, but network success does not mean
the response is usable. This module separates JSON extraction and field-type
validation from the business post-processing in ``quote_analyzer.py``.

THE GOVERNING PRINCIPLE, and it is not obvious: this module raises only for
damage it cannot contain, and degrades everything else. A malformed TYPE (a list
where text belongs) raises, because nothing downstream can recover. An
unrecognised ENUM VALUE degrades to None or to the conservative bucket, because
the UI already has a deterministic fallback for each one and hard-failing threw
away a complete, usable extraction over a cosmetic deviation -- the operator saw
"The quote could not be analyzed" and got nothing at all for a response that
merely said "onsite labor" instead of "onsite_labor".

So: when you add a field, decide which of those two it is, and say why here.

The enum sets below are COPIES of definitions that live elsewhere --
config.WORK_CATEGORY_SUFFIXES and po_rules.PURCHASE_ROUTES. A drifted copy fails
in the damaging direction and in silence: a category added to config alone is
not in this set, so the model's correct answer for it degrades to None and the
operator sees an unset dropdown with no error. tests/test_analysis_schema.py
pins the copies against their sources for exactly that reason.
"""

from __future__ import annotations

import json
from typing import Any


class AnalysisResponseError(ValueError):
    """Raised when the model response cannot safely populate QuoteAnalysis."""


_ALLOWED_TAX_STATUSES = {"included", "excluded", "unclear"}
_ALLOWED_WORK_CATEGORIES = {
    "chemical_treatment",
    "building_automation",
    "electrical_pm",
    "preventive_maintenance",
    "repairs",
    "repair_cap",
    "steam_trap",
    "water_softener",
}
_ALLOWED_ASSUMPTION_SECTIONS = {"inclusion", "exclusion", "scope"}
_ALLOWED_PURCHASE_ROUTES = {
    "onsite_labor",
    "onsite_rental",
    "equipment_purchase",
    "materials_purchase",
}
_ALLOWED_REQUEST_TYPES = {"PO", "CHANGE ORDER"}

_STRING_FIELDS = {
    "vendor_name",
    "project_description",
    "scope_of_work",
}
_OPTIONAL_STRING_FIELDS = {
    "facility_name",
    "facility_address",
    "tax_warning",
    "tax_note",
    "contact_name",
    "contact_email",
    "subtotal_amount",
    "tax_amount",
    "total_amount",
    "short_description",
    "work_category",
    "asset_reference",
    "purchase_route_guess",
    "request_type_guess",
    "original_po_number",
}
_LIST_FIELDS = {"inclusions", "exclusions"}


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Extract exactly one JSON object, tolerating a Markdown code fence."""
    if not isinstance(raw, str) or not raw.strip():
        raise AnalysisResponseError("Claude returned an empty analysis response.")

    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline == -1:
            raise AnalysisResponseError("Claude returned an incomplete JSON code block.")
        text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()

    start = text.find("{")
    if start == -1:
        raise AnalysisResponseError("Claude did not return a JSON object.")

    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise AnalysisResponseError(
            f"Claude returned malformed JSON near character {exc.pos}."
        ) from exc

    # ``raw_decode`` already captured one complete object. Models commonly add
    # a closing code fence or short remark; neither invalidates that object.
    if not isinstance(value, dict):
        raise AnalysisResponseError("Claude's analysis response was not a JSON object.")
    return value


def _string(value: Any, field: str, *, optional: bool) -> str | None:
    """Normalize one text field. Returns None only for an OPTIONAL empty value.

    The asymmetry is deliberate and load-bearing for the UI: a required field
    empties to "" while an optional one becomes None. web_ui distinguishes those
    two -- "" is a value the operator must fill (it drives the "Needed from you"
    banner and the highlight), while None means the field does not apply. Making
    both None would hide required-but-missing fields instead of flagging them.

    A non-string RAISES rather than being coerced with str(). A model returning
    {"vendor_name": {"name": "Trane"}} would otherwise stringify to
    "{'name': 'Trane'}" and print that onto the MSAPO form.
    """
    if value is None and optional:
        return None
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AnalysisResponseError(f"Field '{field}' must be text or null.")
    cleaned = value.strip()
    return cleaned or (None if optional else "")


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AnalysisResponseError(f"Field '{field}' must be a list of text items.")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise AnalysisResponseError(
                f"Field '{field}' item {index + 1} must be text."
            )
        cleaned = item.strip()
        if cleaned:
            result.append(cleaned)
    return result


def _assumption_section(value: Any) -> str:
    """Map a model-supplied assumption section onto a section the UI renders.

    Matching on the stem rather than the exact token matters for correctness,
    not just tolerance. These strings are rendered verbatim as bullets on the
    Scope/Inclusions/Exclusions PDF attached to the purchase order, so coercing
    an unrecognized value straight to "exclusion" inverts the meaning of a model
    answer like "included" or "inclusions" — the attachment would then tell the
    vendor they are excluding work the model meant to include.

    "inclu*" covers inclusion/included/including; "exclu*" covers the exclusion
    forms; anything genuinely unrecognizable still falls back to "exclusion",
    which is the conservative bucket because an over-stated exclusion is visible
    to the reviewer while a silently dropped one is not.
    """
    text = value.strip().lower() if isinstance(value, str) else ""
    if text.startswith("inclu"):
        return "inclusion"
    if text.startswith("exclu"):
        return "exclusion"
    if text.startswith("scope"):
        return "scope"
    return text if text in _ALLOWED_ASSUMPTION_SECTIONS else "exclusion"


def _assumptions(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AnalysisResponseError("Field 'ai_assumptions' must be a list.")

    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        # Retain compatibility with older responses that returned bare strings.
        if isinstance(item, str):
            text = item.strip()
            if text:
                result.append({"text": text, "section": "exclusion"})
            continue
        if not isinstance(item, dict):
            raise AnalysisResponseError(
                f"AI assumption {index + 1} must be an object with text and section."
            )
        text = item.get("text")
        section = item.get("section", "exclusion")
        if not isinstance(text, str) or not text.strip():
            raise AnalysisResponseError(
                f"AI assumption {index + 1} is missing usable text."
            )
        result.append({"text": text.strip(), "section": _assumption_section(section)})
    return result


def normalize_analysis_response(raw: str) -> dict[str, Any]:
    """Parse and validate the model response into the QuoteAnalysis field shape."""
    source = _extract_json_object(raw)
    normalized: dict[str, Any] = {}

    for field in _STRING_FIELDS:
        normalized[field] = _string(source.get(field), field, optional=False)
    for field in _OPTIONAL_STRING_FIELDS:
        normalized[field] = _string(source.get(field), field, optional=True)
    for field in _LIST_FIELDS:
        normalized[field] = _string_list(source.get(field), field)

    raw_tax = source.get("tax_status", "unclear")
    tax_status = raw_tax.strip().lower() if isinstance(raw_tax, str) else ""
    # ``unclear`` triggers the visible tax alert, so an unsupported hint safely
    # degrades to human review instead of discarding the complete extraction.
    normalized["tax_status"] = (
        tax_status if tax_status in _ALLOWED_TAX_STATUSES else "unclear"
    )

    # This is only a UI default. The site-specific control already falls back
    # when the model does not return one of its configured categories.
    work_category = normalized.get("work_category")
    if work_category is not None:
        candidate = work_category.strip().lower().replace(" ", "_")
        normalized["work_category"] = (
            candidate if candidate in _ALLOWED_WORK_CATEGORIES else None
        )

    # Hard 20-character truncation, because this becomes a JDE cost-code
    # description and the field will not accept more. It can cut mid-word, which
    # is accepted: the operator sees and can edit the value (web_ui renders it
    # with max_chars=20), so a clipped label is visible rather than silent, and
    # rejecting the whole response over a long label would discard everything.
    short_description = normalized.get("short_description")
    if short_description:
        normalized["short_description"] = short_description[:20]

    # Both remaining enums are *guesses* with deterministic fallbacks in the UI
    # (web_ui re-derives the route via infer_purchase_route, and an absent
    # request type defaults to PO). Hard-failing the response therefore threw
    # away a complete, usable extraction over a cosmetic deviation such as
    # "onsite labor" for "onsite_labor" — the operator saw "The quote could not
    # be analyzed" and got nothing. Degrade to None and let the UI decide, the
    # same way tax_status and work_category already do.
    purchase_route = normalized.get("purchase_route_guess")
    if purchase_route is not None:
        candidate = purchase_route.strip().lower().replace(" ", "_").replace("-", "_")
        normalized["purchase_route_guess"] = (
            candidate if candidate in _ALLOWED_PURCHASE_ROUTES else None
        )

    request_type = normalized.get("request_type_guess")
    if request_type is not None:
        candidate = " ".join(request_type.strip().upper().split())
        request_type = candidate if candidate in _ALLOWED_REQUEST_TYPES else None
        normalized["request_type_guess"] = request_type
    # Unchanged safety property: original_po_number survives ONLY for a
    # confirmed CHANGE ORDER. Because an unrecognized guess now degrades to
    # None rather than raising, it lands here as "not a change order" and the
    # PO number is still cleared — the conservative direction.
    if request_type != "CHANGE ORDER":
        normalized["original_po_number"] = None

    normalized["ai_assumptions"] = _assumptions(source.get("ai_assumptions"))
    return normalized
