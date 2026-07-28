"""Three-mode Smartsheet handoff for future ENFRA PO intake.

The final PO form and sheet are not known yet, so this integration is driven by
configuration and stays inert by default. It supports three independent paths:

1. Manual handoff: open the form, copy fields in order, and download attachments.
2. URL prefill: add exact form-field labels as encoded query parameters.
3. API submission: create one row using explicit column IDs and attach files.

The API route deliberately refuses fuzzy title matching. A wrong cost code or
amount in a plausible-looking column is more dangerous than a blocked submit.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from app.smartsheet_store import SubmissionStore, SubmissionStoreError


BASE_URL = "https://api.smartsheet.com/2.0"
REQUEST_TIMEOUT = 60
MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024

DISPLAY_LABELS: dict[str, str] = {
    "requester_name": "Name of Person Completing Form",
    "order_type": "PO Type",
    "contract": "Contract",
    "site": "Site Location",
    "facility_address": "Address/Location",
    "related_to_om": "Related to Asset Management O&M Agreement",
    "billing_method": "Billing Method",
    "customer_po": "Customer Purchase Order",
    "work_category": "Work Category",
    "cost_code": "Job Cost Code",
    "asset_id": "ENFRA Unique Identifier",
    "vendor": "Subcontractor Name",
    "contact_name": "Contact Name",
    "contact_email": "Contact Email",
    "description": "Description",
    "scope_of_work": "Description of Work or Issue Needing Repair",
    "estimated_start_date": "Estimated Start Date",
    "estimated_completion_date": "Estimated Completion Date",
    "customer_representative": "Customer Representative Requesting Service",
    "service_branch_tech_needed": "Service Branch Tech Needed For Work",
    "subtotal": "Subtotal (pre-tax)",
    "tax": "Sales Tax",
    "total": "Amount",
    "tax_status": "Tax Status",
    "administrator_email": "Administrator Email",
    "instructions": "Additional Instructions",
    "submission_key": "Email Process Control Submission Key",
    "send_copy_email": "Send Me a Copy",
}

DEFAULT_FORM_ORDER: tuple[str, ...] = (
    "requester_name",
    "contract",
    "site",
    "related_to_om",
    "billing_method",
    "customer_po",
    "vendor",
    "contact_name",
    "contact_email",
    "description",
    "scope_of_work",
    "facility_address",
    "estimated_start_date",
    "estimated_completion_date",
    "customer_representative",
    "service_branch_tech_needed",
    "asset_id",
    "work_category",
    "cost_code",
    "subtotal",
    "tax",
    "total",
    "administrator_email",
    "instructions",
)

_AMOUNT_FIELDS = {"subtotal", "tax", "total"}
_ALLOWED_API_MODES = {"disabled", "dry_run", "live"}
_ALLOWED_ROW_POSITIONS = {"top", "bottom"}


class SmartsheetConfigurationError(ValueError):
    """Raised when optional Smartsheet configuration is present but invalid."""


@dataclass(frozen=True)
class SmartsheetConfig:
    form_url: str | None
    prefill_enabled: bool
    form_field_map: dict[str, str]
    form_value_map: dict[str, dict[str, str]]
    form_order: tuple[str, ...]
    api_mode: str
    api_token: str | None
    sheet_id: str | None
    column_map: dict[str, int]
    required_fields: tuple[str, ...]
    row_position: str
    api_base_url: str


@dataclass(frozen=True)
class PrefillResult:
    url: str
    included: tuple[str, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class ApiReadiness:
    ready: bool
    mode: str
    problems: tuple[str, ...]


def _text(env: Mapping[str, str], name: str) -> str | None:
    value = str(env.get(name, "")).strip()
    return value or None


def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = _text(env, name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SmartsheetConfigurationError(f"{name} must be true or false.")


def _json_object(env: Mapping[str, str], name: str) -> dict[str, Any]:
    raw = _text(env, name)
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SmartsheetConfigurationError(
            f"{name} contains invalid JSON near character {exc.pos}."
        ) from exc
    if not isinstance(value, dict):
        raise SmartsheetConfigurationError(f"{name} must be a JSON object.")
    return value


def _csv(env: Mapping[str, str], name: str) -> tuple[str, ...]:
    raw = _text(env, name)
    if raw is None:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def load_config(env: Mapping[str, str] | None = None) -> SmartsheetConfig:
    source = os.environ if env is None else env

    field_map_raw = _json_object(source, "SMARTSHEET_FORM_FIELD_MAP_JSON")
    field_map: dict[str, str] = {}
    for logical, label in field_map_raw.items():
        if not isinstance(logical, str) or not isinstance(label, str) or not label.strip():
            raise SmartsheetConfigurationError(
                "SMARTSHEET_FORM_FIELD_MAP_JSON must map logical field names to exact form labels."
            )
        field_map[logical.strip()] = label.strip()

    value_map_raw = _json_object(source, "SMARTSHEET_FORM_VALUE_MAP_JSON")
    value_map: dict[str, dict[str, str]] = {}
    for logical, mappings in value_map_raw.items():
        if not isinstance(logical, str) or not isinstance(mappings, dict):
            raise SmartsheetConfigurationError(
                "SMARTSHEET_FORM_VALUE_MAP_JSON must map fields to value-mapping objects."
            )
        normalized: dict[str, str] = {}
        for original, replacement in mappings.items():
            if not isinstance(replacement, (str, int, float, bool)):
                raise SmartsheetConfigurationError(
                    f"SMARTSHEET_FORM_VALUE_MAP_JSON value for {logical!r} is unsupported."
                )
            normalized[str(original)] = str(replacement)
        value_map[logical] = normalized

    column_map_raw = _json_object(source, "SMARTSHEET_COLUMN_MAP_JSON")
    column_map: dict[str, int] = {}
    for logical, column_id in column_map_raw.items():
        try:
            parsed = int(column_id)
        except (TypeError, ValueError) as exc:
            raise SmartsheetConfigurationError(
                f"Smartsheet column ID for {logical!r} must be numeric."
            ) from exc
        if parsed <= 0:
            raise SmartsheetConfigurationError(
                f"Smartsheet column ID for {logical!r} must be positive."
            )
        column_map[str(logical)] = parsed

    configured_order = _csv(source, "SMARTSHEET_FORM_ORDER")
    api_mode = (_text(source, "SMARTSHEET_API_MODE") or "disabled").lower()
    if api_mode not in _ALLOWED_API_MODES:
        raise SmartsheetConfigurationError(
            "SMARTSHEET_API_MODE must be disabled, dry_run, or live."
        )
    row_position = (_text(source, "SMARTSHEET_ROW_POSITION") or "bottom").lower()
    if row_position not in _ALLOWED_ROW_POSITIONS:
        raise SmartsheetConfigurationError(
            "SMARTSHEET_ROW_POSITION must be top or bottom."
        )

    return SmartsheetConfig(
        form_url=_text(source, "SMARTSHEET_FORM_URL"),
        prefill_enabled=_bool(source, "SMARTSHEET_URL_PREFILL_ENABLED", False),
        form_field_map=field_map,
        form_value_map=value_map,
        form_order=configured_order or DEFAULT_FORM_ORDER,
        api_mode=api_mode,
        api_token=_text(source, "SMARTSHEET_API_TOKEN"),
        sheet_id=_text(source, "SMARTSHEET_SHEET_ID"),
        column_map=column_map,
        required_fields=_csv(source, "SMARTSHEET_REQUIRED_FIELDS"),
        row_position=row_position,
        api_base_url=(_text(source, "SMARTSHEET_API_BASE_URL") or BASE_URL).rstrip("/"),
    )


def manual_enabled(config: SmartsheetConfig) -> bool:
    return bool(config.form_url)


def prefill_enabled(config: SmartsheetConfig) -> bool:
    return bool(config.form_url and config.prefill_enabled and config.form_field_map)


def api_readiness(config: SmartsheetConfig) -> ApiReadiness:
    problems: list[str] = []
    if config.api_mode == "disabled":
        return ApiReadiness(False, config.api_mode, ("API mode is disabled.",))
    if not config.api_token:
        problems.append("SMARTSHEET_API_TOKEN is not configured.")
    if not config.sheet_id:
        problems.append("SMARTSHEET_SHEET_ID is not configured.")
    if not config.column_map:
        problems.append("SMARTSHEET_COLUMN_MAP_JSON has no explicit column IDs.")
    if not config.required_fields:
        problems.append("SMARTSHEET_REQUIRED_FIELDS has not been confirmed.")
    else:
        missing_required_mappings = [
            field for field in config.required_fields if field not in config.column_map
        ]
        if missing_required_mappings:
            problems.append(
                "Required fields lack column IDs: " + ", ".join(missing_required_mappings)
            )
    return ApiReadiness(not problems, config.api_mode, tuple(problems))


def _nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _mapped_form_value(config: SmartsheetConfig, field: str, value: Any) -> str:
    text = str(value).strip()
    mappings = config.form_value_map.get(field, {})
    if text in mappings:
        return mappings[text]
    lowered = text.lower()
    for source, replacement in mappings.items():
        if source.lower() == lowered:
            return replacement
    return text


def build_prefilled_form_url(
    fields: Mapping[str, Any], config: SmartsheetConfig
) -> PrefillResult:
    if not config.form_url:
        raise SmartsheetConfigurationError("SMARTSHEET_FORM_URL is not configured.")
    if not config.prefill_enabled:
        raise SmartsheetConfigurationError(
            "SMARTSHEET_URL_PREFILL_ENABLED is not enabled."
        )
    if not config.form_field_map:
        raise SmartsheetConfigurationError(
            "Exact form labels are required in SMARTSHEET_FORM_FIELD_MAP_JSON."
        )

    split = urlsplit(config.form_url)
    query_items = list(parse_qsl(split.query, keep_blank_values=True))
    included: list[str] = []
    skipped: list[str] = []

    for logical, value in fields.items():
        if not _nonempty(value):
            continue
        label = config.form_field_map.get(logical)
        if not label:
            skipped.append(logical)
            continue
        query_items.append((label, _mapped_form_value(config, logical, value)))
        included.append(logical)

    query = urlencode(query_items, doseq=True)
    return PrefillResult(
        url=urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment)),
        included=tuple(included),
        skipped=tuple(skipped),
    )


def handoff_rows(
    fields: Mapping[str, Any], config: SmartsheetConfig
) -> list[tuple[str, str, str]]:
    """Return logical key, display label, and value in configured form order."""
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for logical in (*config.form_order, *fields.keys()):
        if logical in seen:
            continue
        seen.add(logical)
        value = fields.get(logical)
        if not _nonempty(value):
            continue
        label = config.form_field_map.get(logical) or DISPLAY_LABELS.get(logical, logical)
        rows.append((logical, label, str(value).strip()))
    return rows


def download_names(
    attachments: Sequence[tuple[str, bytes]], base: str
) -> list[tuple[str, str, bytes]]:
    stem = re.sub(r"\s*MSAPO\s*$", "", base or "").strip() or "PO"
    result: list[tuple[str, str, bytes]] = []
    for index, (filename, data) in enumerate(attachments, 1):
        extension = os.path.splitext(filename)[1].lower()
        kind = "Quote" if index == 1 else "MSAPO"
        label = f"{kind} · {extension.lstrip('.').upper()}" if extension else kind
        result.append((label, f"{stem} {index} {kind}{extension}", data))
    return result


def _headers(config: SmartsheetConfig, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "smartsheet-integration-source": "APPLICATION,ENFRA,EmailProcessControl",
    }
    if extra:
        headers.update(extra)
    return headers


def get_columns(config: SmartsheetConfig) -> list[dict]:
    response = requests.get(
        f"{config.api_base_url}/sheets/{config.sheet_id}/columns?includeAll=true",
        headers=_headers(config),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def validate_column_mapping(config: SmartsheetConfig) -> dict:
    readiness = api_readiness(config)
    if not readiness.ready:
        return {"ok": False, "problems": list(readiness.problems)}
    try:
        columns = get_columns(config)
    except Exception as exc:  # noqa: BLE001 - converted to user-facing text
        return {"ok": False, "problems": [_error_text(exc)]}

    by_id = {int(column["id"]): column for column in columns if column.get("id") is not None}
    missing = [
        logical for logical, column_id in config.column_map.items() if column_id not in by_id
    ]
    mapped = {
        logical: {
            "id": column_id,
            "title": by_id[column_id].get("title", ""),
            "type": by_id[column_id].get("type", ""),
        }
        for logical, column_id in config.column_map.items()
        if column_id in by_id
    }
    return {"ok": not missing, "mapped": mapped, "missing": missing}


def _clean_amount(value: Any) -> float | str | None:
    if value is None:
        return None
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value))
    if not match:
        return str(value)
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return str(value)


def _attachment_fingerprint(filename: str, data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(filename.encode("utf-8", "ignore"))
    digest.update(b"\0")
    digest.update(data)
    return digest.hexdigest()


def submission_fingerprint(
    fields: Mapping[str, Any], attachments: Sequence[tuple[str, bytes]]
) -> str:
    normalized_fields = {
        key: str(value).strip()
        for key, value in sorted(fields.items())
        if _nonempty(value) and key != "submission_key"
    }
    payload = {
        "fields": normalized_fields,
        "attachments": [
            {"name": filename, "sha256": _attachment_fingerprint(filename, data)}
            for filename, data in attachments
            if data
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_cells(
    fields: Mapping[str, Any], config: SmartsheetConfig, columns: Mapping[int, dict]
) -> list[dict]:
    cells: list[dict] = []
    for logical, column_id in config.column_map.items():
        raw = fields.get(logical)
        if not _nonempty(raw):
            continue
        if column_id not in columns:
            continue
        value = _clean_amount(raw) if logical in _AMOUNT_FIELDS else str(raw).strip()
        cells.append({"columnId": column_id, "value": value, "strict": False})
    return cells


def _create_row(config: SmartsheetConfig, cells: list[dict]) -> dict:
    row: dict[str, Any] = {"cells": cells}
    if config.row_position == "top":
        row["toTop"] = True
    response = requests.post(
        f"{config.api_base_url}/sheets/{config.sheet_id}/rows",
        headers=_headers(config, {"Content-Type": "application/json"}),
        json=[row],
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    result = response.json().get("result") or []
    if not result or "id" not in result[0]:
        raise RuntimeError("Smartsheet created no identifiable row.")
    return result[0]


def _attach_file(
    config: SmartsheetConfig, row_id: str | int, filename: str, data: bytes
) -> None:
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"{filename} is larger than Smartsheet's 30 MB attachment limit."
        )
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    disposition_name = quote(filename, safe="")
    response = requests.post(
        f"{config.api_base_url}/sheets/{config.sheet_id}/rows/{row_id}/attachments",
        headers=_headers(
            config,
            {
                "Content-Type": mime,
                "Content-Disposition": f'attachment; filename="{disposition_name}"',
                "Content-Length": str(len(data)),
            },
        ),
        data=data,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def submit_po(
    fields: Mapping[str, Any],
    attachments: Sequence[tuple[str, bytes]] | None = None,
    *,
    config: SmartsheetConfig | None = None,
    store: SubmissionStore | None = None,
) -> dict:
    """Create or safely resume one Smartsheet row and its attachments."""
    cfg = config or load_config()
    files = list(attachments or [])
    readiness = api_readiness(cfg)
    if cfg.api_mode != "live":
        return {
            "ok": False,
            "error": "Smartsheet API submission is not in live mode.",
            "problems": list(readiness.problems),
        }
    if not readiness.ready:
        return {"ok": False, "error": "Smartsheet API configuration is incomplete.",
                "problems": list(readiness.problems)}

    missing_values = [field for field in cfg.required_fields if not _nonempty(fields.get(field))]
    if missing_values:
        return {
            "ok": False,
            "error": "Required Smartsheet values are missing: " + ", ".join(missing_values),
        }

    try:
        columns = get_columns(cfg)
        columns_by_id = {
            int(column["id"]): column for column in columns if column.get("id") is not None
        }
        invalid_mappings = [
            logical for logical, column_id in cfg.column_map.items()
            if column_id not in columns_by_id
        ]
        if invalid_mappings:
            return {
                "ok": False,
                "error": "Configured Smartsheet column IDs were not found: "
                + ", ".join(invalid_mappings),
            }

        key = submission_fingerprint(fields, files)
        enriched_fields = dict(fields)
        if "submission_key" in cfg.column_map:
            enriched_fields["submission_key"] = key

        cells = _build_cells(enriched_fields, cfg, columns_by_id)
        if not cells:
            return {"ok": False, "error": "No populated fields map to configured columns."}

        history = store or SubmissionStore.from_environment()
        claim = history.claim(key)
        if not claim.allowed:
            if claim.reason == "complete":
                return {
                    "ok": True,
                    "duplicate": True,
                    "row_id": claim.row_id,
                    "attached": len(claim.attached),
                    "skipped_attachments": [],
                    "submission_key": key,
                }
            return {
                "ok": False,
                "error": "This PO is already being submitted in another request.",
                "submission_key": key,
            }

        row_id = claim.row_id
        if not row_id:
            row = _create_row(cfg, cells)
            row_id = str(row["id"])
            history.record_row(key, row_id)

        attached_fingerprints = set(claim.attached)
        attached_count = len(attached_fingerprints)
        skipped: list[str] = []
        for filename, data in files:
            if not data:
                continue
            fingerprint = _attachment_fingerprint(filename, data)
            if fingerprint in attached_fingerprints:
                continue
            try:
                _attach_file(cfg, row_id, filename, data)
                history.record_attachment(key, fingerprint)
                attached_fingerprints.add(fingerprint)
                attached_count += 1
            except Exception as exc:  # noqa: BLE001 - preserve row and allow safe retry
                skipped.append(f"{filename}: {_error_text(exc)}")

        if skipped:
            history.finish(key, "partial", "; ".join(skipped))
        else:
            history.finish(key, "complete")
        return {
            "ok": True,
            "duplicate": False,
            "partial": bool(skipped),
            "row_id": row_id,
            "attached": attached_count,
            "skipped_attachments": skipped,
            "submission_key": key,
        }
    except SubmissionStoreError as exc:
        return {
            "ok": False,
            "error": (
                "Smartsheet submission was blocked because duplicate-prevention "
                f"storage is unavailable. {exc}"
            ),
        }
    except Exception as exc:  # noqa: BLE001 - UI receives a concise message
        return {"ok": False, "error": _error_text(exc)}


_STATUS_HINTS = {
    401: "The API token is missing, expired, or invalid.",
    403: "The token account does not have permission to edit this sheet.",
    404: "The sheet ID is not visible to the configured token account.",
    413: "The request or attachment is too large for Smartsheet.",
    429: "Smartsheet is rate-limiting the integration; wait and retry.",
}


def _error_text(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc) or exc.__class__.__name__
    status = getattr(response, "status_code", None)
    message = None
    try:
        body = response.json()
        if isinstance(body, dict):
            message = body.get("message") or (body.get("error") or {}).get("message")
    except Exception:  # noqa: BLE001 - error bodies may be non-JSON
        pass
    text = message or (f"HTTP {status}" if status else str(exc))
    hint = _STATUS_HINTS.get(status)
    return f"{text} {hint}".strip() if hint else text
