"""
Smartsheet PO-submission integration — OFF by default.

ENFRA is rolling out a Smartsheet form for PO submissions.  That form means
re-typing, by hand, everything Email Process Control already knows — and it
can't carry the quote attachment at all.  This module skips the form and pushes
a fully-populated row (plus the quote and MSAPO files) straight onto the PO
sheet through the Smartsheet API v2.

It is completely INERT until both of these are set (typically on Render):

    SMARTSHEET_API_TOKEN   a Smartsheet API access token (use a service account)
    SMARTSHEET_SHEET_ID    the numeric ID of the destination PO sheet

With either unset, ``is_enabled()`` returns False, the UI never shows the
Smartsheet button, and nothing here ever runs — so the scaffold ships safely
disabled and goes live the moment those two values exist in the dashboard, with
no code change.

Column mapping is done LIVE against the sheet's real column titles (fetched via
the API) using a set of aliases per logical field, so the integration keeps
working even when the sheet's exact column names differ slightly from ours.
Any field with no matching column is simply skipped and reported back, never
fatal.
"""

from __future__ import annotations

import mimetypes
import os
import re

import requests

BASE_URL = "https://api.smartsheet.com/2.0"
_TIMEOUT = 60

# Logical field  ->  candidate column titles on the sheet (case/space-insensitive).
# The first column whose normalized title matches one of these aliases wins.
FIELD_ALIASES: dict[str, list[str]] = {
    "contract": ["contract", "contract name", "customer", "client", "account"],
    "site": ["site", "site location", "location", "facility", "building"],
    "asset_id": ["asset id", "applicable asset id", "asset", "unique identifier",
                 "equipment id", "asset tag"],
    "cost_code": ["cost code", "job cost code", "gl code", "cost center", "gl"],
    "work_category": ["work category", "category", "trade", "scope of work", "scope"],
    "vendor": ["vendor", "subcontractor", "subcontractor name", "supplier",
               "vendor name", "contractor"],
    "contact_name": ["contact name", "vendor contact", "contact", "rep"],
    "contact_email": ["contact email", "vendor email", "email", "rep email"],
    "description": ["description", "short description", "work description",
                    "summary", "po description", "notes"],
    "subtotal": ["subtotal", "subtotal (pre-tax)", "pre-tax", "pre-tax amount"],
    "tax": ["sales tax", "tax", "tax amount"],
    "total": ["total", "total amount", "amount", "po amount", "cost", "value"],
    "administrator_email": ["administrator email", "administrator", "admin email",
                            "contract administrator", "submitted to"],
}

# Fields whose values are money and should be sent numeric so a currency/number
# column parses them ("$4,546.50" -> 4546.50).
_AMOUNT_FIELDS = {"subtotal", "tax", "total"}


# ── Configuration ────────────────────────────────────────────────────
def _api_token() -> str | None:
    tok = os.environ.get("SMARTSHEET_API_TOKEN", "").strip()
    return tok or None


def _sheet_id() -> str | None:
    sid = os.environ.get("SMARTSHEET_SHEET_ID", "").strip()
    return sid or None


def is_enabled() -> bool:
    """True only when both the token and the sheet ID are configured."""
    return bool(_api_token() and _sheet_id())


def _headers(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {_api_token()}"}
    if extra:
        h.update(extra)
    return h


# ── Column matching ──────────────────────────────────────────────────
def _norm(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for fuzzy title match."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (title or "").lower())).strip()


def get_columns() -> list[dict]:
    """Live column list for the configured sheet: [{id, title, type}, ...]."""
    url = f"{BASE_URL}/sheets/{_sheet_id()}/columns?includeAll=true"
    r = requests.get(url, headers=_headers(), timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json().get("data", [])


def _map_columns(columns: list[dict]) -> dict[str, dict]:
    """logical field -> the sheet column dict it maps to.

    Prefers an exact normalized-title match against an alias; falls back to a
    substring match.  Each column is claimed by at most one field.
    """
    by_norm = {_norm(c["title"]): c for c in columns}
    used: set[int] = set()
    mapping: dict[str, dict] = {}
    # Pass 1 — exact alias match.
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            col = by_norm.get(_norm(alias))
            if col and col["id"] not in used:
                mapping[field] = col
                used.add(col["id"])
                break
    # Pass 2 — substring match for anything still unmapped.
    for field, aliases in FIELD_ALIASES.items():
        if field in mapping:
            continue
        norm_aliases = [_norm(a) for a in aliases]
        for norm_title, col in by_norm.items():
            if col["id"] in used:
                continue
            if any(a and (a in norm_title or norm_title in a) for a in norm_aliases):
                mapping[field] = col
                used.add(col["id"])
                break
    return mapping


def preview_mapping() -> dict:
    """Diagnostic used by the UI: which fields map to which columns, and which
    logical fields have no column at all. Returns {"ok", "mapped", "unmapped",
    "error"}."""
    try:
        columns = get_columns()
    except Exception as e:  # noqa: BLE001 — surface any API/network error as text
        return {"ok": False, "error": _err_text(e)}
    mapping = _map_columns(columns)
    return {
        "ok": True,
        "mapped": {f: col["title"] for f, col in mapping.items()},
        "unmapped": [f for f in FIELD_ALIASES if f not in mapping],
    }


# ── Submission ───────────────────────────────────────────────────────
def _clean_amount(value: str):
    """'$4,546.50' -> 4546.50 (float) so numeric columns accept it; returns the
    original string if it isn't parseable as a number."""
    if value is None:
        return None
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value))
    if not m:
        return str(value)
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return str(value)


def _create_row(cells: list[dict]) -> dict:
    url = f"{BASE_URL}/sheets/{_sheet_id()}/rows"
    body = [{"toTop": True, "cells": cells}]
    r = requests.post(url, headers=_headers({"Content-Type": "application/json"}),
                      json=body, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()["result"][0]


def _attach_file(row_id, filename: str, data: bytes) -> None:
    # Smartsheet's current API expects multipart/form-data for row attachments
    # (the older raw-body "simple upload" is deprecated). requests builds the
    # multipart envelope — including the boundary and per-part Content-Type —
    # from the ``files`` mapping, so we must NOT set Content-Type ourselves.
    # Limits per the docs: 30 MB per file, 30 attach requests/min per token.
    url = f"{BASE_URL}/sheets/{_sheet_id()}/rows/{row_id}/attachments"
    mime, _ = mimetypes.guess_type(filename)
    files = {"file": (filename, data, mime or "application/octet-stream")}
    r = requests.post(url, headers=_headers(), files=files, timeout=_TIMEOUT)
    r.raise_for_status()


def submit_po(fields: dict, attachments: list[tuple[str, bytes]] | None = None) -> dict:
    """Create a PO row and attach the quote/MSAPO files.

    Parameters
    ----------
    fields : logical field -> value (see FIELD_ALIASES for the field names).
             Empty values are skipped.
    attachments : [(filename, data), ...] attached to the new row.

    Returns a result dict — never raises — of the shape::

        {"ok": True, "row_id": 123, "attached": 2, "skipped_attachments": [],
         "unmapped": ["work_category"]}
        {"ok": False, "error": "..."}
    """
    if not is_enabled():
        return {"ok": False, "error": "Smartsheet is not configured "
                "(set SMARTSHEET_API_TOKEN and SMARTSHEET_SHEET_ID)."}
    try:
        columns = get_columns()
        mapping = _map_columns(columns)

        cells: list[dict] = []
        for field, col in mapping.items():
            raw = fields.get(field)
            if raw is None or str(raw).strip() == "":
                continue
            value = _clean_amount(raw) if field in _AMOUNT_FIELDS else str(raw)
            # strict:false lets Smartsheet coerce to the column's type (number,
            # date, contact) instead of rejecting a plain string.
            cells.append({"columnId": col["id"], "value": value, "strict": False})

        if not cells:
            return {"ok": False, "error": "No sheet columns matched the PO fields "
                    "— check the sheet's column titles."}

        row = _create_row(cells)
        row_id = row["id"]

        attached, skipped = 0, []
        for filename, data in (attachments or []):
            if not data:
                continue
            try:
                _attach_file(row_id, filename, data)
                attached += 1
            except Exception as e:  # noqa: BLE001 — one bad file shouldn't lose the row
                skipped.append(f"{filename} ({_err_text(e)})")

        # Fields we had a value for but no column to hold them.
        unmapped = [f for f, v in fields.items()
                    if str(v or "").strip() and f not in mapping]
        return {"ok": True, "row_id": row_id, "attached": attached,
                "skipped_attachments": skipped, "unmapped": unmapped}
    except Exception as e:  # noqa: BLE001 — the UI shows .get("error"), never a traceback
        return {"ok": False, "error": _err_text(e)}


def _err_text(e: Exception) -> str:
    """A concise, user-facing message from a requests/HTTP error, including the
    Smartsheet API's own message when present."""
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            j = resp.json()
            msg = j.get("message") or j.get("error", {}).get("message")
            if msg:
                return f"{msg} (HTTP {resp.status_code})"
        except Exception:  # noqa: BLE001
            pass
        return f"HTTP {resp.status_code}"
    return str(e) or e.__class__.__name__
