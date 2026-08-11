"""Streamlit interface for Purchase Order Process Control.

The application converts a reviewed vendor quote into a prefilled Smartsheet PO
request and a two-file supporting package: the unchanged quote plus a concise
Scope/Inclusions/Exclusions PDF. It does not create or send email.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from decimal import Decimal

import streamlit as st

from app import contracts
from app.asset_guess import guess_asset_uid
from app.assets import assets_for_facility, guess_asset_id
from app.config import (
    FACILITIES,
    FACILITY_SHORT_NAMES,
    WORK_CATEGORY_DISPLAY,
    facility_key_from_name,
    lookup_cost_code,
    valid_categories_for_site,
)
from app.device_identity import device_token, ensure_device_cookie
from app.expense_ui import (
    EXPENSE_WORKFLOW,
    PURCHASE_WORKFLOW,
    preserve_expense_draft_state,
    render_expense_workflow,
)
from app.job_numbers import (
    RRH_JOB_NUMBERS,
    job_numbers_for_contract,
    suggest_job_number,
)
from app.memory import (
    record_device_account_manager,
    record_vendor_contact,
    remembered_device_account_manager,
    remembered_vendor_contact,
)
from app.ocr import extract_text
from app.po_context import (
    _document_signature,
    account_manager_memory_context_id,
    build_po_context,
    vendor_contact_memory_context_id,
)
from app.po_rules import (
    PURCHASE_ROUTE_LABELS,
    PURCHASE_ROUTES,
    classify_po,
    infer_purchase_route,
    normalize_asset_id,
    parse_amount,
)
from app.quote_analyzer import AIAssumption, QuoteAnalysis, analyze_quote
from app.scope_pdf import build_scope_pdf
from app.smartsheet import (
    MAX_ATTACHMENT_BYTES,
    preflight_attachments,
    validate_submission_fields,
)
from app.smartsheet_inline import render_inline_smartsheet_handoff
from app.workflow_state import (
    PASTE_MODE,
    QUOTE_INPUT_MODES,
    UPLOAD_MODE,
    choose_quote_text,
    clear_active_analysis,
    quote_length_problem,
)
from app.workflow_review import (
    ReviewNeeds,
    required_email_is_valid,
    retain_review_needs,
    review_needs,
    tax_alert_message,
)


SITE_LABEL_TO_KEY = {label: key for key, label in FACILITY_SHORT_NAMES.items()}
SITE_LABELS = list(FACILITY_SHORT_NAMES.values())
CONTRACT_PLACEHOLDER = "— Select a contract —"
SITE_PLACEHOLDER = "— Select a site —"
JOB_NUMBER_PLACEHOLDER = "— Select a job number —"
ASSET_NONE = "None Applicable"
ASSET_PLACEHOLDER = "— Choose an asset or No asset —"
REQUEST_TYPE_LABELS = {
    "PO": "New purchase order",
    "CHANGE ORDER": "Change order to an existing PO",
}


@dataclass(frozen=True)
class RoutingSnapshot:
    """Current routing values before their widgets are placed on the page."""

    contract: str
    rrh: bool
    site: str
    category_label: str
    cost_code: str
    rrh_site_key: str | None


CUSTOM_CSS = """
<style>
    :root {
        --enfra-ocean: #092B24;
        --enfra-blue: #557F7F;
        --enfra-iced: #D3E7E0;
        --enfra-concrete: #D3CCC4;
        --enfra-yellow: #D6EF4B;
        --enfra-iron: #000000;
    }

    .stApp {
        font-family: Arial, Helvetica, sans-serif;
        color: var(--enfra-iron);
        background: linear-gradient(180deg, var(--enfra-iced) 0, #FFFFFF 250px);
    }
    #MainMenu, footer, header {visibility: hidden;}

    .block-container {
        max-width: 1000px !important;
        padding-top: 1.25rem !important;
        padding-right: max(1rem, env(safe-area-inset-right)) !important;
        padding-bottom: max(3rem, env(safe-area-inset-bottom)) !important;
        padding-left: max(1rem, env(safe-area-inset-left)) !important;
    }

    .hero {
        background: var(--enfra-ocean);
        border-left: 8px solid var(--enfra-yellow);
        border-radius: 6px;
        padding: 2rem 2.2rem;
        margin-bottom: 0.45rem;
        box-shadow: 0 12px 30px rgba(9,43,36,0.20);
    }
    .brand-kicker {
        color: var(--enfra-yellow);
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.18em;
        margin: 0 0 0.65rem;
        text-transform: uppercase;
    }
    .hero h1 {
        color: #FFFFFF;
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        line-height: 1.08;
        margin: 0 0 0.45rem;
    }
    .hero h1 .zing { color: var(--enfra-yellow); }
    .hero-subtitle {
        color: var(--enfra-iced);
        font-size: 0.98rem;
        line-height: 1.5;
        margin: 0;
        max-width: 40rem;
    }

    .st-key-load_synthetic_test button {
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        color: var(--enfra-blue) !important;
        font-size: 0.8rem !important;
        min-height: 32px !important;
        padding: 0.2rem 0.45rem !important;
    }
    .st-key-load_synthetic_test button:hover {
        color: var(--enfra-ocean) !important;
        text-decoration: underline;
    }

    .step-header {
        align-items: center;
        display: flex;
        gap: 0.7rem;
        margin: 1.45rem 0 0.75rem;
    }
    .step-num {
        align-items: center;
        background: var(--enfra-ocean);
        border-radius: 3px;
        color: #FFFFFF;
        display: flex;
        flex-shrink: 0;
        font-size: 0.85rem;
        font-weight: 700;
        height: 30px;
        justify-content: center;
        width: 30px;
    }
    .step-num.yellow { background: var(--enfra-yellow); color: var(--enfra-ocean); }
    .step-title {
        color: var(--enfra-ocean);
        font-size: 1.28rem;
        font-weight: 700;
        line-height: 1.2;
        margin: 0;
    }

    .metric-card {
        background: #FFFFFF;
        border: 1px solid var(--enfra-concrete);
        border-radius: 5px;
        height: 100%;
        min-width: 0;
        padding: 0.95rem 1.05rem;
    }
    .metric-label {
        color: var(--enfra-blue);
        font-size: 0.66rem;
        font-weight: 700;
        letter-spacing: 0.09em;
        text-transform: uppercase;
    }
    .metric-value {
        color: var(--enfra-ocean);
        font-size: 1.02rem;
        font-weight: 700;
        line-height: 1.3;
        margin-top: 0.2rem;
        overflow-wrap: anywhere;
    }

    .facility-banner {
        align-items: center;
        background: var(--enfra-iced);
        border-left: 5px solid var(--enfra-blue);
        border-radius: 4px;
        display: flex;
        gap: 0.75rem;
        margin: 0.45rem 0 0.25rem;
        padding: 0.9rem 1.1rem;
    }
    .facility-name { color: var(--enfra-ocean); font-size: 0.96rem; font-weight: 700; }
    .facility-address { color: #365B55; font-size: 0.82rem; margin-top: 0.12rem; }

    .tax-alert {
        align-items: flex-start;
        background: var(--enfra-yellow);
        border: 2px solid var(--enfra-ocean);
        border-radius: 4px;
        color: var(--enfra-ocean);
        display: flex;
        gap: 0.75rem;
        line-height: 1.45;
        margin: 0.7rem 0;
        padding: 0.95rem 1.05rem;
    }
    .tax-alert-label {
        background: var(--enfra-ocean);
        border-radius: 2px;
        color: #FFFFFF;
        flex: 0 0 auto;
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        padding: 0.25rem 0.4rem;
    }
    .needs-banner {
        background: #F5F9F7;
        border: 1px solid var(--enfra-blue);
        border-left: 5px solid var(--enfra-yellow);
        border-radius: 4px;
        color: var(--enfra-ocean);
        line-height: 1.45;
        margin: 0.8rem 0;
        padding: 0.85rem 1rem;
    }
    .request-summary {
        background: var(--enfra-ocean);
        border-left: 6px solid var(--enfra-yellow);
        border-radius: 4px;
        color: #FFFFFF;
        line-height: 1.5;
        margin: 0.9rem 0 0.35rem;
        overflow-wrap: anywhere;
        padding: 0.9rem 1rem;
    }
    .request-summary-detail {
        color: var(--enfra-iced);
        display: block;
        font-size: 0.82rem;
        margin-top: 0.25rem;
    }

    .scope-section {
        background: #F5F9F7;
        border: 1px solid var(--enfra-concrete);
        border-radius: 4px;
        margin-bottom: 0.7rem;
        padding: 1rem 1.1rem;
    }
    .scope-label {
        border-bottom: 3px solid var(--enfra-yellow);
        color: var(--enfra-ocean);
        display: inline-block;
        font-size: 0.66rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        margin-bottom: 0.5rem;
        padding-bottom: 0.3rem;
        text-transform: uppercase;
    }
    .scope-text { color: #243F3A; font-size: 0.88rem; line-height: 1.6; margin: 0; }

    .cost-code-pill {
        align-items: center;
        background: var(--enfra-ocean);
        border-left: 5px solid var(--enfra-yellow);
        border-radius: 3px;
        color: #FFFFFF;
        display: flex;
        font-size: 1rem;
        font-weight: 700;
        gap: 0.5rem;
        letter-spacing: 0.02em;
        margin-top: 0.25rem;
        padding: 0.58rem 0.85rem;
    }
    .field-label { color: var(--enfra-ocean); font-size: 0.8rem; font-weight: 700; margin-bottom: 0.15rem; }

    .stButton > button[kind="primary"] {
        background: var(--enfra-yellow);
        border: 2px solid var(--enfra-ocean);
        border-radius: 4px;
        box-shadow: 0 5px 14px rgba(9,43,36,0.18);
        color: var(--enfra-ocean);
        font-size: 0.98rem;
        font-weight: 700;
        min-height: 46px;
    }
    .stButton > button[kind="primary"]:hover {
        background: #C6DF3E;
        border-color: var(--enfra-ocean);
        color: var(--enfra-ocean);
    }
    button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible {
        outline: 3px solid var(--enfra-yellow) !important;
        outline-offset: 2px !important;
    }

    div[data-testid="stFileUploader"] section {
        background: #F5F9F7;
        border: 2px dashed var(--enfra-blue);
        border-radius: 5px;
    }
    div[data-testid="stFileUploader"] section:hover { border-color: var(--enfra-ocean); }
    div[data-testid="stExpander"] {
        background: transparent !important;
        border: 0 !important;
        border-radius: 0 !important;
        box-shadow: none !important;
    }

    .app-footer { color: var(--enfra-blue); font-size: 0.78rem; padding: 2rem 1rem 0.5rem; text-align: center; }
    .app-footer a { color: var(--enfra-ocean); font-weight: 700; text-decoration: none; }
    .footer-divider { background: var(--enfra-yellow); height: 4px; margin: 0 auto 0.8rem; width: 44px; }
    hr { border: 0; border-top: 1px solid var(--enfra-concrete); margin: 1.1rem 0; }

    @media (max-width: 640px) {
        .block-container { padding-top: 0.7rem !important; }
        .hero { border-left-width: 6px; padding: 1.45rem 1.15rem; }
        .hero h1 { font-size: 1.7rem; }
        .hero-subtitle { font-size: 0.92rem; }
        .step-header { align-items: flex-start; margin-top: 1.2rem; }
        .step-title { font-size: 1.13rem; padding-top: 0.2rem; }
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            flex: 1 1 100% !important;
            min-width: 100% !important;
            width: 100% !important;
        }
        div[data-baseweb="input"] input,
        div[data-baseweb="select"] input,
        textarea { font-size: 16px !important; }
        .tax-alert { display: block; }
        .tax-alert-label { display: inline-block; margin-bottom: 0.55rem; }
    }

    @media (pointer: coarse) {
        button, a[role="button"] { min-height: 44px; }
        input, textarea, [role="combobox"] { font-size: 16px !important; }
    }
</style>
"""


def _h(value: object) -> str:
    return html.escape(str(value or ""))


def _parse_amount(value: object) -> Decimal | None:
    """Compatibility wrapper around the canonical currency parser."""
    return parse_amount(value)


def _pricing_difference(
    subtotal: object, tax: object, total: object
) -> Decimal | None:
    """Return subtotal plus tax minus total when all values are parseable."""
    parsed = tuple(_parse_amount(value) for value in (subtotal, tax, total))
    if any(value is None for value in parsed):
        return None
    sub, sales_tax, grand_total = parsed
    return sub + sales_tax - grand_total


def _strip_ai_wrapper(text: str) -> str:
    match = re.search(r"\[AI ESTIMATE:\s*(.+?)\]", text)
    return match.group(1).strip() if match else text.strip()


def _build_unified_lists(
    analysis: QuoteAnalysis,
) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """Return de-duplicated inclusion/exclusion choices with AI flags."""

    def _process(items: list[str], section: str) -> list[tuple[str, bool]]:
        result: list[tuple[str, bool]] = []
        seen: set[str] = set()
        for item in items or []:
            raw = str(item)
            clean = _strip_ai_wrapper(raw)
            if clean and clean not in seen:
                seen.add(clean)
                result.append((clean, "[AI ESTIMATE:" in raw))
        for assumption in analysis.ai_assumptions or []:
            if assumption.section != section:
                continue
            clean = str(assumption.text or "").strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append((clean, True))
        return result

    return (
        _process(analysis.inclusions, "inclusion"),
        _process(analysis.exclusions, "exclusion"),
    )


def _routing_for_generation(
    analysis: QuoteAnalysis,
    quote_text: str,
    token: str,
) -> tuple[str, str, str | None, str | None]:
    """Resolve the reviewed contract/site for the generated scope PDF.

    Streamlit deletes widget keys when a widget is absent during a rerun. The
    confirmed values are therefore mirrored into a plain session key and take
    precedence over both stale widget state and the original AI suggestion.
    """
    detected_contract, detected_site = contracts.match_facility(
        analysis.facility_name, quote_text
    )
    raw_confirmed = st.session_state.get(f"routing_{token}")
    confirmed = raw_confirmed if isinstance(raw_confirmed, dict) else {}
    contract = (
        confirmed.get("contract")
        or st.session_state.get(f"contract_{token}")
        or detected_contract
        or ""
    )
    if contract == CONTRACT_PLACEHOLDER:
        contract = ""
    if contract and not contracts.is_known_contract(contract):
        confirmed = {}
        contract = (
            detected_contract
            if contracts.is_known_contract(detected_contract)
            else ""
        )

    if contracts.is_rrh(contract):
        facility_key = facility_key_from_name(analysis.facility_name)
        default_site = FACILITY_SHORT_NAMES.get(facility_key) if facility_key else ""
        site = (
            confirmed.get("site")
            or st.session_state.get(f"site_{token}")
            or default_site
            or ""
        )
        if site == SITE_PLACEHOLDER:
            site = ""
        selected_key = SITE_LABEL_TO_KEY.get(site)
        if selected_key:
            facility = FACILITIES[selected_key]
            return contract, site, facility["name"], facility["address"]
        return contract, site, analysis.facility_name, analysis.facility_address

    if contract:
        sites = contracts.sites_for_contract(contract)
        site = (
            confirmed.get("site")
            or st.session_state.get(f"gsite_{token}_{contract}")
            or st.session_state.get(f"gsitetxt_{token}_{contract}")
            or (detected_site if contract == detected_contract else "")
            or (sites[0] if len(sites) == 1 else "")
        )
        if site == SITE_PLACEHOLDER:
            site = ""
        address = analysis.facility_address if site and site == detected_site else ""
        return contract, site, site or analysis.facility_name, address

    return "", detected_site or "", analysis.facility_name, analysis.facility_address


def _routing_snapshot(
    analysis: QuoteAnalysis,
    quote_text: str,
    token: str,
) -> RoutingSnapshot:
    """Resolve routing defaults without rendering or creating blank widgets."""
    detected_contract, detected_site = contracts.match_facility(
        analysis.facility_name, quote_text
    )
    contract_options = set(contracts.contract_names())
    raw_confirmed = st.session_state.get(f"routing_{token}")
    confirmed = raw_confirmed if isinstance(raw_confirmed, dict) else {}
    stored_contract = str(st.session_state.get(f"contract_{token}", "") or "")
    confirmed_contract = str(confirmed.get("contract", "") or "")
    if stored_contract in contract_options:
        contract = stored_contract
    elif confirmed_contract in contract_options:
        contract = confirmed_contract
    else:
        contract = detected_contract if detected_contract in contract_options else ""
    if not contract:
        return RoutingSnapshot("", False, "", "", "", None)

    rrh = contracts.is_rrh(contract)
    if rrh:
        detected_site_key = facility_key_from_name(analysis.facility_name)
        default_site = (
            FACILITY_SHORT_NAMES.get(detected_site_key) if detected_site_key else ""
        )
        stored_site = str(st.session_state.get(f"site_{token}", "") or "")
        confirmed_site = str(confirmed.get("site", "") or "")
        if stored_site in SITE_LABELS:
            site = stored_site
        elif confirmed_contract == contract and confirmed_site in SITE_LABELS:
            site = confirmed_site
        else:
            site = default_site or ""
        site_key = SITE_LABEL_TO_KEY.get(site)
        if not site_key:
            return RoutingSnapshot(contract, True, site, "", "", None)
        valid_categories = valid_categories_for_site(site_key)
        category_labels = [
            WORK_CATEGORY_DISPLAY.get(item, item) for item in valid_categories
        ]
        if not category_labels:
            return RoutingSnapshot(contract, True, site, "", "", site_key)
        guessed_category = (
            WORK_CATEGORY_DISPLAY.get(analysis.work_category, analysis.work_category)
            if analysis.work_category in valid_categories
            else category_labels[0]
        )
        stored_category = str(
            st.session_state.get(f"cat_{token}_{site_key}", "") or ""
        )
        category_label = (
            stored_category if stored_category in category_labels else guessed_category
        )
        category_key = valid_categories[category_labels.index(category_label)]
        cost_code = lookup_cost_code(site_key, category_key) or str(
            st.session_state.get(f"manualcost_{token}_{site_key}", "") or ""
        ).strip()
        return RoutingSnapshot(
            contract, True, site, category_label, cost_code, site_key
        )

    sites = contracts.sites_for_contract(contract)
    if sites:
        stored_site = str(
            st.session_state.get(f"gsite_{token}_{contract}", "") or ""
        )
        confirmed_site = str(confirmed.get("site", "") or "")
        site = (
            stored_site
            if stored_site in sites
            else confirmed_site
            if confirmed_contract == contract and confirmed_site in sites
            else detected_site
            if contract == detected_contract and detected_site in sites
            else sites[0]
            if len(sites) == 1
            else ""
        )
    else:
        site = str(
            st.session_state.get(f"gsitetxt_{token}_{contract}")
            or (
                confirmed.get("site")
                if confirmed_contract == contract
                else ""
            )
            or ""
        ).strip()
    category_label = str(
        st.session_state.get(
            f"gcat_{token}_{contract}",
            WORK_CATEGORY_DISPLAY.get(
                analysis.work_category, analysis.work_category or ""
            ),
        )
        or ""
    ).strip()
    cost_code = str(
        st.session_state.get(f"gcost_{token}_{contract}", "") or ""
    ).strip()
    return RoutingSnapshot(
        contract, False, site, category_label, cost_code, None
    )


def _asset_control_data(
    *,
    analysis: QuoteAnalysis,
    quote_text: str,
    contract: str,
    rrh: bool,
    site: str,
    rrh_site_key: str | None,
) -> tuple[list[dict[str, str]], dict[str, str], str | None]:
    """Return the current site assets, labels, and unique-best suggestion."""
    if not contract or not site:
        return [], {}, None
    if rrh:
        site_assets = assets_for_facility(rrh_site_key) if rrh_site_key else []
        exact_guess = (
            guess_asset_id(quote_text, rrh_site_key, hint=analysis.asset_reference)
            if rrh_site_key
            else None
        )
    else:
        site_assets = contracts.assets_for_site(contract, site)
        exact_guess = contracts.guess_uid(
            quote_text, contract, site, hint=analysis.asset_reference
        )
    uids = [asset["uid"] for asset in site_assets]
    labels = {asset["uid"]: contracts.asset_label(asset) for asset in site_assets}
    broad_guess = guess_asset_uid(
        site_assets,
        quote_text=quote_text,
        hint=analysis.asset_reference,
    )
    guess = exact_guess if exact_guess in uids else broad_guess
    return site_assets, labels, guess


def _render_tax_alert(status: object) -> None:
    """Render the one prominent non-blocking alert when tax was not included."""
    message = tax_alert_message(status)
    if not message:
        return
    st.markdown(
        '<div class="tax-alert" role="alert">'
        '<span class="tax-alert-label">TAX CHECK</span>'
        f'<strong>{_h(message)}</strong></div>',
        unsafe_allow_html=True,
    )


def _build_test_analysis() -> QuoteAnalysis:
    return QuoteAnalysis(
        vendor_name="Northeast Mechanical Services",
        project_description="Repair and recommission absorption chiller CH-1.",
        facility_name="Clifton Springs Hospital & Clinic",
        facility_address="2 Coulter Rd, Clifton Springs, NY 14432",
        scope_of_work=(
            "Isolate and drain absorption chiller CH-1. Inspect the solution "
            "pump, purge unit, and tube bundle; replace worn gaskets and the "
            "purge valve. Refill and perform a full commissioning cycle."
        ),
        inclusions=[
            "Chiller teardown and reassembly",
            "Gasket and purge valve replacement",
            "Startup and commissioning",
        ],
        exclusions=["Crane or rigging", "Work outside the quoted equipment"],
        ai_assumptions=[
            AIAssumption(
                text="Facility provides normal-hours equipment access",
                section="inclusion",
            )
        ],
        contact_name="Morgan Bell",
        contact_email="mbell@example.com",
        subtotal_amount="$23,250.00",
        tax_amount="$1,860.00",
        total_amount="$25,110.00",
        short_description="Chiller Repair",
        tax_status="included",
        tax_note="Quoted total includes the stated sales tax.",
        work_category="repairs",
        asset_reference="CH-1",
        purchase_route_guess="onsite_labor",
        request_type_guess="PO",
    )


def _load_test_into_state() -> None:
    analysis = _build_test_analysis()
    quote_text = analysis.scope_of_work
    token = hashlib.sha256(quote_text.encode("utf-8")).hexdigest()[:12]
    quote_bytes = b"(synthetic sample quote placeholder)"
    st.session_state["analysis"] = analysis
    st.session_state["analysis_token"] = token
    st.session_state["quote_text"] = quote_text
    st.session_state["quote_source"] = "synthetic"
    st.session_state["synthetic_quote_active"] = True
    st.session_state["quote_input_mode"] = UPLOAD_MODE
    st.session_state["last_sig"] = hashlib.sha256(
        quote_text.encode("utf-8")
    ).hexdigest()
    st.session_state["extracted_text"] = quote_text
    st.session_state["uploaded_file_bytes"] = quote_bytes
    st.session_state["uploaded_file_name"] = "Sample_Quote.txt"
    st.session_state["extract_hash"] = hashlib.sha256(quote_bytes).hexdigest()
    st.session_state.pop("scope_pdf_bytes", None)
    st.session_state.pop("scope_pdf_signature", None)
    st.session_state.pop("analysis_error_signature", None)
    st.session_state.pop("analysis_error_message", None)
    st.session_state.pop("extraction_error_hash", None)
    st.session_state.pop("extraction_error_message", None)


def _deactivate_synthetic_quote() -> None:
    st.session_state["synthetic_quote_active"] = False


def _retry_extraction() -> None:
    st.session_state.pop("extraction_error_hash", None)
    st.session_state.pop("extraction_error_message", None)


def _retry_analysis() -> None:
    st.session_state.pop("analysis_error_signature", None)
    st.session_state.pop("analysis_error_message", None)


def _render_analysis_retry(signature: str) -> None:
    st.error(
        "The quote could not be analyzed. Try again, or switch to Paste text "
        "if the uploaded file has an unusual layout."
    )
    details = st.session_state.get("analysis_error_message", "")
    if details:
        st.caption(f"Analysis detail: {details}")
    st.button(
        "Try analyzing this quote again",
        key=f"retry_analysis_{signature[:12]}",
        on_click=_retry_analysis,
    )


def _render_routing_controls(
    analysis: QuoteAnalysis,
    quote_text: str,
    token: str,
) -> tuple[str, bool, str, str, str, str | None]:
    """Render sanitized contract/site/cost-code overrides in page order."""
    detected_contract, detected_site = contracts.match_facility(
        analysis.facility_name, quote_text
    )
    contract_options = [CONTRACT_PLACEHOLDER] + contracts.contract_names()
    raw_confirmed = st.session_state.get(f"routing_{token}")
    confirmed = raw_confirmed if isinstance(raw_confirmed, dict) else {}
    contract_key = f"contract_{token}"
    if st.session_state.get(contract_key) not in contract_options:
        st.session_state[contract_key] = (
            confirmed.get("contract")
            if confirmed.get("contract") in contract_options
            else detected_contract
            if detected_contract in contract_options
            else CONTRACT_PLACEHOLDER
        )
    contract = st.selectbox(
        "Contract *",
        contract_options,
        key=contract_key,
    )
    if contract == CONTRACT_PLACEHOLDER:
        st.session_state.pop(f"routing_{token}", None)
        return "", False, "", "", "", None

    rrh = contracts.is_rrh(contract)
    if rrh:
        facility_key = facility_key_from_name(analysis.facility_name)
        default_site = FACILITY_SHORT_NAMES.get(facility_key) if facility_key else None
        site_options = [SITE_PLACEHOLDER] + SITE_LABELS
        site_key_name = f"site_{token}"
        if st.session_state.get(site_key_name) not in site_options:
            st.session_state[site_key_name] = (
                confirmed.get("site")
                if confirmed.get("contract") == contract
                and confirmed.get("site") in site_options
                else default_site
                if default_site in site_options
                else SITE_PLACEHOLDER
            )
        site = st.selectbox("Site *", site_options, key=site_key_name)
        if site == SITE_PLACEHOLDER:
            st.session_state.pop(f"routing_{token}", None)
            return contract, rrh, "", "", "", None
        site_key = SITE_LABEL_TO_KEY.get(site)
        if not site_key:
            st.session_state.pop(f"routing_{token}", None)
            return contract, rrh, "", "", "", None
        valid_categories = valid_categories_for_site(site_key)
        category_labels = [
            WORK_CATEGORY_DISPLAY.get(item, item) for item in valid_categories
        ]
        if not category_labels:
            st.session_state[f"routing_{token}"] = {
                "contract": contract,
                "site": site,
            }
            return contract, rrh, site, "", "", site_key
        default_category = (
            WORK_CATEGORY_DISPLAY.get(analysis.work_category, analysis.work_category)
            if analysis.work_category in valid_categories
            else category_labels[0]
        )
        category_state_key = f"cat_{token}_{site_key}"
        if st.session_state.get(category_state_key) not in category_labels:
            st.session_state[category_state_key] = default_category
        category_label = st.selectbox(
            "Work category",
            category_labels,
            key=category_state_key,
        )
        category_key = valid_categories[category_labels.index(category_label)]
        cost_code = lookup_cost_code(site_key, category_key) or ""
        if cost_code:
            st.markdown(
                '<div class="field-label">Job cost code</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="cost-code-pill">🏷️ {_h(cost_code)}</div>',
                unsafe_allow_html=True,
            )
        else:
            cost_code = st.text_input(
                "Job cost code *",
                key=f"manualcost_{token}_{site_key}",
                placeholder="Enter the site cost code",
            )
        st.session_state[f"routing_{token}"] = {
            "contract": contract,
            "site": site,
        }
        return contract, rrh, site, category_label, cost_code, site_key

    sites = contracts.sites_for_contract(contract)
    if sites:
        site_options = [SITE_PLACEHOLDER] + sites
        site_state_key = f"gsite_{token}_{contract}"
        site_default = (
            detected_site
            if contract == detected_contract and detected_site in site_options
            else (sites[0] if len(sites) == 1 else SITE_PLACEHOLDER)
        )
        if st.session_state.get(site_state_key) not in site_options:
            st.session_state[site_state_key] = (
                confirmed.get("site")
                if confirmed.get("contract") == contract
                and confirmed.get("site") in site_options
                else site_default
            )
        site = st.selectbox("Site *", site_options, key=site_state_key)
        if site == SITE_PLACEHOLDER:
            site = ""
    else:
        site = st.text_input(
            "Site *",
            key=f"gsitetxt_{token}_{contract}",
            placeholder="Enter the site",
        )
    category_label = st.text_input(
        "Work category",
        value=WORK_CATEGORY_DISPLAY.get(
            analysis.work_category, analysis.work_category or ""
        ),
        key=f"gcat_{token}_{contract}",
    )
    cost_code = st.text_input(
        "Job cost code *",
        key=f"gcost_{token}_{contract}",
        placeholder="Paste the cost code",
    )
    if site:
        st.session_state[f"routing_{token}"] = {
            "contract": contract,
            "site": site,
        }
    else:
        st.session_state.pop(f"routing_{token}", None)
    return contract, rrh, site, category_label, cost_code, None


def _render_asset_control(
    *,
    analysis: QuoteAnalysis,
    quote_text: str,
    token: str,
    contract: str,
    rrh: bool,
    site: str,
    rrh_site_key: str | None,
) -> str:
    """Show one AI-suggested asset dropdown and export the full registry UID."""
    if not contract or not site:
        return ASSET_NONE
    site_assets, labels, guess = _asset_control_data(
        analysis=analysis,
        quote_text=quote_text,
        contract=contract,
        rrh=rrh,
        site=site,
        rrh_site_key=rrh_site_key,
    )
    uids = [asset["uid"] for asset in site_assets]
    if not uids:
        st.caption(
            "No asset registry is configured for this site; Asset ID will be blank."
        )
        return ASSET_NONE
    asset_state_key = f"asset_{token}_{contract}_{site}"
    resolved_options = [ASSET_NONE, *uids]
    stored_asset = st.session_state.get(asset_state_key)
    needs_choice = guess not in uids and stored_asset not in resolved_options
    options = (
        [ASSET_PLACEHOLDER, *resolved_options]
        if needs_choice or stored_asset == ASSET_PLACEHOLDER
        else resolved_options
    )
    default_asset = (
        guess
        if guess in uids
        else ASSET_PLACEHOLDER
        if needs_choice
        else ASSET_NONE
    )
    # A registry update can remove an asset while an older Streamlit session
    # still holds its UID.  Never pass that stale value back to selectbox: it
    # can otherwise render a choice that is no longer valid or raise during a
    # rerun.  Reset only this account/site asset selection to the fresh guess.
    if st.session_state.get(asset_state_key) not in options:
        st.session_state[asset_state_key] = default_asset
    raw_asset = st.selectbox(
        "Specific asset *",
        options,
        format_func=lambda uid: (
            "Choose the asset, or confirm that no asset applies"
            if uid == ASSET_PLACEHOLDER
            else "No asset applies"
            if uid == ASSET_NONE
            else f"{labels[uid]} · {uid}"
        ),
        key=asset_state_key,
        help=(
            "The tool suggests the asset from the quote and selected site. "
            "Choose a different one only if the suggestion is wrong."
        ),
    )
    full_asset_id = normalize_asset_id(raw_asset)
    if full_asset_id:
        st.caption(f"Full Asset ID sent to Smartsheet: **{full_asset_id}**")
    elif analysis.asset_reference:
        st.caption(
            f"Quote clue: {analysis.asset_reference}. No unique site asset was found."
        )
    return raw_asset


def _render_footer() -> None:
    st.markdown(
        """
        <div class="app-footer">
            <div class="footer-divider"></div>
            Built by Evan Roden
            &nbsp;•&nbsp; purchase-order prep without duplicate entry
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Purchase Order Process Control",
        page_icon="📋",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    try:
        browser_token = device_token(st.context.cookies)
        if not browser_token:
            ensure_device_cookie()
    except Exception:
        browser_token = ""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    preserve_expense_draft_state()

    workflow_mode = st.segmented_control(
        "Choose workflow",
        (PURCHASE_WORKFLOW, EXPENSE_WORKFLOW),
        default=PURCHASE_WORKFLOW,
        key="workflow_mode",
        label_visibility="collapsed",
        width="stretch",
    )
    if workflow_mode == EXPENSE_WORKFLOW:
        render_expense_workflow(browser_token)
        _render_footer()
        return

    st.markdown(
        """
        <div class="hero">
            <p class="brand-kicker">PURCHASE ORDER WORKFLOW</p>
            <h1>Purchase Order <span class="zing">Process Control</span></h1>
            <p class="hero-subtitle">
                Upload the quote, answer only what the tool could not determine,
                then create both files and open the prefilled Smartsheet request.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([2, 3, 2])
    with center:
        if st.button(
            "Built by Evan Roden",
            key="load_synthetic_test",
            width="stretch",
            help="Load the built-in synthetic quote for a safe workflow test.",
        ):
            _load_test_into_state()
            st.session_state["uploader_nonce"] = (
                st.session_state.get("uploader_nonce", 0) + 1
            )
            st.rerun()

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num navy">1</div>
            <p class="step-title">Provide the vendor quote</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    input_mode = st.radio(
        "Quote source",
        QUOTE_INPUT_MODES,
        horizontal=True,
        key="quote_input_mode",
        on_change=_deactivate_synthetic_quote,
        label_visibility="collapsed",
    )
    uploaded_text = ""
    pasted_text = ""
    uploaded = None

    if input_mode == UPLOAD_MODE:
        uploaded = st.file_uploader(
            "Upload quote",
            type=[
                "pdf", "png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp",
                "heic", "heif", "hif", "txt",
            ],
            max_upload_size=MAX_ATTACHMENT_BYTES // (1024 * 1024),
            label_visibility="collapsed",
            key=f"uploader_{st.session_state.get('uploader_nonce', 0)}",
            on_change=_deactivate_synthetic_quote,
        )
        if uploaded is not None:
            file_bytes = uploaded.getvalue()
            st.session_state["uploaded_file_bytes"] = file_bytes
            st.session_state["uploaded_file_name"] = uploaded.name
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            extraction_failed = (
                st.session_state.get("extraction_error_hash") == file_hash
            )
            if (
                st.session_state.get("extract_hash") != file_hash
                and not extraction_failed
            ):
                with st.spinner("Reading the quote…"):
                    try:
                        extracted = extract_text(
                            file_bytes, uploaded.name
                        ).strip()
                        if not extracted:
                            raise ValueError("No readable text was found in the file.")
                    except Exception as exc:
                        st.session_state["extracted_text"] = ""
                        st.session_state["extraction_error_hash"] = file_hash
                        st.session_state["extraction_error_message"] = str(exc)[:300]
                    else:
                        st.session_state["extracted_text"] = extracted
                        st.session_state["extract_hash"] = file_hash
                        st.session_state.pop("extraction_error_hash", None)
                        st.session_state.pop("extraction_error_message", None)
            if st.session_state.get("extraction_error_hash") == file_hash:
                st.error(
                    "The file could not be read. Try reading it again, upload a "
                    "clearer copy, or switch to Paste text."
                )
                details = st.session_state.get("extraction_error_message", "")
                if details:
                    st.caption(f"File-reading detail: {details}")
                st.button(
                    "Try reading this file again",
                    key=f"retry_extract_{file_hash[:12]}",
                    on_click=_retry_extraction,
                )
            else:
                uploaded_text = st.session_state.get("extracted_text", "")
            if uploaded_text:
                with st.expander("Preview extracted text", expanded=False):
                    st.text_area(
                        "Raw text",
                        uploaded_text,
                        height=170,
                        disabled=True,
                        label_visibility="collapsed",
                    )
    elif input_mode == PASTE_MODE:
        pasted_text = st.text_area(
            "Paste the full vendor quote text",
            height=200,
            placeholder="Paste the vendor quote here…",
            label_visibility="collapsed",
            key="pasted_quote_text",
            on_change=_deactivate_synthetic_quote,
        )

    quote_text, quote_source = choose_quote_text(
        input_mode,
        uploaded_text=uploaded_text,
        pasted_text=pasted_text,
        synthetic_active=bool(st.session_state.get("synthetic_quote_active")),
        synthetic_text=st.session_state.get("quote_text", ""),
    )

    length_problem = quote_length_problem(quote_text)
    if length_problem:
        clear_active_analysis(st.session_state)
        st.error(length_problem)
        _render_footer()
        return

    if not quote_text:
        if st.session_state.get("analysis") is not None:
            clear_active_analysis(st.session_state)
        st.info("Upload or paste a quote above. It will be analyzed automatically.")
        _render_footer()
        return

    full_signature = hashlib.sha256(
        quote_text.encode("utf-8", "ignore")
    ).hexdigest()
    if (
        st.session_state.get("last_sig") == full_signature
        and st.session_state.get("analysis") is not None
    ):
        # The same text can legitimately move from an uploaded file to pasted
        # text (or vice versa).  Keep the attachment source current even when
        # another AI call is unnecessary.
        st.session_state["quote_text"] = quote_text
        st.session_state["quote_source"] = quote_source
    if st.session_state.get("analysis_error_signature") == full_signature:
        _render_analysis_retry(full_signature)
    elif st.session_state.get("last_sig") != full_signature:
        with st.spinner("Reading the quote and extracting the PO details…"):
            try:
                analysis = analyze_quote(quote_text)
            except Exception as exc:
                clear_active_analysis(st.session_state)
                st.session_state["analysis_error_signature"] = full_signature
                st.session_state["analysis_error_message"] = str(exc)[:300]
                st.session_state["quote_source"] = quote_source
            else:
                st.session_state["analysis"] = analysis
                st.session_state["analysis_token"] = full_signature[:12]
                st.session_state["last_sig"] = full_signature
                st.session_state["quote_text"] = quote_text
                st.session_state["quote_source"] = quote_source
                st.session_state.pop("scope_pdf_bytes", None)
                st.session_state.pop("scope_pdf_signature", None)
                st.session_state.pop("analysis_error_signature", None)
                st.session_state.pop("analysis_error_message", None)

        if st.session_state.get("analysis_error_signature") == full_signature:
            _render_analysis_retry(full_signature)

    analysis: QuoteAnalysis | None = st.session_state.get("analysis")
    if analysis is None:
        _render_footer()
        return

    token = st.session_state.get("analysis_token", "x")
    cached_quote = st.session_state.get("quote_text", "")

    # Keep the analyzed-quote path free of early returns from here onward.
    # Streamlit removes keys for widgets that do not render during a rerun, so
    # package invalidation must suppress only generation/handoff—not the fields
    # where the operator entered corrections.

    routing_snapshot = _routing_snapshot(analysis, cached_quote, token)

    request_type_key = f"request_type_{token}"
    request_type_guess = str(
        getattr(analysis, "request_type_guess", "") or "PO"
    ).strip()
    if request_type_guess not in REQUEST_TYPE_LABELS:
        request_type_guess = "PO"
    if st.session_state.get(request_type_key) not in REQUEST_TYPE_LABELS:
        st.session_state[request_type_key] = request_type_guess
    request_type = str(st.session_state[request_type_key])

    original_po_key = f"original_po_{token}"
    original_po_guess = str(
        getattr(analysis, "original_po_number", "") or ""
    ).strip()
    if original_po_key not in st.session_state:
        st.session_state[original_po_key] = original_po_guess

    route_key = f"purchase_route_{token}"
    route_guess = str(
        getattr(analysis, "purchase_route_guess", "") or ""
    ).strip()
    if route_guess not in PURCHASE_ROUTES:
        route_guess = infer_purchase_route(
            " ".join(
                (
                    cached_quote,
                    str(getattr(analysis, "project_description", "") or ""),
                    str(getattr(analysis, "scope_of_work", "") or ""),
                )
            )
        )
    if st.session_state.get(route_key) not in PURCHASE_ROUTES:
        st.session_state[route_key] = route_guess
    purchase_route = str(st.session_state[route_key])

    total_key = f"total_{token}"
    if total_key not in st.session_state:
        st.session_state[total_key] = analysis.total_amount or ""
    total_value = str(st.session_state.get(total_key, "") or "").strip()

    vendor_key = f"vendor_{token}"
    if vendor_key not in st.session_state:
        st.session_state[vendor_key] = analysis.vendor_name or ""
    vendor_value = str(st.session_state.get(vendor_key, "") or "").strip()

    contact_key = f"contact_{token}"
    analysis_contact_name = str(analysis.contact_name or "").strip()
    if contact_key not in st.session_state:
        st.session_state[contact_key] = analysis_contact_name

    email_key = f"cemail_{token}"
    analysis_contact_email = str(analysis.contact_email or "").strip()
    if email_key not in st.session_state:
        st.session_state[email_key] = analysis_contact_email

    contact_seed_key = f"vendor_contact_seed_{token}"
    seeded_name_key = f"vendor_contact_seeded_name_{token}"
    seeded_email_key = f"vendor_contact_seeded_email_{token}"
    contact_seed_context = ""
    if routing_snapshot.contract and vendor_value:
        contact_seed_context = (
            f"{routing_snapshot.contract}\x00{vendor_value.casefold()}"
        )
    previous_seed_context = str(
        st.session_state.get(contact_seed_key, "") or ""
    )
    if contact_seed_context and previous_seed_context != contact_seed_context:
        previous_seeded_name = str(
            st.session_state.get(seeded_name_key, "") or ""
        )
        previous_seeded_email = str(
            st.session_state.get(seeded_email_key, "") or ""
        )
        if previous_seed_context:
            if (
                previous_seeded_name
                and st.session_state.get(contact_key) == previous_seeded_name
            ):
                st.session_state[contact_key] = analysis_contact_name
            if (
                previous_seeded_email
                and st.session_state.get(email_key) == previous_seeded_email
            ):
                st.session_state[email_key] = analysis_contact_email

        current_name = str(st.session_state.get(contact_key, "") or "").strip()
        current_email = str(st.session_state.get(email_key, "") or "").strip()
        remembered_name, remembered_email = remembered_vendor_contact(
            routing_snapshot.contract,
            vendor_value,
            contact_name=current_name,
            contact_email=current_email,
        )
        seeded_name = ""
        seeded_email = ""
        if not current_name and remembered_name:
            st.session_state[contact_key] = remembered_name
            seeded_name = remembered_name
        if not current_email and remembered_email:
            st.session_state[email_key] = remembered_email
            seeded_email = remembered_email
        st.session_state[contact_seed_key] = contact_seed_context
        st.session_state[seeded_name_key] = seeded_name
        st.session_state[seeded_email_key] = seeded_email

    contact_value = str(st.session_state.get(contact_key, "") or "").strip()
    email_value = str(st.session_state.get(email_key, "") or "").strip()
    remembered_contact_active = bool(
        contact_seed_context
        and st.session_state.get(contact_seed_key) == contact_seed_context
        and (
            (
                st.session_state.get(seeded_name_key)
                and contact_value == st.session_state.get(seeded_name_key)
            )
            or (
                st.session_state.get(seeded_email_key)
                and email_value == st.session_state.get(seeded_email_key)
            )
        )
    )

    description_key = f"desc_{token}"
    if description_key not in st.session_state:
        st.session_state[description_key] = (
            analysis.short_description or ""
        )[:20]
    elif len(str(st.session_state.get(description_key, "") or "")) > 20:
        st.session_state[description_key] = str(
            st.session_state.get(description_key, "") or ""
        )[:20]
    description_value = str(
        st.session_state.get(description_key, "") or ""
    ).strip()[:20]

    instructions_key = f"instructions_{token}"
    instructions_value = str(
        st.session_state.get(instructions_key, "") or ""
    ).strip()

    job_key = ""
    job_value = ""
    if routing_snapshot.contract:
        job_key = f"job_number_{token}_{routing_snapshot.contract}"
        job_options = job_numbers_for_contract(routing_snapshot.contract)
        job_suggestion = suggest_job_number(job_options, cached_quote)
        valid_job_values = {JOB_NUMBER_PLACEHOLDER, *job_options}
        if st.session_state.get(job_key) not in valid_job_values:
            st.session_state[job_key] = (
                job_suggestion
                or RRH_JOB_NUMBERS[0]
                if routing_snapshot.rrh
                else job_suggestion or JOB_NUMBER_PLACEHOLDER
            )
        job_value = str(st.session_state.get(job_key, "") or "").strip()
        if job_value == JOB_NUMBER_PLACEHOLDER:
            job_value = ""

    site_assets, _, asset_guess = _asset_control_data(
        analysis=analysis,
        quote_text=cached_quote,
        contract=routing_snapshot.contract,
        rrh=routing_snapshot.rrh,
        site=routing_snapshot.site,
        rrh_site_key=routing_snapshot.rrh_site_key,
    )
    asset_uids = [asset["uid"] for asset in site_assets]
    asset_key = (
        f"asset_{token}_{routing_snapshot.contract}_{routing_snapshot.site}"
        if routing_snapshot.contract and routing_snapshot.site
        else ""
    )
    stored_asset = st.session_state.get(asset_key) if asset_key else None
    asset_resolved = (
        not asset_uids
        or stored_asset in [ASSET_NONE, *asset_uids]
        or asset_guess in asset_uids
    )

    current_needs = review_needs(
        routing_ready=bool(
            routing_snapshot.contract
            and routing_snapshot.site
            and routing_snapshot.category_label
            and routing_snapshot.cost_code
        ),
        request_type=request_type,
        original_po_number=st.session_state.get(original_po_key, ""),
        job_number=job_value,
        asset_resolved=asset_resolved,
        total=total_value,
        vendor=vendor_value,
        description=description_value,
        contact_name=contact_value,
        contact_email=email_value,
    )
    review_needs_key = f"review_needs_{token}"
    needs: ReviewNeeds = retain_review_needs(
        st.session_state.get(review_needs_key),
        current_needs,
    )
    st.session_state[review_needs_key] = needs

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num">2</div>
            <p class="step-title">Review and complete the request</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_tax_alert(getattr(analysis, "tax_status", ""))

    metrics = st.columns(3)
    metric_values = (
        ("Vendor", vendor_value or "Needs your input"),
        (
            "Site",
            routing_snapshot.site
            or analysis.facility_name
            or "Needs your input",
        ),
        ("Final amount", total_value or "Needs your input"),
    )
    for column, (label, value) in zip(metrics, metric_values):
        with column:
            st.markdown(
                f'<div class="metric-card"><div class="metric-label">{_h(label)}</div>'
                f'<div class="metric-value">{_h(value)}</div></div>',
                unsafe_allow_html=True,
            )

    if analysis.facility_name:
        st.markdown(
            f'<div class="facility-banner"><div>'
            f'<div class="facility-name">{_h(analysis.facility_name)}</div>'
            f'<div class="facility-address">{_h(analysis.facility_address)}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    final_inclusions: list[str] = []
    final_exclusions: list[str] = []
    unified_inclusions, unified_exclusions = _build_unified_lists(analysis)
    with st.expander(
        "Review scope, inclusions, and exclusions",
        expanded=False,
        type="compact",
    ):
        st.caption(
            "The tool selected everything below for the supporting PDF. "
            "Only change an item if the quote was interpreted incorrectly."
        )
        scope_value = st.text_area(
            "Scope of Work",
            key=scope_key,
            height=160,
            help=(
                "Edit the tool's draft when the quote was interpreted "
                "incorrectly. This exact text is used in the supporting PDF."
            ),
        ).strip()
        inclusion_column, exclusion_column = st.columns(2)
        with inclusion_column:
            st.markdown(
                '<div class="scope-label">Inclusions</div>',
                unsafe_allow_html=True,
            )
            for index, (text_value, is_ai) in enumerate(unified_inclusions):
                if st.checkbox(
                    f"{'Suggested: ' if is_ai else ''}{text_value}",
                    key=f"inc_{token}_{index}",
                    value=True,
                ):
                    final_inclusions.append(text_value)
        with exclusion_column:
            st.markdown(
                '<div class="scope-label">Exclusions</div>',
                unsafe_allow_html=True,
            )
            for index, (text_value, is_ai) in enumerate(unified_exclusions):
                if st.checkbox(
                    f"{'Suggested: ' if is_ai else ''}{text_value}",
                    key=f"exc_{token}_{index}",
                    value=True,
                ):
                    final_exclusions.append(text_value)
        if any(is_ai for _, is_ai in unified_inclusions + unified_exclusions):
            st.caption(
                "Items marked Suggested were inferred by the tool rather than "
                "stated in the quote."
            )

    if needs.any:
        st.markdown(
            '<div class="needs-banner"><strong>Needed from you</strong><br>'
            'The tool could not safely determine one or more values below. '
            'Every question shown below is required before generation.</div>',
            unsafe_allow_html=True,
        )

    questions = st.container()
    corrections = st.expander(
        "Change a value the tool already filled",
        expanded=False,
        type="compact",
    )
    with corrections:
        st.caption(
            "This panel contains only values the tool filled or defaulted. "
            "Unresolved questions stay visible above it."
        )

    with questions if needs.routing else corrections:
        contract, rrh, site, category_label, cost_code, rrh_site_key = (
            _render_routing_controls(analysis, cached_quote, token)
        )

    with corrections:
        request_type = st.selectbox(
            "What kind of request is this? *",
            tuple(REQUEST_TYPE_LABELS),
            format_func=lambda value: REQUEST_TYPE_LABELS[value],
            key=request_type_key,
            help="The tool guesses this from the quote. Change it only if needed.",
        )

    if request_type == "CHANGE ORDER":
        with questions if needs.original_po_number else corrections:
            st.text_input(
                "Original PO number *",
                key=original_po_key,
                placeholder="Enter the existing PO number",
            )

    if contract:
        job_key = f"job_number_{token}_{contract}"
        job_options = job_numbers_for_contract(contract)
        job_suggestion = suggest_job_number(job_options, cached_quote)
        selectable_job_options = (
            job_options
            if rrh
            else (JOB_NUMBER_PLACEHOLDER, *job_options)
        )
        if st.session_state.get(job_key) not in selectable_job_options:
            st.session_state[job_key] = (
                job_suggestion
                or RRH_JOB_NUMBERS[0]
                if rrh
                else job_suggestion or JOB_NUMBER_PLACEHOLDER
            )
        with questions if needs.job_number else corrections:
            st.selectbox(
                "Job number *",
                selectable_job_options,
                key=job_key,
                help=(
                    "The choices match Smartsheet exactly. Unity choices are "
                    "for Unity Health System in Arkansas; Rochester-area "
                    "Unity hospitals use RRH job numbers."
                ),
            )
    else:
        job_key = ""

    with corrections:
        purchase_route = st.selectbox(
            "How will this work or purchase be handled? *",
            PURCHASE_ROUTES,
            format_func=lambda route: PURCHASE_ROUTE_LABELS[route],
            key=route_key,
            help=(
                "Labor and rentals take priority. Equipment applies only to "
                "complete Group A equipment purchases."
            ),
        )

    with questions if needs.asset else corrections:
        selected_asset = _render_asset_control(
            analysis=analysis,
            quote_text=cached_quote,
            token=token,
            contract=contract,
            rrh=rrh,
            site=site,
            rrh_site_key=rrh_site_key,
        )

    with questions if needs.total else corrections:
        total_value = st.text_input(
            "PO/CO amount — final total including every fee and tax *",
            key=total_key,
            help=(
                "Use the final amount payable, including sales tax, freight, "
                "delivery, surcharges, and any other quoted fees."
            ),
        ).strip()

    with questions if needs.vendor else corrections:
        st.text_input("Vendor name *", key=vendor_key)

    with questions if needs.contact_name else corrections:
        st.text_input("Vendor representative name *", key=contact_key)

    with questions if needs.contact_email else corrections:
        st.text_input(
            "Vendor representative email *",
            key=email_key,
            help="Enter the representative's complete email address.",
        )

    if remembered_contact_active:
        st.caption(
            "Vendor representative filled from prior requests for this vendor "
            "on this account."
        )

    with questions if needs.description else corrections:
        st.text_input(
            "Short description (20 characters maximum) *",
            max_chars=20,
            key=description_key,
        )

    if instructions_value:
        with corrections:
            st.text_area(
                "Additional information (optional)",
                key=instructions_key,
                help="Only add a note the Smartsheet reviewer needs to see.",
            )

    requester_value = ""
    requester_key = ""
    if contract:
        requester_key = f"requester_{token}_{contract}"
        if requester_key not in st.session_state:
            st.session_state[requester_key] = remembered_device_account_manager(
                browser_token, contract
            )
        with questions:
            requester_value = st.text_input(
                "Your name (Requester / Asset Manager) *",
                key=requester_key,
                placeholder="Enter your name once",
                help=(
                    "After a successful package, this browser remembers the most "
                    "recent name for this ENFRA account."
                ),
            ).strip()

    if not instructions_value and st.toggle(
        "Add Additional Information",
        key=f"show_optional_{token}",
        help="Use this only when the Smartsheet reviewer needs an extra note.",
    ):
        st.text_area(
            "Additional information (optional)",
            key=instructions_key,
            placeholder="Only enter something the Smartsheet reviewer needs",
        )

    with corrections:
        st.caption(
            "Request Completed, PO #, and Work Order # stay blank. Dispatch to "
            "Service Center is NA. Original PO Number is sent only for a change order."
        )

    classification = None
    classification_error = ""
    try:
        classification = classify_po(purchase_route, total_value)
    except ValueError as exc:
        classification_error = str(exc)

    asset_id = normalize_asset_id(selected_asset)
    summary_route = PURCHASE_ROUTE_LABELS.get(purchase_route, "Route not found")
    summary_primary = (
        f"{REQUEST_TYPE_LABELS.get(request_type, request_type)} · "
        f"{contract or 'Account needed'} · {site or 'Site needed'} · "
        f"{category_label or 'Category needed'} / {cost_code or 'Cost code needed'}"
    )
    summary_detail = (
        f"{summary_route} · "
        f"{classification.object_account if classification else 'Account pending'} · "
        f"{classification.agreement_type if classification else 'Agreement pending'} · "
        f"Asset: {asset_id or 'None'} · Total: {total_value or 'Needed'}"
    )
    st.markdown(
        f'<div class="request-summary"><strong>{_h(summary_primary)}</strong>'
        f'<span class="request-summary-detail">{_h(summary_detail)}</span></div>',
        unsafe_allow_html=True,
    )

    draft_problems: list[str] = []
    if not contract:
        draft_problems.append("choose the contract")
    if not site:
        draft_problems.append("choose the site")
    if not cost_code:
        draft_problems.append("enter the job cost code")
    if not requester_value:
        draft_problems.append("enter your name")
    if (
        not job_key
        or str(st.session_state.get(job_key, "") or "").strip()
        in {"", JOB_NUMBER_PLACEHOLDER}
    ):
        draft_problems.append("confirm the job number")
    if request_type == "CHANGE ORDER" and not str(
        st.session_state.get(original_po_key, "")
    ).strip():
        draft_problems.append("enter the original PO number")
    if not str(st.session_state.get(vendor_key, "")).strip():
        draft_problems.append("confirm the vendor name")
    if not str(st.session_state.get(description_key, "")).strip():
        draft_problems.append("confirm the short description")
    if selected_asset == ASSET_PLACEHOLDER:
        draft_problems.append("choose the specific asset or No asset applies")
    if not str(st.session_state.get(contact_key, "")).strip():
        draft_problems.append("enter the vendor representative name")
    contact_email = str(st.session_state.get(email_key, "")).strip()
    if not required_email_is_valid(contact_email):
        draft_problems.append("enter a valid vendor representative email")
    parsed_total = parse_amount(total_value)
    if parsed_total is None or parsed_total <= 0:
        draft_problems.append("enter a valid final PO/CO amount greater than zero")
    if classification_error and parsed_total is not None and parsed_total > 0:
        draft_problems.append(classification_error)

    if draft_problems:
        concise_problems = [
            problem.rstrip(". ") for problem in dict.fromkeys(draft_problems)
        ]
        st.warning(
            "Before generating: " + "; ".join(concise_problems) + "."
        )

    selected_contract, selected_site, facility_name, _ = _routing_for_generation(
        analysis, cached_quote, token
    )
    current_pdf_signature = _document_signature(
        token,
        selected_contract,
        selected_site,
        final_inclusions,
        final_exclusions,
        vendor=str(st.session_state.get(vendor_key, "") or "").strip(),
        scope=str(getattr(analysis, "scope_of_work", "") or "").strip(),
    )
    if (
        st.session_state.get("scope_pdf_bytes")
        and st.session_state.get("scope_pdf_signature") != current_pdf_signature
    ):
        st.session_state.pop("scope_pdf_bytes", None)
        st.session_state.pop("scope_pdf_signature", None)
        st.warning(
            "A PDF-bearing detail changed. Generate the package again before "
            "opening Smartsheet."
        )

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num yellow">3</div>
            <p class="step-title">Generate files and open Smartsheet</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "One button creates the Scope/Inclusions/Exclusions PDF, keeps the "
        "unchanged quote, and prepares the prefilled Smartsheet link."
    )
    generated_key = f"generated_context_{token}"
    if st.button(
        "Generate both files and Smartsheet link",
        type="primary",
        width="stretch",
        key=f"generate_package_{token}",
        disabled=bool(draft_problems),
    ):
        try:
            scope_pdf = build_scope_pdf(
                scope=analysis.scope_of_work,
                inclusions=final_inclusions,
                exclusions=final_exclusions,
                vendor=str(st.session_state.get(vendor_key, "") or ""),
                site=facility_name or selected_site,
            )
        except Exception as exc:
            st.error(f"PDF generation failed: {exc}")
        else:
            st.session_state["scope_pdf_bytes"] = scope_pdf
            st.session_state["scope_pdf_signature"] = current_pdf_signature
            context = build_po_context(st.session_state)
            if context is not None:
                st.session_state[generated_key] = context.context_id
                memory_ready = (
                    context.ready
                    and not validate_submission_fields(context.fields)
                    and not preflight_attachments(context.attachments)
                )
                if memory_ready and contract:
                    record_device_account_manager(
                        device_token=browser_token,
                        account=contract,
                        manager_name=context.fields.get("requester_name"),
                        context_id=account_manager_memory_context_id(context),
                    )
                    record_vendor_contact(
                        contract=contract,
                        vendor=context.fields.get("vendor"),
                        contact_name=context.fields.get("contact_name"),
                        contact_email=context.fields.get("contact_email"),
                        context_id=vendor_contact_memory_context_id(context),
                    )

    context = build_po_context(st.session_state)
    generated_context = st.session_state.get(generated_key, "")
    if context is not None and generated_context == context.context_id:
        render_inline_smartsheet_handoff(context)
    elif generated_context:
        st.info("A detail changed. Use the button again to refresh both files and the link.")

    _render_footer()


if __name__ == "__main__":
    main()
