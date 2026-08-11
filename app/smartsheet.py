"""Fail-closed three-mode Smartsheet handoff for ENFRA PO intake.

The live PO form's labels, required inputs, and job choices are represented
exactly. Manual copy/paste is enabled when the verified form URL is configured;
URL prefilling and direct API submission remain independently gated. Production
API writes require explicit column IDs, exact titles/types, a submission-key
column, strict cell parsing, persistent leases, and verified attachments.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from app.job_numbers import JOB_NUMBER_OPTIONS, RRH_JOB_NUMBERS
from app.smartsheet_store import SubmissionStore, SubmissionStoreError
from app.po_rules import (
    EQUIPMENT_ACCOUNT,
    EQUIPMENT_PO,
    MATERIALS_ACCOUNT,
    OUTSIDE_RENTALS_ACCOUNT,
    RENTAL_AGREEMENT,
    SERVICE_AGREEMENT,
    STANDARD_PO_OVER_25K,
    STANDARD_PO_UNDER_25K,
    SUBCONTRACTOR_ACCOUNT,
    parse_amount,
)

BASE_URL = "https://api.smartsheet.com/2.0"
REQUEST_TIMEOUT = 60
MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024
MAX_CELL_CHARS = 4000
DEFAULT_PREFILL_MAX_URL_LENGTH = 7000

DISPLAY_LABELS: dict[str, str] = {
    "request_type": "REQUEST TYPE",
    "requester_name": "REQUESTER",
    "job_number": "JOB NUMBER",
    "site_location": "SITE NUMBER / LOCATION",
    "cost_code": "COST CODE",
    "object_account": "OBJECT ACCOUNT",
    "agreement_type": "AGREEMENT TYPE FOR PO",
    "leave_request_completed": "LEAVE REQUEST COMPLETED",
    "po_number": "PO #",
    "work_order_number": "WORK ORDER #",
    "original_po_number": "ORIGINAL PO NUMBER",
    "total": "PO/CO AMOUNT",
    "vendor": "VENDOR NAME",
    "contact_name": "VENDOR CONTACT NAME",
    "contact_email": "VENDOR CONTACT EMAIL",
    "description_of_work": "DESCRIPTION OF WORK",
    "asset_id": "ASSET ID",
    "dispatch_service_center": "DISPATCH WO TO SERVICE CENTER?",
    "instructions": "ADDITIONAL INFORMATION IF NEEDED",
    "submission_key": "Purchase Order Process Control Submission Key",
}
KNOWN_FIELDS = frozenset(DISPLAY_LABELS)
ALWAYS_BLANK_FIELDS = frozenset(
    {
        "leave_request_completed",
        "po_number",
        "work_order_number",
    }
)

DEFAULT_FORM_ORDER: tuple[str, ...] = (
    "request_type",
    "requester_name",
    "job_number",
    "site_location",
    "cost_code",
    "object_account",
    "agreement_type",
    "original_po_number",
    "total",
    "vendor",
    "contact_name",
    "contact_email",
    "description_of_work",
    "asset_id",
    "dispatch_service_center",
    "instructions",
)

DEFAULT_FORM_REQUIRED_FIELDS: tuple[str, ...] = (
    "request_type",
    "requester_name",
    "job_number",
    "site_location",
    "cost_code",
    "object_account",
    "agreement_type",
    "total",
    "vendor",
    "contact_name",
    "contact_email",
    "description_of_work",
    "dispatch_service_center",
)

OBJECT_ACCOUNT_OPTIONS: tuple[str, ...] = (
    "NA",
    MATERIALS_ACCOUNT,
    "5490-OTHER",
    SUBCONTRACTOR_ACCOUNT,
    EQUIPMENT_ACCOUNT,
    OUTSIDE_RENTALS_ACCOUNT,
)
AGREEMENT_TYPE_OPTIONS: tuple[str, ...] = (
    "NA",
    SERVICE_AGREEMENT,
    RENTAL_AGREEMENT,
    "03 - CSAPO (CONSTRUCTION)",
    STANDARD_PO_UNDER_25K,
    STANDARD_PO_OVER_25K,
    EQUIPMENT_PO,
)
REQUEST_TYPE_OPTIONS: tuple[str, ...] = ("PO", "CHANGE ORDER")
_EXACT_OPTIONS: dict[str, tuple[str, ...]] = {
    "request_type": REQUEST_TYPE_OPTIONS,
    "job_number": JOB_NUMBER_OPTIONS,
    "object_account": OBJECT_ACCOUNT_OPTIONS,
    "agreement_type": AGREEMENT_TYPE_OPTIONS,
    "dispatch_service_center": ("NA",),
}

_AMOUNT_FIELDS = {"total"}
_DATE_FIELDS: set[str] = set()
_EMAIL_FIELDS = {"contact_email"}
_BOOLEAN_FIELDS: set[str] = set()
_ALLOWED_API_MODES = {"disabled", "dry_run", "live"}
_ALLOWED_ROW_POSITIONS = {"top", "bottom"}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._()\[\] -]+")


class SmartsheetConfigurationError(ValueError):
    """Raised when optional Smartsheet configuration is unsafe or inconsistent."""


@dataclass(frozen=True)
class ColumnSpec:
    id: int
    title: str
    type: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SmartsheetConfig:
    form_url: str | None
    prefill_enabled: bool
    form_field_map: dict[str, str]
    form_value_map: dict[str, dict[str, str]]
    form_order: tuple[str, ...]
    form_required_fields: tuple[str, ...]
    prefill_max_url_length: int
    api_mode: str
    api_token: str | None
    sheet_id: str | None
    column_specs: dict[str, ColumnSpec]
    required_fields: tuple[str, ...]
    row_position: str
    api_base_url: str

    @property
    def column_map(self) -> dict[str, int]:
        return {field: spec.id for field, spec in self.column_specs.items()}


@dataclass(frozen=True)
class PrefillResult:
    url: str
    included: tuple[str, ...]
    skipped: tuple[str, ...]
    missing_required: tuple[str, ...]


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


def _integer(
    env: Mapping[str, str], name: str, default: int, *, minimum: int, maximum: int
) -> int:
    raw = _text(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SmartsheetConfigurationError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise SmartsheetConfigurationError(
            f"{name} must be between {minimum} and {maximum}."
        )
    return value


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


def _known_field(field: Any, source: str) -> str:
    if not isinstance(field, str) or field.strip() not in KNOWN_FIELDS:
        raise SmartsheetConfigurationError(
            f"{source} contains unknown logical field {field!r}."
        )
    return field.strip()


def _csv_fields(env: Mapping[str, str], name: str) -> tuple[str, ...]:
    raw = _text(env, name)
    if raw is None:
        return ()
    result: list[str] = []
    for item in raw.split(","):
        if not item.strip():
            continue
        field = _known_field(item.strip(), name)
        if field in result:
            raise SmartsheetConfigurationError(f"{name} contains duplicate field {field!r}.")
        result.append(field)
    return tuple(result)


def _validate_form_url(url: str | None) -> str | None:
    if not url:
        return None
    split = urlsplit(url)
    host = (split.hostname or "").lower()
    if split.scheme != "https" or not host:
        raise SmartsheetConfigurationError(
            "SMARTSHEET_FORM_URL must be an absolute HTTPS URL."
        )
    if host != "smartsheet.com" and not host.endswith(".smartsheet.com"):
        raise SmartsheetConfigurationError(
            "SMARTSHEET_FORM_URL must use a Smartsheet domain."
        )
    return url


def _validate_api_base(url: str, *, allow_custom: bool, mode: str) -> str:
    split = urlsplit(url)
    host = (split.hostname or "").lower()
    if split.scheme != "https" or not host:
        raise SmartsheetConfigurationError("SMARTSHEET_API_BASE_URL must be HTTPS.")
    if host != "api.smartsheet.com":
        if mode == "live" or not allow_custom:
            raise SmartsheetConfigurationError(
                "Live Smartsheet tokens may only be sent to api.smartsheet.com."
            )
    return url.rstrip("/")


def _parse_column_specs(env: Mapping[str, str]) -> dict[str, ColumnSpec]:
    raw_specs = _json_object(env, "SMARTSHEET_COLUMN_SPECS_JSON")
    legacy_map = _json_object(env, "SMARTSHEET_COLUMN_MAP_JSON")
    specs: dict[str, ColumnSpec] = {}

    if raw_specs:
        for raw_field, raw_spec in raw_specs.items():
            field = _known_field(raw_field, "SMARTSHEET_COLUMN_SPECS_JSON")
            if not isinstance(raw_spec, dict):
                raise SmartsheetConfigurationError(
                    f"Column specification for {field!r} must be an object."
                )
            try:
                column_id = int(raw_spec.get("id"))
            except (TypeError, ValueError) as exc:
                raise SmartsheetConfigurationError(
                    f"Column ID for {field!r} must be numeric."
                ) from exc
            title = str(raw_spec.get("title", "")).strip()
            column_type = str(raw_spec.get("type", "")).strip().upper()
            options_raw = raw_spec.get("options", [])
            if not isinstance(options_raw, list) or not all(
                isinstance(option, (str, int, float, bool)) for option in options_raw
            ):
                raise SmartsheetConfigurationError(
                    f"Column options for {field!r} must be a JSON array of values."
                )
            specs[field] = ColumnSpec(
                column_id,
                title,
                column_type,
                tuple(str(option) for option in options_raw),
            )
    elif legacy_map:
        for raw_field, raw_id in legacy_map.items():
            field = _known_field(raw_field, "SMARTSHEET_COLUMN_MAP_JSON")
            try:
                column_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise SmartsheetConfigurationError(
                    f"Smartsheet column ID for {field!r} must be numeric."
                ) from exc
            specs[field] = ColumnSpec(column_id, "", "")

    ids = [spec.id for spec in specs.values()]
    if any(column_id <= 0 for column_id in ids):
        raise SmartsheetConfigurationError("Smartsheet column IDs must be positive.")
    if len(ids) != len(set(ids)):
        raise SmartsheetConfigurationError(
            "Two logical fields cannot map to the same Smartsheet column ID."
        )
    return specs


def load_config(env: Mapping[str, str] | None = None) -> SmartsheetConfig:
    source = os.environ if env is None else env
    api_mode = (_text(source, "SMARTSHEET_API_MODE") or "disabled").lower()
    if api_mode not in _ALLOWED_API_MODES:
        raise SmartsheetConfigurationError(
            "SMARTSHEET_API_MODE must be disabled, dry_run, or live."
        )

    field_map_raw = _json_object(source, "SMARTSHEET_FORM_FIELD_MAP_JSON")
    field_map: dict[str, str] = {}
    labels: set[str] = set()
    for raw_field, raw_label in field_map_raw.items():
        field = _known_field(raw_field, "SMARTSHEET_FORM_FIELD_MAP_JSON")
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise SmartsheetConfigurationError(
                "SMARTSHEET_FORM_FIELD_MAP_JSON values must be exact non-empty labels."
            )
        label = raw_label.strip()
        if label in labels:
            raise SmartsheetConfigurationError(
                f"Two logical fields cannot use the same form label {label!r}."
            )
        labels.add(label)
        field_map[field] = label

    value_map_raw = _json_object(source, "SMARTSHEET_FORM_VALUE_MAP_JSON")
    value_map: dict[str, dict[str, str]] = {}
    for raw_field, mappings in value_map_raw.items():
        field = _known_field(raw_field, "SMARTSHEET_FORM_VALUE_MAP_JSON")
        if not isinstance(mappings, dict):
            raise SmartsheetConfigurationError(
                "SMARTSHEET_FORM_VALUE_MAP_JSON must map fields to objects."
            )
        normalized: dict[str, str] = {}
        for original, replacement in mappings.items():
            if not isinstance(replacement, (str, int, float, bool)):
                raise SmartsheetConfigurationError(
                    f"Value mapping for {field!r} contains an unsupported value."
                )
            normalized[str(original)] = str(replacement)
        value_map[field] = normalized

    configured_order = _csv_fields(source, "SMARTSHEET_FORM_ORDER")
    required_fields = _csv_fields(source, "SMARTSHEET_REQUIRED_FIELDS")
    form_required = _csv_fields(source, "SMARTSHEET_FORM_REQUIRED_FIELDS")
    row_position = (_text(source, "SMARTSHEET_ROW_POSITION") or "bottom").lower()
    if row_position not in _ALLOWED_ROW_POSITIONS:
        raise SmartsheetConfigurationError(
            "SMARTSHEET_ROW_POSITION must be top or bottom."
        )

    api_base = _validate_api_base(
        _text(source, "SMARTSHEET_API_BASE_URL") or BASE_URL,
        allow_custom=_bool(source, "SMARTSHEET_ALLOW_CUSTOM_API_BASE", False),
        mode=api_mode,
    )

    return SmartsheetConfig(
        form_url=_validate_form_url(_text(source, "SMARTSHEET_FORM_URL")),
        prefill_enabled=_bool(source, "SMARTSHEET_URL_PREFILL_ENABLED", False),
        form_field_map=field_map,
        form_value_map=value_map,
        form_order=configured_order or DEFAULT_FORM_ORDER,
        form_required_fields=form_required or DEFAULT_FORM_REQUIRED_FIELDS,
        prefill_max_url_length=_integer(
            source,
            "SMARTSHEET_PREFILL_MAX_URL_LENGTH",
            DEFAULT_PREFILL_MAX_URL_LENGTH,
            minimum=1000,
            maximum=20000,
        ),
        api_mode=api_mode,
        api_token=_text(source, "SMARTSHEET_API_TOKEN"),
        sheet_id=_text(source, "SMARTSHEET_SHEET_ID"),
        column_specs=_parse_column_specs(source),
        required_fields=required_fields,
        row_position=row_position,
        api_base_url=api_base,
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
    if not config.column_specs:
        problems.append("No explicit Smartsheet column specifications are configured.")
    if not config.required_fields:
        problems.append("SMARTSHEET_REQUIRED_FIELDS has not been confirmed.")
    missing = [field for field in config.required_fields if field not in config.column_specs]
    if missing:
        problems.append("Required fields lack column specifications: " + ", ".join(missing))
    if "submission_key" not in config.column_specs:
        problems.append("A dedicated submission_key column is required for reconciliation.")
    incomplete_specs = [
        field
        for field, spec in config.column_specs.items()
        if not spec.title or not spec.type
    ]
    if incomplete_specs:
        problems.append(
            "Column specifications need exact title and type for: "
            + ", ".join(incomplete_specs)
        )
    return ApiReadiness(not problems, config.api_mode, tuple(problems))


def _nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _must_remain_blank(field: str, fields: Mapping[str, Any]) -> bool:
    if field in ALWAYS_BLANK_FIELDS:
        return True
    return (
        field == "original_po_number"
        and str(fields.get("request_type", "")).strip() != "CHANGE ORDER"
    )


def _mapped_value(config: SmartsheetConfig, field: str, value: Any) -> str:
    text = str(value).strip()
    mappings = config.form_value_map.get(field, {})
    if text in mappings:
        return mappings[text]
    lowered = text.lower()
    for source, replacement in mappings.items():
        if source.lower() == lowered:
            return replacement
    return text


def missing_required_fields(
    fields: Mapping[str, Any], required_fields: Sequence[str]
) -> tuple[str, ...]:
    missing = [
        field for field in required_fields if not _nonempty(fields.get(field))
    ]
    if (
        str(fields.get("request_type", "")).strip() == "CHANGE ORDER"
        and not _nonempty(fields.get("original_po_number"))
        and "original_po_number" not in missing
    ):
        missing.append("original_po_number")
    return tuple(missing)


def validate_submission_fields(fields: Mapping[str, Any]) -> tuple[str, ...]:
    problems: list[str] = []
    for field, value in fields.items():
        if field not in KNOWN_FIELDS:
            continue
        if _must_remain_blank(field, fields):
            if _nonempty(value):
                problems.append(f"{DISPLAY_LABELS[field]} must remain blank.")
            continue
        if not _nonempty(value):
            continue
        text = str(value).strip()
        if len(text) > MAX_CELL_CHARS:
            problems.append(
                f"{DISPLAY_LABELS[field]} exceeds Smartsheet's {MAX_CELL_CHARS:,}-character cell limit."
            )
        if field in _EMAIL_FIELDS and not _EMAIL_RE.match(text):
            problems.append(f"{DISPLAY_LABELS[field]} is not a valid email address.")
        if field in _DATE_FIELDS:
            try:
                _iso_date(text)
            except ValueError:
                problems.append(
                    f"{DISPLAY_LABELS[field]} must be MM/DD/YYYY or YYYY-MM-DD."
                )
        if field in _AMOUNT_FIELDS:
            try:
                _money_number(text)
            except ValueError:
                problems.append(f"{DISPLAY_LABELS[field]} is not a valid amount.")
        if field == "description_of_work" and len(text) > 20:
            problems.append("DESCRIPTION OF WORK must be 20 characters or fewer.")
        if field == "asset_id" and len(text) > 160:
            problems.append("ASSET ID exceeds the 160-character safety limit.")
        options = _EXACT_OPTIONS.get(field)
        if options and text not in options:
            problems.append(
                f"{DISPLAY_LABELS[field]} must exactly match one of: {', '.join(options)}."
            )
    return tuple(problems)


def _encode_prefill_query(query_items: Sequence[tuple[str, str]]) -> str:
    """Use Smartsheet's documented percent-encoded query-string wire format.

    ``urlencode`` defaults to form-style ``quote_plus`` encoding, which renders
    spaces as ``+``. The live Smartsheet form accepts the documented ``%20``
    representation for spaces in form labels and values, so use RFC 3986
    percent encoding explicitly.
    """
    return urlencode(query_items, doseq=True, quote_via=quote)


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
    existing = list(parse_qsl(split.query, keep_blank_values=True))
    mapped_labels = set(config.form_field_map.values())
    query_items = [(key, value) for key, value in existing if key not in mapped_labels]
    included: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for field in (*config.form_order, *fields.keys()):
        if field in seen:
            continue
        seen.add(field)
        if field not in KNOWN_FIELDS:
            continue
        if _must_remain_blank(field, fields):
            continue
        value = fields.get(field)
        if not _nonempty(value):
            continue
        label = config.form_field_map.get(field)
        if not label:
            skipped.append(f"{field}: no exact label mapping")
            continue
        text = _mapped_value(config, field, value)
        if len(text) > MAX_CELL_CHARS:
            skipped.append(f"{field}: value exceeds {MAX_CELL_CHARS:,} characters")
            continue
        candidate = [*query_items, (label, text)]
        candidate_url = urlunsplit(
            (
                split.scheme,
                split.netloc,
                split.path,
                _encode_prefill_query(candidate),
                split.fragment,
            )
        )
        if len(candidate_url) > config.prefill_max_url_length:
            skipped.append(f"{field}: URL length limit reached")
            continue
        query_items = candidate
        included.append(field)

    url = urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            _encode_prefill_query(query_items),
            split.fragment,
        )
    )
    required_for_request = list(config.form_required_fields)
    if (
        str(fields.get("request_type", "")).strip() == "CHANGE ORDER"
        and "original_po_number" not in required_for_request
    ):
        required_for_request.append("original_po_number")
    missing = tuple(
        field
        for field in required_for_request
        if not _must_remain_blank(field, fields)
        and (not _nonempty(fields.get(field)) or field not in included)
    )
    return PrefillResult(url, tuple(included), tuple(skipped), missing)


def handoff_rows(
    fields: Mapping[str, Any], config: SmartsheetConfig
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for field in (*config.form_order, *fields.keys()):
        if field in seen:
            continue
        seen.add(field)
        if field not in KNOWN_FIELDS:
            continue
        if _must_remain_blank(field, fields):
            continue
        value = fields.get(field)
        if not _nonempty(value):
            continue
        label = config.form_field_map.get(field) or DISPLAY_LABELS.get(field, field)
        rows.append((field, label, str(value).strip()))
    return rows


def _safe_filename(filename: str, default: str = "attachment") -> str:
    name = Path(str(filename or "")).name.replace("\r", "").replace("\n", "").strip()
    name = _SAFE_FILENAME_RE.sub("_", name).strip(" .")
    return name[:180] or default


def download_names(
    attachments: Sequence[tuple[str, bytes]], base: str
) -> list[tuple[str, str, bytes]]:
    stem = re.sub(
        r"\s*(?:MSAPO|Scope)\s*$",
        "",
        _safe_filename(base, "PO"),
        flags=re.I,
    ).strip() or "PO"
    result: list[tuple[str, str, bytes]] = []
    for index, (filename, data) in enumerate(attachments, 1):
        safe_original = _safe_filename(filename)
        extension = Path(safe_original).suffix.lower()
        kind = "Quote" if index == 1 else "Scope"
        label = f"{kind} · {extension.lstrip('.').upper()}" if extension else kind
        result.append((label, f"{stem} {index} {kind}{extension}", data))
    return result


def preflight_attachments(
    attachments: Sequence[tuple[str, bytes]]
) -> tuple[str, ...]:
    problems: list[str] = []
    seen_names: set[str] = set()
    for filename, data in attachments:
        safe_name = _safe_filename(filename)
        if not isinstance(data, bytes) or not data:
            problems.append(f"{safe_name} is empty or unreadable.")
            continue
        if len(data) > MAX_ATTACHMENT_BYTES:
            problems.append(
                f"{safe_name} is larger than Smartsheet's 30 MB attachment limit."
            )
        folded = safe_name.casefold()
        if folded in seen_names:
            problems.append(f"Attachment filename is duplicated: {safe_name}.")
        seen_names.add(folded)
    return tuple(problems)


def _headers(config: SmartsheetConfig, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "smartsheet-integration-source": "APPLICATION,ENFRA,PurchaseOrderProcessControl",
    }
    if extra:
        headers.update(extra)
    return headers


def _retry_after(response: Any, attempt: int) -> float:
    raw = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
    try:
        return min(30.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return float(min(8, 2 ** attempt))


def _safe_get(config: SmartsheetConfig, url: str, **kwargs) -> requests.Response:
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                headers=_headers(config),
                timeout=REQUEST_TIMEOUT,
                **kwargs,
            )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    time.sleep(_retry_after(response, attempt))
                    continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last = exc
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if attempt < 2 and (status is None or status == 429 or status >= 500):
                time.sleep(_retry_after(response, attempt))
                continue
            raise
    raise last or RuntimeError("Smartsheet GET request failed.")


def get_columns(config: SmartsheetConfig) -> list[dict]:
    response = _safe_get(
        config,
        f"{config.api_base_url}/sheets/{config.sheet_id}/columns",
        params={"includeAll": "true", "level": 2},
    )
    return response.json().get("data", [])


def _column_problems(
    config: SmartsheetConfig, columns: Sequence[dict]
) -> tuple[list[str], dict[int, dict]]:
    by_id = {int(column["id"]): column for column in columns if column.get("id") is not None}
    problems: list[str] = []
    for field, spec in config.column_specs.items():
        column = by_id.get(spec.id)
        if not column:
            problems.append(f"{field}: column ID {spec.id} was not found")
            continue
        if str(column.get("title", "")).strip() != spec.title:
            problems.append(
                f"{field}: expected title {spec.title!r}, found {column.get('title')!r}"
            )
        if str(column.get("type", "")).upper() != spec.type:
            problems.append(
                f"{field}: expected type {spec.type}, found {column.get('type')}"
            )
        if column.get("lockedForUser"):
            problems.append(f"{field}: column is locked for the token account")
        if column.get("systemColumnType") or column.get("formula"):
            problems.append(f"{field}: system/formula columns are not writable inputs")
        actual_options = tuple(str(option) for option in column.get("options", []) or [])
        missing_options = [option for option in spec.options if option not in actual_options]
        if missing_options:
            problems.append(
                f"{field}: expected options are missing: {', '.join(missing_options)}"
            )
    return problems, by_id


def validate_column_mapping(config: SmartsheetConfig) -> dict:
    readiness = api_readiness(config)
    if not readiness.ready:
        return {"ok": False, "problems": list(readiness.problems)}
    try:
        columns = get_columns(config)
        problems, by_id = _column_problems(config, columns)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "problems": [_error_text(exc)]}
    mapped = {
        field: {
            "id": spec.id,
            "title": by_id[spec.id].get("title", ""),
            "type": by_id[spec.id].get("type", ""),
        }
        for field, spec in config.column_specs.items()
        if spec.id in by_id
    }
    return {"ok": not problems, "mapped": mapped, "problems": problems}


def _money_number(value: Any) -> float:
    amount = parse_amount(value)
    if amount is None or amount <= 0:
        raise ValueError("must be a valid amount greater than $0.00")
    return float(amount)


def _iso_date(value: Any) -> str:
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError("invalid date")


def _boolean(value: Any) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    raise ValueError("invalid boolean")


def _cell_value(field: str, raw: Any, column: Mapping[str, Any]) -> Any:
    text = str(raw).strip()
    if len(text) > MAX_CELL_CHARS:
        raise ValueError(f"exceeds {MAX_CELL_CHARS:,} characters")
    column_type = str(column.get("type", "")).upper()
    if field in _AMOUNT_FIELDS:
        return _money_number(text)
    if column_type in {"DATE", "ABSTRACT_DATETIME"} or field in _DATE_FIELDS:
        return _iso_date(text)
    if column_type == "CHECKBOX" or field in _BOOLEAN_FIELDS:
        return _boolean(text)
    if column_type == "CONTACT_LIST":
        if not _EMAIL_RE.match(text):
            raise ValueError("must be a valid email address for a contact column")
        return text
    if column_type in {"PICKLIST", "MULTI_PICKLIST"}:
        options = [str(option) for option in column.get("options", []) or []]
        if options and text not in options:
            raise ValueError(f"must exactly match one of: {', '.join(options)}")
    return text


def _build_cells(
    fields: Mapping[str, Any], config: SmartsheetConfig, columns: Mapping[int, dict]
) -> tuple[list[dict], list[str]]:
    cells: list[dict] = []
    problems: list[str] = []
    for field, spec in config.column_specs.items():
        if _must_remain_blank(field, fields):
            continue
        raw = fields.get(field)
        if not _nonempty(raw):
            continue
        column = columns.get(spec.id)
        if not column:
            continue
        try:
            value = _cell_value(field, raw, column)
        except ValueError as exc:
            problems.append(f"{DISPLAY_LABELS[field]} {exc}.")
            continue
        cells.append({"columnId": spec.id, "value": value, "strict": True})
    return cells, problems


def _create_row(config: SmartsheetConfig, cells: list[dict]) -> dict:
    row: dict[str, Any] = {"cells": cells}
    row["toTop" if config.row_position == "top" else "toBottom"] = True
    response = requests.post(
        f"{config.api_base_url}/sheets/{config.sheet_id}/rows",
        headers=_headers(config, {"Content-Type": "application/json"}),
        json=[row],
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    result = response.json().get("result")
    if isinstance(result, dict):
        created = result
    elif isinstance(result, list) and result:
        created = result[0]
    else:
        raise RuntimeError("Smartsheet created no identifiable row.")
    if "id" not in created:
        raise RuntimeError("Smartsheet row response did not include an ID.")
    return created


def _attachment_fingerprint(filename: str, data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(_safe_filename(filename).encode("utf-8"))
    digest.update(b"\0")
    digest.update(data)
    return digest.hexdigest()


def _api_attachment_name(filename: str, data: bytes) -> str:
    safe = _safe_filename(filename)
    path = Path(safe)
    fingerprint = _attachment_fingerprint(safe, data)[:12]
    stem = path.stem[:140] or "attachment"
    return f"{stem} [EPC-{fingerprint}]{path.suffix.lower()}"


def _attach_file(
    config: SmartsheetConfig, row_id: str | int, filename: str, data: bytes
) -> None:
    api_name = _api_attachment_name(filename, data)
    mime = mimetypes.guess_type(api_name)[0] or "application/octet-stream"
    encoded_name = quote(api_name, safe="")
    response = requests.post(
        f"{config.api_base_url}/sheets/{config.sheet_id}/rows/{row_id}/attachments",
        headers=_headers(
            config,
            {
                "Content-Type": mime,
                "Content-Disposition": f'attachment; filename="{encoded_name}"',
                "Content-Length": str(len(data)),
            },
        ),
        data=data,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def _row_attachment_names(config: SmartsheetConfig, row_id: str | int) -> set[str]:
    response = _safe_get(
        config,
        f"{config.api_base_url}/sheets/{config.sheet_id}/rows/{row_id}/attachments",
        params={"includeAll": "true"},
    )
    body = response.json()
    entries = body.get("data", body if isinstance(body, list) else [])
    return {
        str(entry.get("name", ""))
        for entry in entries
        if isinstance(entry, dict) and entry.get("name")
    }


def _remote_has_attachment(names: set[str], filename: str, data: bytes) -> bool:
    return _api_attachment_name(filename, data) in names


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
            {"name": _safe_filename(filename), "sha256": hashlib.sha256(data).hexdigest()}
            for filename, data in attachments
            if isinstance(data, bytes) and data
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _search_rows_for_key(config: SmartsheetConfig, key: str) -> list[str]:
    response = _safe_get(
        config,
        f"{config.api_base_url}/search/sheets/{config.sheet_id}",
        params={"query": f'"{key}"'},
    )
    results = response.json().get("results", [])
    candidates = [
        str(item.get("objectId"))
        for item in results
        if isinstance(item, dict) and item.get("objectType") == "row" and item.get("objectId")
    ]
    verified: list[str] = []
    key_column_id = config.column_specs["submission_key"].id
    for row_id in candidates:
        row_response = _safe_get(
            config,
            f"{config.api_base_url}/sheets/{config.sheet_id}/rows/{row_id}",
        )
        row = row_response.json()
        for cell in row.get("cells", []):
            if int(cell.get("columnId", -1)) == key_column_id and str(cell.get("value", "")) == key:
                verified.append(row_id)
                break
    return list(dict.fromkeys(verified))


def reconcile_submission(
    fields: Mapping[str, Any],
    attachments: Sequence[tuple[str, bytes]],
    *,
    config: SmartsheetConfig | None = None,
    store: SubmissionStore | None = None,
) -> dict:
    cfg = config or load_config()
    readiness = api_readiness(cfg)
    if not readiness.ready:
        return {"ok": False, "error": "Smartsheet API configuration is incomplete.", "problems": list(readiness.problems)}
    key = submission_fingerprint(fields, attachments)
    try:
        rows = _search_rows_for_key(cfg, key)
        if not rows:
            return {
                "ok": False,
                "not_found": True,
                "submission_key": key,
                "error": "No indexed Smartsheet row contains this exact submission key yet. Search indexing can lag; wait and try again before creating anything manually.",
            }
        if len(rows) > 1:
            return {
                "ok": False,
                "multiple": True,
                "submission_key": key,
                "row_ids": rows,
                "error": "Multiple rows contain this submission key. An administrator must reconcile the duplicates.",
            }
        history = store or SubmissionStore.from_environment()
        history.reconcile_row(key, rows[0])
        return {"ok": True, "submission_key": key, "row_id": rows[0]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "submission_key": key, "error": _error_text(exc)}


def _ambiguous_write_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status is None or status in {408, 425, 429} or (isinstance(status, int) and status >= 500)


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
        return {"ok": False, "error": "Smartsheet API configuration is incomplete.", "problems": list(readiness.problems)}

    problems = list(validate_submission_fields(fields))
    missing = missing_required_fields(fields, cfg.required_fields)
    if missing:
        problems.append("Required values are missing: " + ", ".join(missing))
    problems.extend(preflight_attachments(files))
    if problems:
        return {"ok": False, "error": "Submission preflight failed.", "problems": problems}

    key = submission_fingerprint(fields, files)
    enriched = dict(fields)
    enriched["submission_key"] = key
    history = store or SubmissionStore.from_environment()
    lease_token: str | None = None

    try:
        columns = get_columns(cfg)
        mapping_problems, columns_by_id = _column_problems(cfg, columns)
        if mapping_problems:
            return {"ok": False, "error": "Live sheet mapping changed.", "problems": mapping_problems}
        cells, cell_problems = _build_cells(enriched, cfg, columns_by_id)
        if cell_problems:
            return {"ok": False, "error": "One or more values do not match the live column types.", "problems": cell_problems}
        if not cells:
            return {"ok": False, "error": "No populated values map to writable columns."}

        history.cleanup()
        claim = history.claim(key)
        lease_token = claim.lease_token
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
            if claim.reason == "uncertain":
                return {
                    "ok": False,
                    "uncertain": True,
                    "submission_key": key,
                    "error": claim.last_error or "A prior row-creation request had an unknown outcome. Reconcile it before retrying.",
                }
            return {
                "ok": False,
                "in_progress": True,
                "submission_key": key,
                "error": "This PO is already being processed by another request.",
            }
        if not lease_token:
            raise SubmissionStoreError("Smartsheet submission lease was not issued.")

        row_id = claim.row_id
        if not row_id:
            try:
                row = _create_row(cfg, cells)
                row_id = str(row["id"])
            except Exception as exc:  # noqa: BLE001
                status = "uncertain" if _ambiguous_write_error(exc) else "failed"
                history.finish(key, lease_token, status, _error_text(exc))
                return {
                    "ok": False,
                    "uncertain": status == "uncertain",
                    "submission_key": key,
                    "error": (
                        "Smartsheet may have created the row, but the response was not conclusive. Use reconciliation before retrying. "
                        if status == "uncertain"
                        else "Smartsheet rejected the row. "
                    ) + _error_text(exc),
                }
            try:
                history.record_row(key, lease_token, row_id)
            except SubmissionStoreError as exc:
                return {
                    "ok": False,
                    "uncertain": True,
                    "row_id": row_id,
                    "submission_key": key,
                    "error": f"Row {row_id} was created, but local duplicate-prevention state could not record it. Do not submit again until reconciled. {exc}",
                }

        history.renew(key, lease_token)
        remote_names = _row_attachment_names(cfg, row_id)
        attached = set(claim.attached)
        for filename, data in files:
            fingerprint = _attachment_fingerprint(filename, data)
            if fingerprint not in attached and _remote_has_attachment(remote_names, filename, data):
                history.record_attachment(key, lease_token, fingerprint)
                attached.add(fingerprint)

        skipped: list[str] = []
        for filename, data in files:
            fingerprint = _attachment_fingerprint(filename, data)
            if fingerprint in attached:
                continue
            history.renew(key, lease_token)
            try:
                _attach_file(cfg, row_id, filename, data)
            except Exception as exc:  # noqa: BLE001
                # The upload response may have been lost. Re-list the row before
                # deciding whether another attempt is safe.
                try:
                    remote_names = _row_attachment_names(cfg, row_id)
                except Exception:
                    remote_names = set()
                if _remote_has_attachment(remote_names, filename, data):
                    history.record_attachment(key, lease_token, fingerprint)
                    attached.add(fingerprint)
                    continue
                skipped.append(f"{_safe_filename(filename)}: {_error_text(exc)}")
                continue
            history.record_attachment(key, lease_token, fingerprint)
            attached.add(fingerprint)

        if skipped:
            history.finish(key, lease_token, "partial", "; ".join(skipped))
        else:
            history.finish(key, lease_token, "complete")
        return {
            "ok": True,
            "duplicate": False,
            "partial": bool(skipped),
            "row_id": row_id,
            "attached": len(attached),
            "skipped_attachments": skipped,
            "submission_key": key,
        }
    except SubmissionStoreError as exc:
        return {
            "ok": False,
            "error": "Submission was blocked because duplicate-prevention state is unavailable or untrusted. " + str(exc),
            "submission_key": key,
        }
    except Exception as exc:  # noqa: BLE001
        if lease_token:
            try:
                history.finish(key, lease_token, "failed", _error_text(exc))
            except Exception:
                pass
        return {"ok": False, "error": _error_text(exc), "submission_key": key}


_STATUS_HINTS = {
    401: "The API token is missing, expired, or invalid.",
    403: "The token account does not have permission to edit this sheet.",
    404: "The sheet or row is not visible to the configured token account.",
    413: "The request or attachment is too large for Smartsheet.",
    429: "Smartsheet is rate-limiting the integration; wait before retrying.",
}


def _error_text(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        text = str(exc) or exc.__class__.__name__
        return text[:500]
    status = getattr(response, "status_code", None)
    message = None
    try:
        body = response.json()
        if isinstance(body, dict):
            message = body.get("message") or (body.get("error") or {}).get("message")
    except Exception:
        pass
    text = str(message or (f"HTTP {status}" if status else exc))[:400]
    hint = _STATUS_HINTS.get(status)
    return f"{text} {hint}".strip() if hint else text
