"""Disposable, versioned source-parse inventory; no reviewed report decisions.

Every manifest is stored under a *profile-scoped* digest-derived filename.
Its inventory is regenerated from parsed data rather than trusting cache JSON.
A version change invalidates derived extraction, not the immutable original,
saved report, manual corrections, approved pins or other sites' metadata.
"""
from __future__ import annotations

from hashlib import sha256
import json

PARSER_POLICY_VERSION = 1
STAGE_POLICY_VERSION = 1


def _digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def make(content, source_size: int) -> dict:
    """Inventory of pages, structured tables, assets, provenance and warnings.

    Do not copy report-level reviewed fields into the identity: those belong to
    the saved draft. Cached extraction includes initial suggestions only.
    """
    source = content.source
    return {
        "parser_policy": PARSER_POLICY_VERSION,
        "source_revision": source.sha256,
        "source_sha256": source.sha256,
        "source_size": source_size,
        "source_suffix": source.suffix,
        "provenance": {"source_id": source.id, "type": source.suffix},
        "page_items": [
            {"number": number, "text_sha256": sha256(text.encode("utf-8")).hexdigest(),
             "needs_vision": number in source.needs_vision}
            for number, text in enumerate(source.page_texts, 1)
        ],
        "tables": [
            {"name": table.name, "rows": len(table.rows),
             "columns": len(table.columns),
             "cells_sha256": _digest([table.columns, table.rows])}
            for table in content.tables
        ],
        "assets": [[number, identifier] for number, identifier in content.image_items],
        "warnings_sha256": _digest(source.notices),
        "passages_sha256": _digest(source.pdf_text_blocks),
        # Page selection/captions are editable review decisions, not immutable
        # parser identity. Legacy review recovery may update them in place.
    }


def valid(manifest, content, source_size: int) -> bool:
    """Strictly reject stale/malformed current manifests; legacy has no key."""
    if not isinstance(manifest, dict):
        return False
    try:
        return manifest == make(content, source_size)
    except (ValueError, TypeError, OverflowError, UnicodeError):
        return False


def stage_record(content) -> dict:
    """Completed expensive parse, before suggested facts, in a bounded JSON file."""
    from dataclasses import asdict
    record = {"schema": 1, "stage_policy": STAGE_POLICY_VERSION,
              "source_sha256": content.source.sha256,
              "source_suffix": content.source.suffix,
              "source": asdict(content.source),
              "tables": [asdict(table) for table in content.tables],
              "image_items": list(content.image_items)}
    record["payload_sha256"] = _digest({k: v for k, v in record.items() if k != "payload_sha256"})
    return record


def stage_valid(record, digest: str, suffix: str) -> bool:
    if not isinstance(record, dict):
        return False
    if (type(record.get("stage_policy")) is not int
            or record["stage_policy"] != STAGE_POLICY_VERSION
            or record.get("source_sha256") != digest
            or record.get("source_suffix") != suffix):
        return False
    actual = record.get("payload_sha256")
    if not isinstance(actual, str) or len(actual) != 64:
        return False
    try:
        return actual == _digest({k: v for k, v in record.items() if k != "payload_sha256"})
    except (ValueError, TypeError, OverflowError, UnicodeError):
        return False
