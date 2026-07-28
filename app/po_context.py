"""Build a Smartsheet-ready PO snapshot from the existing Streamlit workflow.

The email and future Smartsheet routes must use the same finalized values. This
module reads the current session-state keys without importing the UI module, so
it can be tested independently and reused by a future primary Smartsheet flow.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app import contracts
from app.config import (
    FACILITIES,
    FACILITY_SHORT_NAMES,
    WORK_CATEGORY_DISPLAY,
    lookup_cost_code,
)
from app.eml_builder import DAVID_EMAIL


_CONTRACT_PLACEHOLDER = "— Select a contract —"
_SITE_PLACEHOLDER = "— Select a site —"
_SITE_LABEL_TO_KEY = {label: key for key, label in FACILITY_SHORT_NAMES.items()}
_CATEGORY_LABEL_TO_KEY = {label: key for key, label in WORK_CATEGORY_DISPLAY.items()}


@dataclass(frozen=True)
class POContext:
    fields: dict[str, str]
    attachments: tuple[tuple[str, bytes], ...]
    attachment_base: str
    warnings: tuple[str, ...]

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
    parts = [prefix, site.strip(), clean_description.strip(), "MSAPO"]
    name = " ".join(part for part in parts if part)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    return re.sub(r"\s+", " ", name).strip() or "MSAPO"


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
) -> tuple[str, str, str, str]:
    """Return work category, cost code, administrator, and facility address."""
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
        administrator = _state_text(
            state, f"recip_{token}_{contract}", DAVID_EMAIL
        ) or DAVID_EMAIL
        return category_label, cost_code, administrator, address

    category = _state_text(state, f"gcat_{token}_{contract}")
    cost_code = _state_text(state, f"gcost_{token}_{contract}")
    administrator = _state_text(state, f"recip_{token}_{contract}")
    extracted_site = str(getattr(analysis, "facility_name", "") or "").strip()
    address = (
        str(getattr(analysis, "facility_address", "") or "").strip()
        if site and site == extracted_site
        else ""
    )
    return category, cost_code, administrator, address


def _asset_value(state: Mapping[str, Any], token: str, contract: str, site: str) -> str:
    no_asset_key = f"noasset_{token}_{contract}_{site}"
    if bool(state.get(no_asset_key, True)):
        return "None Applicable"
    return _state_text(state, f"asset_{token}_{contract}_{site}") or "None Applicable"


def _attachments(
    state: Mapping[str, Any], *, epo_mode: bool, base: str, quote_text: str
) -> tuple[tuple[str, bytes], ...]:
    result: list[tuple[str, bytes]] = []
    uploaded_bytes = state.get("uploaded_file_bytes")
    uploaded_name = _state_text(state, "uploaded_file_name")
    if isinstance(uploaded_bytes, bytes) and uploaded_bytes and uploaded_name:
        result.append((uploaded_name, uploaded_bytes))
    elif quote_text:
        result.append(("Vendor Quote.txt", quote_text.encode("utf-8")))

    if not epo_mode:
        docx = _existing_path(state.get("docx_path"))
        pdf = _existing_path(state.get("pdf_path"))
        if docx:
            result.append((f"{base}.docx", docx.read_bytes()))
        if pdf:
            result.append((f"{base}.pdf", pdf.read_bytes()))
    return tuple(result)


def build_po_context(
    state: Mapping[str, Any], env: Mapping[str, str] | None = None
) -> POContext | None:
    """Return the finalized PO snapshot, or None before quote analysis exists."""
    analysis = state.get("analysis")
    if analysis is None:
        return None

    source_env = os.environ if env is None else env
    token = _state_text(state, "analysis_token", "x") or "x"
    epo_mode = bool(state.get("epo_mode", False))
    contract = _selected_contract(state, token)
    site = _selected_site(state, token, contract) if contract else ""
    rrh = contracts.is_rrh(contract)
    category, cost_code, administrator, address = _routing_fields(
        state, token, contract, site, analysis
    )

    description = _state_text(
        state,
        f"desc_{token}",
        str(getattr(analysis, "short_description", "") or "")[:20],
    )[:20]
    vendor = str(getattr(analysis, "vendor_name", "") or "").strip()
    quote_text = _state_text(state, "quote_text")
    base = _safe_basename(contract, site, getattr(analysis, "project_description", ""), rrh)
    attachments = _attachments(
        state, epo_mode=epo_mode, base=base, quote_text=quote_text
    )

    asset_id = "None Applicable" if epo_mode else _asset_value(
        state, token, contract, site
    )
    fields = {
        "requester_name": str(source_env.get("EPC_REQUESTER_NAME", "")).strip(),
        "order_type": "Equipment-only PO" if epo_mode else "MSAPO",
        "contract": contract,
        "site": site,
        "facility_address": address,
        "related_to_om": "",
        "billing_method": "",
        "customer_po": "",
        "work_category": category,
        "cost_code": cost_code,
        "asset_id": asset_id,
        "vendor": vendor,
        "contact_name": _state_text(
            state, f"contact_{token}", str(getattr(analysis, "contact_name", "") or "")
        ),
        "contact_email": _state_text(
            state, f"cemail_{token}", str(getattr(analysis, "contact_email", "") or "")
        ),
        "description": description,
        "scope_of_work": str(getattr(analysis, "scope_of_work", "") or "").strip(),
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
        "total": _state_text(
            state, f"total_{token}", str(getattr(analysis, "total_amount", "") or "")
        ),
        "tax_status": str(getattr(analysis, "tax_status", "") or "").strip(),
        "administrator_email": administrator,
        "instructions": str(getattr(analysis, "tax_note", "") or "").strip(),
        "send_copy_email": "",
    }

    warnings: list[str] = []
    if not contract:
        warnings.append("Select the contract in Email Process Control.")
    if not site:
        warnings.append("Select or enter the site in Email Process Control.")
    if not cost_code:
        warnings.append("Confirm the job cost code before submission.")
    if not fields["total"]:
        warnings.append("Confirm the total amount before submission.")
    if not attachments:
        warnings.append("No quote or generated document is available to attach.")
    if not epo_mode and not any(name.lower().endswith(".docx") for name, _ in attachments):
        warnings.append("Regenerate the MSAPO document before submission.")

    return POContext(
        fields=fields,
        attachments=attachments,
        attachment_base=base,
        warnings=tuple(warnings),
    )
