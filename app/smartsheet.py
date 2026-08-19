"""Fail-closed three-mode Smartsheet handoff for ENFRA PO intake.

The live PO form's labels, required inputs, and job choices are represented
exactly. Manual copy/paste is enabled when the verified form URL is configured;
URL prefilling and direct API submission remain independently gated. Production
API writes require explicit column IDs, exact titles/types, a submission-key
column, strict cell parsing, persistent leases, and verified attachments.

Who depends on this module:

* ``app/smartsheet_inline.py`` -- the only production caller. It uses the
  manual/prefill half (``load_config``, ``manual_enabled``, ``prefill_enabled``,
  ``build_prefilled_form_url``, ``handoff_rows``, ``download_names``).
* ``app/web_ui.py`` -- imports only ``MAX_ATTACHMENT_BYTES``,
  ``preflight_attachments`` and ``validate_submission_fields``, so the uploader
  cap and the "would Smartsheet have accepted this?" gate that guards device
  memory use exactly the same rules as the handoff.
* The API half (``submit_po``, ``reconcile_submission``,
  ``validate_column_mapping``) is deployed with ``SMARTSHEET_API_MODE=disabled``
  and is exercised only by tests and by an operator running a recovery step.
  It is NOT dead: the whole point of the three-mode design is that turning the
  mode on must not require writing new code under time pressure.

Every configuration parser here raises rather than defaulting. A Smartsheet
misconfiguration that "mostly works" is the failure this module exists to
prevent -- a form that opens with blank fields, or a row written into a renamed
column, produces no error anyone sees.
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
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

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
# Smartsheet's published attachment ceiling. web_ui.py converts this to whole
# megabytes for the uploader cap so an oversized quote is rejected BEFORE OCR
# and model analysis are paid for -- see FM-A12.
MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024
# Smartsheet TRUNCATES a longer cell rather than rejecting it, so an over-long
# scope would land as a silently incomplete row. Preflight blocks instead.
MAX_CELL_CHARS = 4000
# Not a Smartsheet limit -- a browser/proxy one. Chrome, Safari and corporate
# proxies all cut long URLs at different, undocumented points, and a cut URL
# opens the form with the tail fields blank and no error. 7,000 is the
# conservative floor across the observed set.
DEFAULT_PREFILL_MAX_URL_LENGTH = 7000

# The EXACT visible labels on the live PO form, mapped from this codebase's
# logical field names. These are used for the manual copy fallback and for the
# error text an operator reads; the prefill URL uses the administrator-supplied
# SMARTSHEET_FORM_FIELD_MAP_JSON instead, because a form revision can rename a
# label without anyone redeploying. Keep both in sync when the form changes.
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
# The registry every configuration key is checked against. A misspelled logical
# field in an environment variable is REJECTED at load time rather than being
# quietly ignored -- an ignored key means a value silently never reaches the
# form (FM-E03).
KNOWN_FIELDS = frozenset(DISPLAY_LABELS)
# Business policy, not a technical limit: purchasing fills these in after the
# request lands. Prefilling them would make the requester look like they had
# already been assigned a PO number. They are stripped from the prefill URL and
# the copy list, and a populated value is reported as a validation problem, so
# an upstream change that starts emitting them fails loudly.
ALWAYS_BLANK_FIELDS = frozenset(
    {
        "leave_request_completed",
        "po_number",
        "work_order_number",
    }
)

# The live form's actual top-to-bottom tab order. It drives the copy-in-order
# fallback (an operator tabbing down the real form) and the order fields are
# added to the prefill URL, which decides WHICH field gets dropped when the URL
# length ceiling is hit -- later fields lose. Pinned by
# tests/test_smartsheet_config.py; changing it requires re-checking the form.
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

# The form's own red-asterisk fields. Deliberately a SEPARATE list from
# DEFAULT_FORM_ORDER and from SMARTSHEET_REQUIRED_FIELDS (the API list): the
# form and the sheet can disagree about what is mandatory, and collapsing them
# into one list would let a form-only requirement disappear the day the API
# list is edited. original_po_number is absent on purpose -- it is required
# only for CHANGE ORDER, which missing_required_fields adds conditionally.
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
# Dropdown values must match the form's options CHARACTER FOR CHARACTER. A
# near-miss ("5301 MATERIALS" for "5301-MATERIALS") does not raise -- Smartsheet
# opens the form with that dropdown left on its placeholder, which looks like
# the tool simply chose not to fill it. Hence exact-membership validation, and
# no normalization or fuzzy matching anywhere in this module.
# dispatch_service_center is a single-option tuple because business policy locks
# it to NA; it is a tuple rather than a constant so a future second option is a
# one-line change here instead of a new code path.
_EXACT_OPTIONS: dict[str, tuple[str, ...]] = {
    "request_type": REQUEST_TYPE_OPTIONS,
    "job_number": JOB_NUMBER_OPTIONS,
    "object_account": OBJECT_ACCOUNT_OPTIONS,
    "agreement_type": AGREEMENT_TYPE_OPTIONS,
    "dispatch_service_center": ("NA",),
}

_AMOUNT_FIELDS = {"total"}
# _DATE_FIELDS and _BOOLEAN_FIELDS are EMPTY because the current PO form has no
# date or checkbox input. They are kept rather than deleted because _cell_value
# still reaches _iso_date/_boolean via the LIVE column's declared type: a sheet
# whose column is DATE or CHECKBOX is converted correctly even though no logical
# field is listed here. Deleting these sets would force the type dispatch to be
# rewritten the first time an administrator adds such a column.
_DATE_FIELDS: set[str] = set()
_EMAIL_FIELDS = {"contact_email"}
_BOOLEAN_FIELDS: set[str] = set()
_ALLOWED_API_MODES = {"disabled", "dry_run", "live"}
_ALLOWED_ROW_POSITIONS = {"top", "bottom"}
# Deliberately permissive. This is a typo guard for a vendor contact address the
# operator retyped, not an RFC 5322 validator; a stricter pattern would reject
# real vendor addresses and block the handoff on a field the form itself accepts.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# Allowlist, not a denylist: anything outside this set becomes "_". Spaces,
# parentheses and square brackets are ALLOWED on purpose -- the download names
# and the "[EPC-<fingerprint>]" API attachment name both rely on them, and the
# name is later embedded unquoted in a Content-Disposition header, so the set
# must stay free of quotes, semicolons, newlines and path separators.
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._()\[\] -]+")


class SmartsheetConfigurationError(ValueError):
    """Raised when optional Smartsheet configuration is unsafe or inconsistent."""


@dataclass(frozen=True)
class ColumnSpec:
    """One live sheet column, identified by ID *and* re-verified by title/type.

    The ID alone is not enough. Smartsheet keeps a column's ID when an
    administrator renames or repurposes it, so a stale mapping would keep
    writing successfully into the wrong column (FM-E01). ``title`` and ``type``
    are compared against the live sheet before every write; empty strings mean
    "not yet confirmed" and are rejected by ``api_readiness``.

    ``options`` is optional and is checked as a SUBSET of the live picklist:
    the sheet may legitimately have gained options, but losing one we depend on
    must block the write.
    """

    id: int
    title: str
    type: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SmartsheetConfig:
    """Fully validated Smartsheet settings; construct only via ``load_config``.

    Frozen because several call sites hold it across Streamlit reruns and a
    mutated copy would let the API-base and form-URL safety checks in
    ``load_config`` be bypassed after the fact.

    The three routes are independently gated and never imply one another:
    a form URL enables manual copy, ``prefill_enabled`` additionally needs the
    exact label map, and the API route needs ``api_mode == "live"`` plus a
    complete ``api_readiness``.
    """

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
        """Field -> column ID, dropping the title/type verification.

        Currently unused by application code. It exists as the read-only
        accessor for operator/debug output; do not route writes through it,
        because an ID without its verified title and type is exactly the input
        that FM-E01 (renamed column, same ID) turns into a silent bad write.
        """
        return {field: spec.id for field, spec in self.column_specs.items()}


@dataclass(frozen=True)
class PrefillResult:
    """Outcome of building one prefilled form URL.

    ``included`` is what actually made it into the encoded query -- NOT what was
    populated. ``skipped`` carries a human reason per dropped field. A required
    field that is populated but not in ``included`` appears in
    ``missing_required``, and callers must withhold the link entirely in that
    case: handing over a link that silently drops a mandatory value is worse
    than handing over nothing (FM-D06).
    """

    url: str
    included: tuple[str, ...]
    skipped: tuple[str, ...]
    missing_required: tuple[str, ...]


@dataclass(frozen=True)
class ApiReadiness:
    """Whether a live API write is permitted, with every reason it is not.

    ``problems`` is returned in full rather than as a single message so an
    operator configuring the integration sees the complete list at once instead
    of fixing one item per deploy.
    """

    ready: bool
    mode: str
    problems: tuple[str, ...]


def _text(env: Mapping[str, str], name: str) -> str | None:
    """Read one env value, treating whitespace-only as absent."""
    value = str(env.get(name, "")).strip()
    return value or None


def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    """Parse a boolean env flag, RAISING on anything unrecognized.

    Deliberately not ``value.lower() in {"1", "true", ...}``. That idiom turns
    a typo such as ``SMARTSHEET_URL_PREFILL_ENABLED=ture`` into a silent
    ``False``, which presents as "prefill just stopped working" with no error
    anywhere in the logs or the UI.
    """
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
    """Parse a bounded integer env value; raise rather than clamp.

    Clamping would let ``SMARTSHEET_PREFILL_MAX_URL_LENGTH=70`` become a working
    configuration that drops every field from the URL.
    """
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
    """Parse a JSON-object env value; ``{}`` when unset, raise when malformed.

    The character offset is included in the error because these values are
    single-line JSON blobs pasted into a Render dashboard field, where a
    truncated paste is the common failure and is otherwise unlocatable.
    """
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
    """Reject any logical field name outside KNOWN_FIELDS.

    The rejection is the point. Silently dropping an unrecognized key would let
    ``"requestor_name"`` sit in the deployed label map forever while the
    REQUESTER box on the form stays empty (FM-E03).
    """
    if not isinstance(field, str) or field.strip() not in KNOWN_FIELDS:
        raise SmartsheetConfigurationError(
            f"{source} contains unknown logical field {field!r}."
        )
    return field.strip()


def _csv_fields(env: Mapping[str, str], name: str) -> tuple[str, ...]:
    """Parse a comma-separated logical-field list, preserving its order.

    Order is meaningful for SMARTSHEET_FORM_ORDER (it is the operator's tab
    order and the URL-truncation priority), so this returns a tuple rather than
    a set. Duplicates raise: a repeated field would silently reorder the copy
    list relative to the real form.

    Returns ``()`` when unset. Callers treat empty as "use the default", so an
    env value of ``",,,"`` also falls back to the default rather than producing
    an empty order.
    """
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
    """Accept only an absolute HTTPS URL on a Smartsheet host; None if unset.

    The host check uses ``hostname`` (not ``netloc``) and requires an exact
    match or a dotted suffix, so ``evil-smartsheet.com`` and
    ``smartsheet.com.evil.test`` are both rejected. This URL is what the
    operator is told to open and paste PO data into, so a lookalike host would
    be a credible phishing target.
    """
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
    """Pin the API host, returning it without a trailing slash.

    A custom base is permitted ONLY when the mode is not ``live`` and the
    operator has explicitly opted in -- that combination exists so an integration
    test can point at a local stub. In ``live`` mode the real bearer token is
    attached to every request, so ``allow_custom`` is ignored entirely and the
    host is forced (FM-E09). Do not "simplify" the condition to a single
    ``allow_custom`` check; that would let one dashboard flag exfiltrate the
    token.
    """
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
    """Build the verified column map from either the new or the legacy env var.

    SMARTSHEET_COLUMN_SPECS_JSON wins outright when present; the legacy
    ID-only SMARTSHEET_COLUMN_MAP_JSON is read only when the new variable is
    absent, and yields specs with EMPTY title/type. That is intentional: empty
    title/type is what ``api_readiness`` reports as "needs exact title and
    type", so an old ID-only deployment cannot silently start writing rows
    without someone re-confirming the live schema first.

    Raises on non-positive or duplicated IDs -- two logical fields sharing one
    column ID means one of them silently overwrites the other (FM-E02).
    """
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
    """Validate every Smartsheet env var and return one frozen config.

    Guarantees: the returned config is internally consistent and safe to act on
    -- form URL on a Smartsheet host, API base pinned when live, no unknown
    logical fields, no duplicate labels, no duplicate column IDs.

    Assumes nothing about deployment: ``load_config({})`` is a valid, fully
    inert configuration (no manual route, no prefill, API disabled). That is
    what tests/test_smartsheet_config.py pins, and it is what makes a
    misconfigured deploy fall back to "no Smartsheet handoff" rather than to a
    half-working one.

    On any invalid value it RAISES SmartsheetConfigurationError; it never
    returns a partially valid config. Callers are expected to surface the
    message to the operator.

    ``env`` is injectable for tests; production passes None and reads
    ``os.environ``.
    """
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

    # Per-field translation from this codebase's canonical value to whatever the
    # form's dropdown actually displays (FM-D04). Currently unset in render.yaml
    # because the two vocabularies match exactly. Before enabling it, read the
    # warning on handoff_rows: the manual copy fallback does NOT apply this map.
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
    """Whether the operator may be shown a form link at all.

    A verified form URL is the only requirement: the manual copy fallback works
    even when prefill has never been configured, which is the state the
    integration shipped in and must keep working in.
    """
    return bool(config.form_url)


def prefill_enabled(config: SmartsheetConfig) -> bool:
    """Whether values may be encoded into the form URL.

    The label map is part of the gate, not an optimization. Without exact
    administrator-supplied labels there is nothing to encode against, and
    guessing a parameter name would fill the WRONG form field with no error
    (FM-D01). Prefill therefore stays off until a real form revision has been
    retested, independently of the manual route.
    """
    return bool(config.form_url and config.prefill_enabled and config.form_field_map)


def api_readiness(config: SmartsheetConfig) -> ApiReadiness:
    """Collect every reason a live API write must not happen.

    Returns ``ready=False`` with a non-empty ``problems`` tuple unless the token,
    sheet ID, explicit column specs, confirmed required-field list, a dedicated
    submission_key column, and an exact title/type for every spec are all
    present. ``ready=True`` never means the sheet is correct -- only that the
    configuration is complete enough for ``_column_problems`` to check it
    against the live sheet.

    The submission_key requirement is not optional: without a durable key cell
    in the sheet, an ambiguous write (FM-F04) can never be reconciled after
    local state is lost, and the only remaining recovery is a human comparing
    rows by eye.
    """
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
    """Whitespace-only counts as empty -- a space typed into a required box is
    not a value, and Smartsheet would accept it as one."""
    return value is not None and str(value).strip() != ""


def _must_remain_blank(field: str, fields: Mapping[str, Any]) -> bool:
    """Whether policy forbids sending this field for THIS request.

    Two rules, one function, because every route (prefill, copy list, cell
    build, validation) must apply exactly the same test. The second rule is
    request-type dependent: ORIGINAL PO NUMBER belongs on a CHANGE ORDER and
    nowhere else. Sending it on a plain PO makes the request look like an
    amendment to a PO that does not exist, and purchasing has no way to tell
    that the tool volunteered it.

    The comparison is against the exact string "CHANGE ORDER" from
    REQUEST_TYPE_OPTIONS -- not a substring or case-insensitive test -- so an
    unexpected request_type value fails toward "must remain blank".
    """
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
    # Case-insensitive second pass, exact-match first. The map is hand-typed
    # into a dashboard field, so "PO" vs "po" is a likely transcription slip;
    # matching it is safer than silently sending the untranslated value into a
    # dropdown that has no such option. Exact match still wins so a map that
    # deliberately distinguishes case is not broken by this leniency.
    lowered = text.lower()
    for source, replacement in mappings.items():
        if source.lower() == lowered:
            return replacement
    return text


def missing_required_fields(
    fields: Mapping[str, Any], required_fields: Sequence[str]
) -> tuple[str, ...]:
    """Required names with no populated value, in the caller's order.

    ``required_fields`` is supplied by the caller because the FORM's mandatory
    list and the SHEET's mandatory list are configured separately and can
    legitimately differ.

    Adds ``original_po_number`` for a CHANGE ORDER even when the caller's list
    omits it, since that requirement is business policy rather than form
    configuration. Returns ``()`` when nothing is missing.
    """
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
    """Every rule Smartsheet would enforce, checked before anything is sent.

    Returns operator-readable problems using the form's own visible labels, or
    ``()`` when the payload would be accepted. It checks only fields PRESENT in
    the mapping -- absence is ``missing_required_fields``'s job, and the two are
    deliberately separate so a draft can be validated before it is complete.

    Keys outside KNOWN_FIELDS are skipped rather than rejected: callers pass the
    whole PO context, which also carries workflow-only values (contract, site,
    subtotal, scope text) that never reach Smartsheet.

    Also used by web_ui.py as the gate on teaching device memory, so a rule
    added here tightens what the app is willing to remember as well.
    """
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
        # 20 is the live form's own input cap on this box, not a guess. The full
        # scope is NOT lost -- it lives in the attached MSAPO form PDF. Raising
        # this number lets Smartsheet truncate the cell instead (FM-A08), which
        # produces a plausible-looking short description with no error.
        if field == "description_of_work" and len(text) > 20:
            problems.append("DESCRIPTION OF WORK must be 20 characters or fewer.")
        # Local safety bound, not a Smartsheet one: asset IDs are short codes,
        # so anything past 160 characters means the asset guesser concatenated
        # unrelated quote text and the value should be looked at by a human.
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

    This is a real production incident, not a theoretical one: the form opened
    correctly and every field was blank, because nearly every live label
    contains a space. Nothing errored -- Smartsheet treats an unrecognized
    parameter as an ordinary form open.

    The PR #31 tests missed it because they called ``parse_qs`` on the result,
    and form-style decoding treats ``+`` and ``%20`` as the same character, so
    the test erased the exact distinction that mattered. The current tests
    assert on the RAW query string for that reason; restoring ``quote_plus``
    here will fail them even though the decoded dict still looks right.

    Note that ``urlencode`` passes ``safe=""`` to ``quote_via``, so ``/`` in
    "SITE NUMBER / LOCATION" is escaped despite ``quote``'s own default of
    ``safe="/"``. Calling ``quote`` directly here would NOT escape it.
    """
    return urlencode(query_items, doseq=True, quote_via=quote)


def build_prefilled_form_url(
    fields: Mapping[str, Any], config: SmartsheetConfig
) -> PrefillResult:
    """Encode populated values into the configured form URL.

    Guarantees: only exact administrator-configured labels are emitted; blank-by-
    policy fields are never included; an existing value for a mapped label in the
    base URL is REPLACED rather than duplicated (FM-D02); unrelated query
    parameters on the base URL survive; and the final URL never exceeds
    ``config.prefill_max_url_length``.

    Raises SmartsheetConfigurationError when the route is not fully configured,
    rather than returning a bare form link that looks prefilled but is not.

    IMPORTANT: ``config.form_order`` is an ORDERING, not a whitelist. The loop
    also walks ``fields.keys()``, so a field absent from form_order is still
    encoded -- just last, which makes it the first casualty of the length limit.
    Shortening form_order to "exclude" a field does nothing; use
    ``_must_remain_blank`` or drop the label mapping instead.
    """
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
    # Drop any pre-existing parameter whose key is one of OUR labels, keep the
    # rest. The configured base URL legitimately carries tracking parameters
    # (e.g. a source tag); duplicating a mapped label instead would leave the
    # form's behaviour undefined -- it may take the first or the last (FM-D02).
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
        # Measure the FULLY ENCODED candidate URL, using the same encoder as the
        # final one. Measuring the raw text instead understates the length by up
        # to 3x once spaces and "&" become %20 and %26, and the resulting link
        # is cut by the browser mid-parameter -- the form then opens with the
        # tail fields blank and nothing reports a problem.
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
            # Skip and keep going rather than break: fields are attempted in form
            # order, and a shorter later field may still fit once an oversized
            # one is dropped.
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
    # A required field counts as missing when it is empty OR when it is populated
    # but did not survive encoding -- an unmapped label or a length skip. Testing
    # only ``_nonempty`` here was the original bug: the value existed in the app,
    # so nothing complained, and the operator opened a link whose mandatory box
    # was empty. ``field not in included`` is the half that catches it.
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
    """(field, visible label, value) triples in the form's own tab order.

    Feeds the manual copy fallback, so the operator can walk the real form top
    to bottom. Blank-by-policy and empty values are omitted; the label falls
    back to DISPLAY_LABELS when the administrator has not mapped that field, so
    the copy list still works on a deployment where prefill was never enabled.

    Values pass through ``_mapped_value``, the SAME translation
    ``build_prefilled_form_url`` applies. This list exists to be TYPED INTO THE
    REAL FORM, so it has to carry strings the form's dropdowns actually offer.

    It previously emitted raw values, on the reasoning that these rows are also
    an audit view of what the tool holds. That made the copy fallback and the
    prefill URL disagree the moment SMARTSHEET_FORM_VALUE_MAP_JSON was
    configured -- and disagree silently, with the operator typing a value the
    dropdown would reject. The audit view is still available from the PO
    context, which is where an untranslated record belongs.

    With no map configured -- the state today, the example in .env.example is
    commented out -- ``_mapped_value`` returns the stripped string unchanged, so
    this is identical to the previous behaviour until the map is enabled.
    """
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
        rows.append((field, label, _mapped_value(config, field, value)))
    return rows


def _safe_filename(filename: str, default: str = "attachment") -> str:
    """Reduce an untrusted upload name to a safe, stable ASCII filename.

    The input is a vendor's filename from a browser upload, so it may contain
    path traversal, CR/LF (header injection into Content-Disposition), or
    reserved punctuation -- FM-B04. ``Path(...).name`` strips directories, the
    explicit CR/LF removal runs BEFORE the regex so a newline can never survive
    as a literal, and the trailing ``strip(" .")`` exists because Windows
    silently drops trailing dots and spaces when saving.

    This function is IDEMPOTENT, and that property is load-bearing:
    ``_attachment_fingerprint`` sanitizes internally while
    ``_api_attachment_name`` also sanitizes before calling it, so a second pass
    must produce the identical string or the local dedup fingerprint and the
    remote name would stop agreeing and every resume would re-upload.
    """
    name = Path(str(filename or "")).name.replace("\r", "").replace("\n", "").strip()
    name = _SAFE_FILENAME_RE.sub("_", name).strip(" .")
    return name[:180] or default


def download_names(
    attachments: Sequence[tuple[str, bytes]], base: str
) -> list[tuple[str, str, bytes]]:
    """Rename the package for download as "<stem> <n> <kind><ext>".

    Positional by contract: the caller guarantees attachment 1 is the unchanged
    vendor quote and attachment 2 is the generated MSAPO form PDF, and
    ``smartsheet_inline`` refuses to render anything other than exactly two.
    Bytes are passed through untouched -- only the presented name changes, so
    the file the operator uploads is byte-identical to the one analyzed.
    """
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
        # The second attachment is the MSAPO agreement form, not the former
        # simplified scope sheet, so the file the operator hands to Smartsheet
        # is named for what it actually is. The stem regex above already
        # tolerates either word, so a base built before this change still
        # normalizes correctly.
        kind = "Quote" if index == 1 else "MSAPO"
        label = f"{kind} · {extension.lstrip('.').upper()}" if extension else kind
        result.append((label, f"{stem} {index} {kind}{extension}", data))
    return result


def preflight_attachments(
    attachments: Sequence[tuple[str, bytes]]
) -> tuple[str, ...]:
    """Reject empty, oversized, or name-colliding attachments (FM-B03).

    Returns operator-readable problems, or ``()`` when the set would upload
    cleanly. Also called by web_ui.py as one of the three independent gates on
    teaching device memory.

    Duplicate detection compares the SANITIZED, case-folded name, because that
    is what Smartsheet stores -- two uploads that differ only by a character
    ``_safe_filename`` collapses would land as indistinguishable attachments on
    the same row, and nobody could tell which one purchasing opened.
    """
    problems: list[str] = []
    seen_names: set[str] = set()
    for filename, data in attachments:
        safe_name = _safe_filename(filename)
        # Register the name BEFORE the empty-file bail-out. Registering after
        # it meant an empty "quote.pdf" never entered seen_names, so a second,
        # valid "quote.pdf" in the same package was not reported as a
        # duplicate -- the operator fixed the empty file, resubmitted, and only
        # then learned about the name collision. This function exists to report
        # every problem in ONE pass; bailing early made it report them serially.
        folded = safe_name.casefold()
        if folded in seen_names:
            problems.append(f"Attachment filename is duplicated: {safe_name}.")
        seen_names.add(folded)
        if not isinstance(data, bytes) or not data:
            problems.append(f"{safe_name} is empty or unreadable.")
            continue
        if len(data) > MAX_ATTACHMENT_BYTES:
            problems.append(
                f"{safe_name} is larger than Smartsheet's 30 MB attachment limit."
            )
    return tuple(problems)


def _headers(config: SmartsheetConfig, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Bearer auth plus the integration-source tag Smartsheet attributes writes to.

    The token is only ever reachable here after ``_validate_api_base`` has
    pinned the host for live mode, so this must not be called with a
    caller-supplied URL. Never log the returned dict.
    """
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "smartsheet-integration-source": "APPLICATION,ENFRA,PurchaseOrderProcessControl",
    }
    if extra:
        headers.update(extra)
    return headers


def _retry_after(response: Any, attempt: int) -> float:
    """Seconds to wait, honouring Retry-After but never trusting it blindly.

    Capped at 30s so a hostile or mistaken header cannot park a Streamlit rerun
    indefinitely, floored at 0 so a negative value cannot reach ``time.sleep``.
    RFC 7231 also permits an HTTP-date here; ``float()`` raises on that and the
    exponential fallback covers it, which is why the except clause is not
    "unnecessary defensive code".
    """
    raw = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
    try:
        return min(30.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return float(min(8, 2 ** attempt))


def _safe_get(config: SmartsheetConfig, url: str, **kwargs) -> requests.Response:
    """GET with bounded retries on 429/5xx and on transport errors.

    READ-ONLY calls only. Retrying a read is free; retrying a write is how
    duplicate rows and duplicate attachments get created, which is why
    ``_create_row`` and ``_attach_file`` deliberately do NOT use this helper and
    call ``requests.post`` directly. Do not "unify" them.

    Raises the underlying ``requests`` exception once the three attempts are
    exhausted, so callers can inspect ``exc.response`` for status.
    """
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
    """Fetch the live sheet's columns.

    ``includeAll=true`` matters: without it Smartsheet paginates and a column
    past the first page would be reported as "not found", which
    ``_column_problems`` would surface as schema drift on a perfectly healthy
    sheet. ``level=2`` is what makes multi-picklist options appear.

    Monkeypatched by tests/test_smartsheet_api.py, so it must stay a
    module-level name rather than becoming a method or an inlined call.
    """
    response = _safe_get(
        config,
        f"{config.api_base_url}/sheets/{config.sheet_id}/columns",
        params={"includeAll": "true", "level": 2},
    )
    return response.json().get("data", [])


def _column_problems(
    config: SmartsheetConfig, columns: Sequence[dict]
) -> tuple[list[str], dict[int, dict]]:
    """Compare the configured specs against the live sheet.

    Returns (problems, columns keyed by ID). Every configured column must exist
    and match on exact title and exact upper-cased type, must not be locked for
    the token account, and must not be a system or formula column -- a write to
    any of those either fails or, worse, appears to succeed while Smartsheet
    recomputes the cell.

    Expected picklist options are checked as a SUBSET: the sheet gaining an
    option is fine, losing one we send is not.
    """
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
    """Operator diagnostic: does the configuration still match the live sheet?

    Returns ``{"ok": bool, "mapped": {...}, "problems": [...]}`` and never
    raises -- network and API failures are converted to a problem string so the
    caller can display them.

    Not called by the running app (the API route is disabled in production).
    It is the tool an administrator runs after a sheet edit, and the read-only
    counterpart to the same check ``submit_po`` performs inline before every
    write. Keep the two in step: they share ``_column_problems`` for exactly
    that reason.
    """
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
    """Strict currency parse; raises rather than repairing bad input.

    Delegates to the ONE parser in po_rules so classification, PO context
    reconciliation and Smartsheet validation cannot disagree about what
    "$1,234.56" or "1e3" means (FM-A09). Do not add a local fallback here.

    The Decimal is narrowed to float only at this boundary because that is what
    the JSON body must carry; every arithmetic and threshold decision (notably
    the $25,000 Standard PO boundary) happens on the Decimal upstream.
    """
    amount = parse_amount(value)
    if amount is None or amount <= 0:
        raise ValueError("must be a valid amount greater than $0.00")
    return float(amount)


def _iso_date(value: Any) -> str:
    """Normalize to ISO for a Smartsheet DATE cell, or raise.

    Only the two unambiguous US-office formats are accepted, ISO first. Adding
    ``%d/%m/%Y`` would make 03/04/2026 parse silently as the wrong day -- a
    date error that reads as perfectly valid in every downstream report.
    """
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
    """Convert one value to the type the LIVE column actually declares.

    Raises ValueError with an operator-readable reason; the caller turns that
    into a blocking problem. Nothing here coerces silently, because every cell
    is written with ``strict: True`` and the alternative -- Smartsheet's lenient
    mode -- stores a date or an amount as plausible-looking TEXT that reads
    correctly to a human and sorts and filters wrongly forever (FM-E06).

    Dispatch order is deliberate: the amount check comes first because "total"
    must be a number regardless of how the column is declared, then the live
    column type decides date/checkbox/contact handling, and picklist membership
    is validated against the sheet's own options rather than our copy of them.
    """
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
    """Build the strict cell list for one row, plus any per-value problems.

    Iterates the CONFIGURED specs rather than the supplied fields, so a value
    with no confirmed column is never written to a guessed one.

    Every cell carries ``"strict": True``. Removing that flag would make the
    whole typed-conversion path above pointless: Smartsheet would accept the
    text form of anything and the row would look fine.

    The ``if not column: continue`` branch is unreachable from ``submit_po``
    (``_column_problems`` has already blocked a missing column ID), but it is
    the fail-safe if a future caller skips that step.
    """
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
    """Create exactly one row. NOT retried, at any level, on purpose.

    A lost response to this call is indistinguishable from a rejection, and the
    remote row may well exist. Retrying is how you get two POs for one quote.
    The caller classifies the failure with ``_ambiguous_write_error`` and parks
    the submission in ``uncertain`` for human reconciliation (FM-F04) instead.

    Also refuses to guess at the response shape: Smartsheet returns ``result``
    as an object or a single-element list depending on the endpoint version, and
    anything else -- or a result without an ``id`` -- raises rather than being
    treated as success with an unknown row.
    """
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
    """Content+name identity used as the local "already attached" key.

    The NUL separator is not decorative: without it, ("ab", b"c") and
    ("a", b"bc") would hash identically, and a renamed file could be mistaken
    for one already uploaded and silently skipped.

    Sanitizes the name internally so callers may pass either the raw upload
    name or an already-sanitized one and still get the same digest -- see the
    idempotency note on ``_safe_filename``.
    """
    digest = hashlib.sha256()
    digest.update(_safe_filename(filename).encode("utf-8"))
    digest.update(b"\0")
    digest.update(data)
    return digest.hexdigest()


def _api_attachment_name(filename: str, data: bytes) -> str:
    """Deterministic remote name: "<stem> [EPC-<12 hex>]<ext>".

    The embedded fingerprint is what makes a lost upload response recoverable:
    the same file always produces the same remote name, so listing the row's
    attachments answers "did my upload land?" without a transaction (FM-B05).

    Consequences of changing this format: every row written under the old format
    stops de-duplicating, and the next resume uploads a second copy of both
    files. 12 hex characters is a deliberate balance -- enough to make an
    accidental collision irrelevant, short enough that the operator can still
    read the original filename in Smartsheet's attachment list.
    """
    safe = _safe_filename(filename)
    path = Path(safe)
    fingerprint = _attachment_fingerprint(safe, data)[:12]
    stem = path.stem[:140] or "attachment"
    return f"{stem} [EPC-{fingerprint}]{path.suffix.lower()}"


def _attach_file(
    config: SmartsheetConfig, row_id: str | int, filename: str, data: bytes
) -> None:
    """Upload one attachment under its deterministic name. Not retried here.

    Like ``_create_row``, a failure may still have stored the file remotely, so
    the caller re-lists the row and decides -- never this function.
    """
    api_name = _api_attachment_name(filename, data)
    mime = mimetypes.guess_type(api_name)[0] or "application/octet-stream"
    # Send the name verbatim, NOT percent-encoded. _api_attachment_name already
    # constrains the result to safe ASCII (see _SAFE_FILENAME_RE), so RFC 6266
    # needs no escaping here — while quote(..., safe="") turned every space and
    # bracket into %20/%5B. Smartsheet then stored and listed the escaped form,
    # so _remote_has_attachment (which compares the UNescaped name) could never
    # match, and the idempotent-resume path re-uploaded the same quote and scope
    # PDF on every retry until the row accumulated duplicates.
    response = requests.post(
        f"{config.api_base_url}/sheets/{config.sheet_id}/rows/{row_id}/attachments",
        headers=_headers(
            config,
            {
                "Content-Type": mime,
                "Content-Disposition": f'attachment; filename="{api_name}"',
                "Content-Length": str(len(data)),
            },
        ),
        data=data,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def _row_attachment_names(config: SmartsheetConfig, row_id: str | int) -> set[str]:
    """Names currently attached to a row -- the remote half of dedup.

    Monkeypatched by tests/test_smartsheet_api.py, so keep it module level.

    Accepts both response shapes because this endpoint has returned a bare JSON
    array as well as a ``{"data": [...]}`` envelope. Guessing wrong yields an
    EMPTY set, which reads as "nothing is attached yet" and re-uploads every
    file -- a silent duplication, not an error.
    """
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
    """Whether this exact attachment already exists on the row.

    Compares against the percent-decoded remote name as well as the raw one so
    that rows written before the Content-Disposition fix (whose stored names are
    percent-escaped) still de-duplicate instead of accumulating a second copy on
    the next resume.
    """
    expected = _api_attachment_name(filename, data)
    if expected in names:
        return True
    return any(unquote(name) == expected for name in names)


def submission_fingerprint(
    fields: Mapping[str, Any], attachments: Sequence[tuple[str, bytes]]
) -> str:
    """The deterministic submission key: identity of one exact PO payload.

    Stable across processes and machines -- sorted keys, stripped values, empty
    values dropped, ``ensure_ascii=False`` so a non-ASCII vendor name hashes the
    same everywhere. This same string is written into the sheet's submission_key
    column, which is the ONLY way an ambiguous write can be reconciled after
    local state is lost (FM-E08).

    ``submission_key`` itself is excluded from the input, or enriching the
    payload with the key would change the key.

    Any real change to the payload -- a corrected total, a re-uploaded quote --
    intentionally produces a NEW key and therefore a new row. That is FM-F07:
    an amended PO is a new submission, not an update to the old row.
    """
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
    """Rows whose submission_key CELL equals ``key`` exactly.

    Two-stage on purpose. Smartsheet's search is fuzzy and full-text: it can
    return a row because the key appears in a comment, an attachment name, or a
    neighbouring cell. Adopting a search hit directly would let reconciliation
    attach the wrong row ID to a submission, so every candidate is re-fetched
    and the submission_key cell is compared character for character.

    The quoted query is a phrase search, not an escape mechanism; ``key`` is
    always a hex digest from ``submission_fingerprint``.
    """
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
    """Recover local state for a submission whose remote outcome was unknown.

    The manual step out of ``uncertain`` (FM-F04/FM-F06). Never creates or edits
    a remote row; it only adopts one that has been positively identified by its
    exact submission_key cell.

    Returns ``ok=True`` with the row ID only when EXACTLY one row matches.
    ``not_found`` does NOT authorize creating a row -- Smartsheet's search index
    lags behind writes by an unbounded amount, so "no result" and "no row" are
    not the same statement. ``multiple`` requires an administrator, because the
    duplicate this was meant to prevent has already happened.
    """
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
    """Could this failed write still have taken effect remotely?

    Biased toward "yes" deliberately. ``status is None`` covers the timeout and
    connection-reset cases, where the request may have been fully processed and
    only the response was lost -- that is the dangerous one. 429 is included
    even though it usually means "rejected", because a proxy can return it after
    the origin already accepted the write.

    A false "yes" costs an operator one reconciliation step. A false "no"
    creates a second purchase order.
    """
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
    """Create or safely resume one Smartsheet row and its attachments.

    Never raises: every outcome is a dict the UI can render. ``ok`` alone is not
    the whole answer -- inspect ``duplicate``, ``partial``, ``uncertain`` and
    ``in_progress``. In particular ``ok=True, duplicate=True`` means "this exact
    payload was already submitted and nothing new was written", which is a
    success, and ``uncertain=True`` means a human must reconcile before ANY
    retry.

    Guarantees, in the order the body enforces them, and the order matters:

    1. Mode and readiness are checked before anything is computed.
    2. Field, required-value and attachment preflight run before any lease is
       taken, so a bad draft never consumes an attempt.
    3. The LIVE sheet schema is verified before the lease, so schema drift is
       reported instead of burning a claim.
    4. Only then is the submission claimed; from that point every mutation is
       lease-guarded and a lost lease aborts rather than proceeding.
    5. Attachments already present remotely are recorded, not re-uploaded.

    Reordering 3 and 4 looks tidier and is wrong: it makes every failed
    configuration check increment ``attempts`` and hold a 5-minute lease that
    blocks the operator's corrected retry.

    Currently reachable only with ``SMARTSHEET_API_MODE=live``, which production
    does not set; the deployed workflow uses the prefill/manual route instead.
    """
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

    # The key is computed from the CALLER's fields, then submission_key is added
    # to a copy for writing. Hashing the enriched dict instead would make the key
    # depend on itself; ``submission_fingerprint`` also drops the field for that
    # reason, so the two defences agree.
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

        # Retention pruning runs BEFORE the claim so a long-lived deployment does
        # not accumulate history forever. It only removes complete/failed records
        # past the retention window; partial and uncertain records are kept
        # regardless of age because they are the recovery evidence. The practical
        # consequence: re-submitting a byte-identical PO more than the retention
        # period later is treated as new. That is intended, not an oversight.
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
        # An allowed claim without a token would mean the store handed out
        # permission it cannot police. Raising here routes into the
        # SubmissionStoreError handler, which fails the submission closed; the
        # obvious alternative -- proceeding with lease_token=None -- would make
        # every subsequent owned update a no-op and silently disable the
        # concurrency guard for this write.
        if not lease_token:
            raise SubmissionStoreError("Smartsheet submission lease was not issued.")

        # A claim that carries a row ID is a RESUME: the row already exists and
        # its cells were written from this same fingerprint, so ``cells`` is
        # intentionally not rewritten. Resuming only finishes the attachments.
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

        # Reconcile REMOTE truth into local state before uploading anything. A
        # previous run may have stored a file and died before recording it; if
        # this pass were skipped, the resume would upload a second copy of a file
        # that is already on the row and nothing would ever report it.
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
            # Renew per file, not once per submission: a 30 MB upload over a slow
            # link can outlast the 5-minute lease, and an expired lease would let
            # a second worker start attaching to the same row.
            history.renew(key, lease_token)
            try:
                _attach_file(cfg, row_id, filename, data)
            except Exception as exc:  # noqa: BLE001
                # The upload response may have been lost. Re-list the row before
                # deciding whether another attempt is safe.
                try:
                    remote_names = _row_attachment_names(cfg, row_id)
                except Exception:
                    # Empty set == "cannot prove it landed" == leave the row
                    # partial. This swallow is safe ONLY because the fallback is
                    # the conservative answer; do not change it to re-raise or to
                    # assume the earlier listing is still valid.
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
    # A store failure is NOT finished as "failed" here, deliberately: writing a
    # final status through the same store that just failed is not trustworthy,
    # and marking a submission failed could unblock a retry of a write that may
    # already have landed. The lease simply expires instead.
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
                # Best effort. Losing the final status only means the lease
                # expires on its own; raising here would replace a specific
                # error message with a bookkeeping one.
                pass
        return {"ok": False, "error": _error_text(exc), "submission_key": key}


# Smartsheet's own error bodies are accurate but assume API-integration
# vocabulary. These append the operational meaning for the person reading the
# message in the UI, who cannot see the request.
_STATUS_HINTS = {
    401: "The API token is missing, expired, or invalid.",
    403: "The token account does not have permission to edit this sheet.",
    404: "The sheet or row is not visible to the configured token account.",
    413: "The request or attachment is too large for Smartsheet.",
    429: "Smartsheet is rate-limiting the integration; wait before retrying.",
}


def _error_text(exc: Exception) -> str:
    """One bounded, operator-readable line for any exception. Never raises.

    Length-capped because this string is stored in the submission history and
    rendered in a Streamlit alert; an unbounded HTML error page would make both
    unusable.

    ``str(exc)`` is used rather than ``repr``: requests exceptions embed the
    request URL, and the URL is the one place the token could not appear but the
    sheet ID does. Do not extend this to include headers.
    """
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
        # A non-JSON body (proxy HTML, empty 502) is normal here; falling through
        # to the status code is the intended path, not a swallowed bug.
        pass
    text = str(message or (f"HTTP {status}" if status else exc))[:400]
    hint = _STATUS_HINTS.get(status)
    return f"{text} {hint}".strip() if hint else text
