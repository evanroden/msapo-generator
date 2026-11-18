"""Provider-gated JSON schemas and portable validation for Monthly AI chunks.

JSON schema constrains syntax, never proves source truth; the existing
normalize_facts/normalize_draft validators remain mandatory before acceptance.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import json

from app.analysis_schema import _extract_json_object

from app.ai_client import foundry_settings

# Tested SDK + known direct Claude model only. Foundry deployment names can
# point at independently configured API/model versions; use portable validation.
_SCHEMA_SDK = "0.122.0"
_SCHEMA_DIRECT_MODELS = frozenset({"claude-sonnet-4-6"})

_FACT_PROPERTIES = {
    "page": {"type": "integer"},
    "kind": {"type": "string", "enum": [
        "action", "finding", "recommendation", "follow_up", "reading",
        "proposal", "training", "improvement", "issue",
    ]},
    "text": {"type": "string"},
    "quote": {"type": "string"},
    "date": {"type": "string"},
    "facility": {"type": "string"},
    "vendor": {"type": "string"},
    "tags": {"type": "array", "items": {"type": "string"}},
    "status": {"type": "string", "enum": ["", "ongoing", "updated", "resolved"]},
    "uncertain": {"type": "boolean"},
}
_PARAGRAPH_PROPERTIES = {
    "text": {"type": "string"},
    "fact_ids": {"type": "array", "items": {"type": "string"}},
    "uncertain": {"type": "boolean"},
}
_PROPERTIES = {"facts": _FACT_PROPERTIES, "paragraphs": _PARAGRAPH_PROPERTIES}
_REQUIRED = {
    "facts": frozenset({"page", "kind", "text", "quote"}),
    "paragraphs": frozenset({"text", "fact_ids"}),
}
_LIMITS = {"facts": 100, "paragraphs": 60}


class InvalidReaderShape(ValueError):
    """The response contains extra, incomplete or ill-typed fields."""


def extract_single_json(raw: str) -> dict:
    """Recover fenced JSON and harmless commentary, but reject sibling payloads.

    The shared PO analyzer deliberately tolerates a short trailing remark. For
    page/fact chunks a second valid object could contain useful facts, so
    accepting only the first object would silently lose evidence.
    """
    value = _extract_json_object(raw)
    text = raw.strip()
    if text.startswith("```"):
        text = text[text.index("\n") + 1:]
    start = text.find("{")
    _, end = json.JSONDecoder().raw_decode(text[start:])
    tail = text[start + end:]
    # Markdown fences and a human-readable remark are harmless. A second
    # complete JSON value is not: re-ask for a single consolidated object.
    decoder = json.JSONDecoder()
    for index, character in enumerate(tail):
        if character not in "{[":
            continue
        try:
            sibling, _ = decoder.raw_decode(tail[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(sibling, (dict, list)):
            raise InvalidReaderShape(
                "Reader returned multiple JSON payloads; useful facts may be omitted."
            )
    return value


def output_schema(kind: str | None, model: str) -> dict | None:
    """Enable the schema only on this verified SDK/direct API combination."""
    if kind is None:
        return None
    if kind not in _PROPERTIES:
        raise ValueError("Unsupported document-reader response kind.")
    try:
        sdk_compatible = version("anthropic") == _SCHEMA_SDK
    except PackageNotFoundError:
        sdk_compatible = False
    if foundry_settings() is not None or model not in _SCHEMA_DIRECT_MODELS or not sdk_compatible:
        return None
    properties = _PROPERTIES[kind]
    item = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {kind: {"type": "array", "items": item}},
            "required": [kind],
            "additionalProperties": False,
        },
    }


def validate_shape(value: dict, kind: str | None) -> None:
    """Portable, non-dropping shape checks even on unsupported deployments.

    Older valid responses omit optional fields; that is safe because the
    normalizers use explicit defaults and require grounded fields. Structural
    exceptions are always visible, never silently discarded.
    """
    if kind is None:
        return
    if kind not in _PROPERTIES:
        raise ValueError("Unsupported document-reader response kind.")
    if type(value) is not dict or set(value) != {kind}:
        raise InvalidReaderShape("Reader response has unexpected or missing root fields.")
    items = value[kind]
    if type(items) is not list or len(items) > _LIMITS[kind]:
        raise InvalidReaderShape("Reader response has an invalid item list.")
    allowed = _PROPERTIES[kind]
    required = _REQUIRED[kind]
    for item in items:
        if type(item) is not dict or not required.issubset(item) or set(item) - set(allowed):
            raise InvalidReaderShape("Reader response has missing or invented item fields.")
        for key, entry in item.items():
            typ = allowed[key]["type"]
            if (typ == "integer" and type(entry) is not int
                or typ == "boolean" and type(entry) is not bool
                or typ == "string" and type(entry) is not str
                or typ == "array" and (
                    type(entry) is not list
                    or any(type(element) is not str for element in entry)
                )):
                raise InvalidReaderShape("Reader response has a wrong field type.")
            if "enum" in allowed[key] and entry not in allowed[key]["enum"]:
                raise InvalidReaderShape("Reader response has an unsupported enum value.")
