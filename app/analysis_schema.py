"""Validation and normalization for Claude quote-analysis JSON.

The model is prompted for a fixed JSON shape, but network success does not mean
the response is usable. This module separates JSON extraction and field-type
validation from the business post-processing in ``quote_analyzer.py``.
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

    trailing = text[start + end :].strip()
    if trailing and trailing not in {"```"}:
        raise AnalysisResponseError(
            "Claude returned extra text after the JSON object; analysis was not used."
        )
    if not isinstance(value, dict):
        raise AnalysisResponseError("Claude's analysis response was not a JSON object.")
    return value


def _string(value: Any, field: str, *, optional: bool) -> str | None:
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
        if not isinstance(section, str) or section not in _ALLOWED_ASSUMPTION_SECTIONS:
            raise AnalysisResponseError(
                f"AI assumption {index + 1} has an invalid section."
            )
        result.append({"text": text.strip(), "section": section})
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

    tax_status = source.get("tax_status", "unclear")
    if not isinstance(tax_status, str) or tax_status not in _ALLOWED_TAX_STATUSES:
        raise AnalysisResponseError(
            "Field 'tax_status' must be included, excluded, or unclear."
        )
    normalized["tax_status"] = tax_status

    work_category = normalized.get("work_category")
    if work_category is not None and work_category not in _ALLOWED_WORK_CATEGORIES:
        raise AnalysisResponseError(
            f"Field 'work_category' contains an unsupported value: {work_category!r}."
        )

    short_description = normalized.get("short_description")
    if short_description:
        normalized["short_description"] = short_description[:20]

    purchase_route = normalized.get("purchase_route_guess")
    if purchase_route is not None and purchase_route not in _ALLOWED_PURCHASE_ROUTES:
        raise AnalysisResponseError(
            "Field 'purchase_route_guess' contains an unsupported value: "
            f"{purchase_route!r}."
        )

    request_type = normalized.get("request_type_guess")
    if request_type is not None and request_type not in _ALLOWED_REQUEST_TYPES:
        raise AnalysisResponseError(
            "Field 'request_type_guess' must be PO or CHANGE ORDER."
        )
    if request_type != "CHANGE ORDER":
        normalized["original_po_number"] = None

    normalized["ai_assumptions"] = _assumptions(source.get("ai_assumptions"))
    return normalized
