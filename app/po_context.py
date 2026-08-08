"""Build a verified Smartsheet-ready snapshot from the PO workflow.

The handoff never assumes that old Streamlit session values are current. It
checks the analyzed quote fingerprint, identifies the active quote source,
reconstructs the reviewed inclusions/exclusions, validates the generated scope
PDF signature, applies the canonical PO rules, and emits a context ID used to
isolate all Smartsheet page widgets.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from app import contracts
from app.config import (
    FACILITIES,
    FACILITY_SHORT_NAMES,
    WORK_CATEGORY_DISPLAY,
    lookup_cost_code,
)
from app.po_rules import (
    PURCHASE_ROUTE_LABELS,
    classify_po,
    normalize_asset_id,
)

_CONTRACT_PLACEHOLDER = "— Select a contract —"
_SITE_PLACEHOLDER = "— Select a site —"
_SITE_LABEL_TO_KEY = {label: key for key, label in FACILITY_SHORT_NAMES.items()}
_CATEGORY_LABEL_TO_KEY = {label: key for key, label in WORK_CATEGORY_DISPLAY.items()}
_LOCKED_FIELDS = (
    "request_type",
    "order_type",
    "purchase_route",
    "contract",
    "site",
    "site_location",
    "work_category",
    "cost_code",
    "object_account",
    "agreement_type",
    "asset_id",
    "vendor",
    "contact_name",
    "contact_email",
    "description",
    "description_of_work",
    "scope_of_work",
    "subtotal",
    "tax",
    "total",
    "tax_status",
    "leave_request_completed",
    "po_number",
    "work_order_number",
    "original_po_number",
    "dispatch_service_center",
)

RRH_DEFAULT_JOB_NUMBER = "RRH-695400022-O&M"
PREPARED_PO_CONTEXT_STATE_KEY = "_prepared_smartsheet_po_context"


@dataclass(frozen=True)
class POContext:
    fields: dict[str, str]
    attachments: tuple[tuple[str, bytes], ...]
    attachment_base: str
    warnings: tuple[str, ...]
    context_id: str
    locked_fields: tuple[str, ...] = _LOCKED_FIELDS

    @property
    def ready(self) -> bool:
        return not self.warnings


def _state_text(state: Mapping[str, Any], key: str, default: str = "") -> str:
    value = state.get(key, default)
    if value is None:
        return default
    return str(value).strip()


def _existing_path(value: Any) -> Path | None:
    if not value:
        return None
    try:
        path = Path(value)
    except TypeError:
        return None
    return path if path.exists() and path.is_file() else None


def _safe_basename(contract: str, site: str, description: str, rrh: bool) -> str:
    prefix = "RRH" if rrh else contract.strip()
    clean_description = re.sub(r"[^\w\s-]", "", description or "SOW")[:50]
    if len(clean_description) == 50 and " " in clean_description:
        clean_description = clean_description.rsplit(" ", 1)[0]
    parts = [prefix, site.strip(), clean_description.strip(), "Scope"]
    name = " ".join(part for part in parts if part)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    return re.sub(r"\s+", " ", name).strip() or "PO Scope"


def _selected_contract(state: Mapping[str, Any], token: str) -> str:
    contract = _state_text(state, f"contract_{token}")
    return "" if contract == _CONTRACT_PLACEHOLDER else contract


def _selected_site(state: Mapping[str, Any], token: str, contract: str) -> str:
    if contracts.is_rrh(contract):
        site = _state_text(state, f"site_{token}")
    else:
        site = (
            _state_text(state, f"gsite_{token}_{contract}")
            or _state_text(state, f"gsitetxt_{token}_{contract}")
        )
    return "" if site == _SITE_PLACEHOLDER else site


def _routing_fields(
    state: Mapping[str, Any], token: str, contract: str, site: str, analysis: Any
) -> tuple[str, str, str]:
    rrh = contracts.is_rrh(contract)
    if rrh:
        site_key = _SITE_LABEL_TO_KEY.get(site)
        category_label = _state_text(state, f"cat_{token}_{site_key}") if site_key else ""
        category_key = _CATEGORY_LABEL_TO_KEY.get(category_label, category_label)
        cost_code = (
            lookup_cost_code(site_key, category_key) if site_key and category_key else None
        ) or (
            _state_text(state, f"manualcost_{token}_{site_key}") if site_key else ""
        )
        address = str(FACILITIES.get(site_key, {}).get("address", "")) if site_key else ""
        return category_label, cost_code, address

    category = _state_text(state, f"gcat_{token}_{contract}")
    cost_code = _state_text(state, f"gcost_{token}_{contract}")
    extracted_site = str(getattr(analysis, "facility_name", "") or "").strip()
    address = (
        str(getattr(analysis, "facility_address", "") or "").strip()
        if site and site == extracted_site
        else ""
    )
    return category, cost_code, address


def _asset_value(state: Mapping[str, Any], token: str, contract: str, site: str) -> str:
    no_asset_key = f"noasset_{token}_{contract}_{site}"
    # Retain the old checkbox key only as a compatibility read. The active UI
    # uses one asset dropdown with a No asset option and exports the full UID.
    if bool(state.get(no_asset_key, False)):
        return "None Applicable"
    return _state_text(state, f"asset_{token}_{contract}_{site}") or "None Applicable"


def _strip_ai_wrapper(text: str) -> str:
    match = re.search(r"\[AI ESTIMATE:\s*(.+?)\]", text)
    return match.group(1).strip() if match else text.strip()


def _unified_review_items(analysis: Any, section: str) -> list[str]:
    raw_items = list(getattr(analysis, "inclusions" if section == "inclusion" else "exclusions", []) or [])
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        clean = _strip_ai_wrapper(str(item))
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    for assumption in list(getattr(analysis, "ai_assumptions", []) or []):
        assumption_section = str(getattr(assumption, "section", "") or "")
        text = str(getattr(assumption, "text", "") or "").strip()
        if assumption_section == section and text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _reviewed_lists(
    state: Mapping[str, Any], token: str, analysis: Any
) -> tuple[list[str], list[str]]:
    inclusions = _unified_review_items(analysis, "inclusion")
    exclusions = _unified_review_items(analysis, "exclusion")
    selected_inclusions = [
        text for index, text in enumerate(inclusions)
        if bool(state.get(f"inc_{token}_{index}", True))
    ]
    selected_exclusions = [
        text for index, text in enumerate(exclusions)
        if bool(state.get(f"exc_{token}_{index}", True))
    ]
    return selected_inclusions, selected_exclusions


def _document_signature(
    token: str,
    contract: str,
    site: str,
    inclusions: list[str],
    exclusions: list[str],
) -> str:
    payload = {
        "analysis": token,
        "contract": contract,
        "site": site,
        "inclusions": inclusions,
        "exclusions": exclusions,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reviewed_scope(analysis: Any, inclusions: list[str], exclusions: list[str]) -> str:
    sections = [str(getattr(analysis, "scope_of_work", "") or "").strip()]
    if inclusions:
        sections.append("Inclusions:\n" + "\n".join(f"- {item}" for item in inclusions))
    if exclusions:
        sections.append("Exclusions:\n" + "\n".join(f"- {item}" for item in exclusions))
    return "\n\n".join(section for section in sections if section)


def _active_quote_attachment(
    state: Mapping[str, Any], quote_text: str
) -> tuple[tuple[str, bytes] | None, list[str]]:
    warnings: list[str] = []
    uploaded_bytes = state.get("uploaded_file_bytes")
    uploaded_name = _state_text(state, "uploaded_file_name")
    extracted_text = _state_text(state, "extracted_text")
    extract_hash = _state_text(state, "extract_hash")

    upload_valid = (
        isinstance(uploaded_bytes, bytes)
        and bool(uploaded_bytes)
        and bool(uploaded_name)
        and bool(extracted_text)
        and extracted_text.strip() == quote_text.strip()
        and hashlib.sha256(uploaded_bytes).hexdigest() == extract_hash
    )
    if upload_valid:
        return (uploaded_name, uploaded_bytes), warnings

    if isinstance(uploaded_bytes, bytes) and uploaded_bytes and not extracted_text:
        warnings.append(
            "The current uploaded file was not successfully extracted; the prior analysis may not describe it."
        )
    if quote_text:
        return ("Vendor Quote.txt", quote_text.encode("utf-8")), warnings
    return None, warnings


def _attachments(
    state: Mapping[str, Any], *, base: str, quote_text: str, scope_pdf_valid: bool
) -> tuple[tuple[tuple[str, bytes], ...], list[str]]:
    warnings: list[str] = []
    result: list[tuple[str, bytes]] = []
    quote_attachment, source_warnings = _active_quote_attachment(state, quote_text)
    warnings.extend(source_warnings)
    if quote_attachment:
        result.append(quote_attachment)

    scope_pdf = state.get("scope_pdf_bytes")
    if scope_pdf_valid and isinstance(scope_pdf, bytes) and scope_pdf:
        result.append((f"{base}.pdf", scope_pdf))
    return tuple(result), warnings


def _money(value: str) -> Decimal | None:
    text = re.sub(r"[^0-9.-]", "", value or "")
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _context_id(fields: Mapping[str, str], attachments: tuple[tuple[str, bytes], ...]) -> str:
    payload = {
        "fields": dict(sorted(fields.items())),
        "attachments": [
            {
                "name": name,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in attachments
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def account_manager_memory_context_id(context: POContext) -> str:
    """Return a package identity that is stable while correcting requester name.

    The UI context includes requester name so changing it refreshes the generated
    handoff. Requester-memory deduplication intentionally excludes only that one
    field, allowing a correction on the same otherwise-identical package to move
    the event instead of creating a second remembered use.
    """
    fields = {
        field: value
        for field, value in context.fields.items()
        if field != "requester_name"
    }
    return _context_id(fields, context.attachments)


def build_po_context(
    state: Mapping[str, Any], env: Mapping[str, str] | None = None
) -> POContext | None:
    analysis = state.get("analysis")
    if analysis is None:
        return None

    # ``env`` remains in the public signature for backwards compatibility with
    # older callers, but requester identity must never come from a deployment
    # default. The requester is the person currently filling out the form and
    # is collected before generation, with device+account-scoped memory after
    # the first verified package.
    _ = env
    token = _state_text(state, "analysis_token", "x") or "x"
    purchase_route = _state_text(state, f"purchase_route_{token}")
    contract = _selected_contract(state, token)
    site = _selected_site(state, token, contract) if contract else ""
    rrh = contracts.is_rrh(contract)
    category, cost_code, address = _routing_fields(
        state, token, contract, site, analysis
    )
    inclusions, exclusions = _reviewed_lists(state, token, analysis)

    description = _state_text(
        state,
        f"desc_{token}",
        str(getattr(analysis, "short_description", "") or "")[:20],
    )[:20]
    vendor = _state_text(
        state,
        f"vendor_{token}",
        str(getattr(analysis, "vendor_name", "") or ""),
    )
    quote_text = _state_text(state, "quote_text")
    expected_token = hashlib.sha256(quote_text.encode("utf-8", "ignore")).hexdigest()[:12] if quote_text else ""
    base = _safe_basename(contract, site, getattr(analysis, "project_description", ""), rrh)

    expected_document_signature = _document_signature(
        token, contract, site, inclusions, exclusions
    )
    stored_document_signature = _state_text(state, "scope_pdf_signature")
    scope_pdf_bytes = state.get("scope_pdf_bytes")
    document_valid = (
        stored_document_signature == expected_document_signature
        and isinstance(scope_pdf_bytes, bytes)
        and scope_pdf_bytes.startswith(b"%PDF-")
    )
    attachments, source_warnings = _attachments(
        state,
        base=base,
        quote_text=quote_text,
        scope_pdf_valid=document_valid,
    )

    raw_asset_id = _asset_value(state, token, contract, site)
    asset_id = normalize_asset_id(raw_asset_id)
    reviewed_scope = _reviewed_scope(analysis, inclusions, exclusions)
    total_value = _state_text(
        state, f"total_{token}", str(getattr(analysis, "total_amount", "") or "")
    )
    try:
        classification = classify_po(purchase_route, total_value)
        classification_error = ""
    except ValueError as exc:
        classification = None
        classification_error = str(exc)
    request_type = _state_text(
        state,
        f"request_type_{token}",
        str(getattr(analysis, "request_type_guess", "") or "PO"),
    )
    if request_type not in {"PO", "CHANGE ORDER"}:
        request_type = "PO"
    original_po_number = (
        _state_text(
            state,
            f"original_po_{token}",
            str(getattr(analysis, "original_po_number", "") or ""),
        )
        if request_type == "CHANGE ORDER"
        else ""
    )
    requester_name = _state_text(state, f"requester_{token}_{contract}")
    job_number = _state_text(
        state,
        f"job_number_{token}_{contract}",
        RRH_DEFAULT_JOB_NUMBER if rrh else "",
    )
    fields = {
        "requester_name": requester_name,
        "request_type": request_type,
        "order_type": PURCHASE_ROUTE_LABELS.get(purchase_route, ""),
        "purchase_route": purchase_route,
        "contract": contract,
        "site": site,
        "job_number": job_number,
        "site_location": site,
        "facility_address": address,
        "related_to_om": "",
        "billing_method": "",
        "customer_po": "",
        "work_category": category,
        "cost_code": cost_code,
        "object_account": classification.object_account if classification else "",
        "agreement_type": classification.agreement_type if classification else "",
        "leave_request_completed": "",
        "po_number": "",
        "work_order_number": "",
        "original_po_number": original_po_number,
        "asset_id": asset_id,
        "vendor": vendor,
        "contact_name": _state_text(
            state, f"contact_{token}", str(getattr(analysis, "contact_name", "") or "")
        ),
        "contact_email": _state_text(
            state, f"cemail_{token}", str(getattr(analysis, "contact_email", "") or "")
        ),
        "description": description,
        # Smartsheet's Description of Work field is capped at 20 characters.
        # The complete reviewed scope remains in the generated PDF only.
        "description_of_work": description,
        "scope_of_work": reviewed_scope,
        "estimated_start_date": "",
        "estimated_completion_date": "",
        "customer_representative": "",
        "service_branch_tech_needed": "",
        "subtotal": _state_text(
            state, f"sub_{token}", str(getattr(analysis, "subtotal_amount", "") or "")
        ),
        "tax": _state_text(
            state, f"tax_{token}", str(getattr(analysis, "tax_amount", "") or "")
        ),
        "total": total_value,
        "tax_status": str(getattr(analysis, "tax_status", "") or "").strip(),
        "instructions": _state_text(state, f"instructions_{token}"),
        "dispatch_service_center": "NA",
    }

    warnings: list[str] = list(source_warnings)
    if quote_text and token != expected_token:
        warnings.append(
            "The analysis fingerprint does not match the stored quote text; re-analyze the quote."
        )
    if not contract:
        warnings.append("Select the contract in Purchase Order Process Control.")
    if not site:
        warnings.append("Select or enter the site in Purchase Order Process Control.")
    if not cost_code:
        warnings.append("Confirm the job cost code before submission.")
    if classification_error:
        warnings.append(classification_error)
    if not fields["requester_name"]:
        warnings.append("Enter the person filling out this request.")
    if not fields["job_number"]:
        warnings.append("Confirm the job number before submission.")
    if request_type == "CHANGE ORDER" and not original_po_number:
        warnings.append("Enter the original PO number for this change order.")
    if not fields["vendor"]:
        warnings.append("Confirm the vendor name before submission.")
    if not description:
        warnings.append("Confirm a Description of Work of 20 characters or fewer.")
    if not fields["total"]:
        warnings.append("Confirm the total amount before submission.")
    if not attachments:
        warnings.append("No verified quote and scope PDF package is available to attach.")
    if not document_valid:
        warnings.append(
            "The Scope/Inclusions/Exclusions PDF is missing or no longer matches the reviewed contract, site, inclusions, and exclusions. Regenerate it."
        )
    if len(attachments) != 2 or not any(
        name.lower().endswith(".pdf") for name, _ in attachments
    ):
        warnings.append(
            "The attachment package must contain the original quote and one Scope/Inclusions/Exclusions PDF."
        )
    if len(asset_id) > 160:
        warnings.append("The selected full Asset ID is unexpectedly long.")

    subtotal = _money(fields["subtotal"])
    tax = _money(fields["tax"])
    total = _money(fields["total"])
    if subtotal is not None and tax is not None and total is not None:
        if abs((subtotal + tax) - total) > Decimal("0.01"):
            warnings.append("Subtotal plus sales tax does not equal the total amount.")

    context_id = _context_id(fields, attachments)
    return POContext(
        fields=fields,
        attachments=attachments,
        attachment_base=base,
        warnings=tuple(dict.fromkeys(warnings)),
        context_id=context_id,
    )
