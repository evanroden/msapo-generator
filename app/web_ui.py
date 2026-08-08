"""Streamlit interface for Purchase Order Process Control.

The application converts a reviewed vendor quote into a prefilled Smartsheet PO
request and a two-file supporting package: the unchanged quote plus a concise
Scope/Inclusions/Exclusions PDF. It does not create or send email.
"""

from __future__ import annotations

import hashlib
import html
import re
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
from app.memory import (
    record_device_account_manager,
    remembered_device_account_manager,
)
from app.ocr import extract_text
from app.po_context import (
    _document_signature,
    account_manager_memory_context_id,
    build_po_context,
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
    RRH_JOB_NUMBERS,
    preflight_attachments,
    validate_submission_fields,
)
from app.smartsheet_inline import render_inline_smartsheet_handoff


SITE_LABEL_TO_KEY = {label: key for key, label in FACILITY_SHORT_NAMES.items()}
SITE_LABELS = list(FACILITY_SHORT_NAMES.values())
CONTRACT_PLACEHOLDER = "— Select a contract —"
SITE_PLACEHOLDER = "— Select a site —"
ASSET_NONE = "None Applicable"
REQUEST_TYPE_LABELS = {
    "PO": "New purchase order",
    "CHANGE ORDER": "Change order to an existing PO",
}


CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Inter:wght@400;500;600;700;800&display=swap');

    .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        background:
            radial-gradient(1200px 500px at 15% -10%, #FFE9D6 0%, transparent 55%),
            radial-gradient(1000px 460px at 100% 0%, #E7E1FF 0%, transparent 50%),
            #F6F7FB;
    }
    #MainMenu, footer, header {visibility: hidden;}

    .block-container {
        max-width: 1000px !important;
        padding-top: 1.4rem !important;
        padding-bottom: 3rem !important;
    }

    /* ── Hero ─────────────────────────────────────────────── */
    .hero {
        background: linear-gradient(130deg, #12314F 0%, #1C4A73 55%, #2E6AA0 100%);
        padding: 2.1rem 2.4rem;
        border-radius: 22px;
        margin-bottom: 0.4rem;
        position: relative;
        overflow: hidden;
        box-shadow: 0 18px 40px rgba(18,49,79,0.28);
    }
    .hero::after {
        content: '';
        position: absolute; inset: 0;
        background-image: radial-gradient(rgba(255,255,255,0.10) 1px, transparent 1px);
        background-size: 22px 22px;
        opacity: 0.5;
        pointer-events: none;
    }
    .hero-emoji {
        font-size: 2.6rem;
        display: inline-block;
        animation: bob 3.2s ease-in-out infinite;
        filter: drop-shadow(0 6px 10px rgba(0,0,0,0.25));
    }
    @keyframes bob { 0%,100%{transform: translateY(0) rotate(-4deg);} 50%{transform: translateY(-9px) rotate(4deg);} }
    .hero h1 {
        font-family: 'Fraunces', Georgia, serif;
        color: #FFFFFF;
        font-size: 2.35rem;
        font-weight: 700;
        margin: 0.4rem 0 0.3rem 0;
        letter-spacing: -0.02em;
        line-height: 1.05;
        position: relative;
    }
    .hero h1 .zing { color: #FFC79A; }
    .hero-subtitle {
        color: rgba(255,255,255,0.78);
        font-size: 0.98rem;
        margin: 0;
        position: relative;
        max-width: 34rem;
    }

    /* ── Byline / secret test trigger ─────────────────────── */
    div[data-testid="stButton"] > button[kind="secondary"] {
        background: transparent;
        border: none;
        color: #B0447A;
        font-weight: 700;
        font-size: 0.82rem;
        padding: 0.25rem 0.5rem;
        box-shadow: none;
        letter-spacing: 0.01em;
    }
    div[data-testid="stButton"] > button[kind="secondary"]:hover {
        background: transparent;
        color: #F0803C;
        text-decoration: underline;
        transform: none;
        box-shadow: none;
    }

    /* ── Section headers ──────────────────────────────────── */
    .step-header { display:flex; align-items:center; gap:0.7rem; margin: 1.4rem 0 0.7rem; }
    .step-num {
        width: 30px; height: 30px; border-radius: 9px;
        display:flex; align-items:center; justify-content:center;
        font-size: 0.85rem; font-weight: 800; color:#fff; flex-shrink:0;
        box-shadow: 0 4px 10px rgba(0,0,0,0.12);
    }
    .step-num.navy   { background:#12314F; }
    .step-num.orange { background:#F0803C; }
    .step-num.grape  { background:#6D5AE6; }
    .step-num.mint   { background:#16A34A; }
    .step-title { font-family:'Fraunces', Georgia, serif; font-size:1.3rem; font-weight:700; color:#12233B; margin:0; }

    /* ── Cards / metrics ──────────────────────────────────── */
    .metric-card {
        background: #fff; border: 1px solid #ECE7F5; border-radius: 16px;
        padding: 1rem 1.15rem; box-shadow: 0 6px 16px rgba(20,20,50,0.05);
        transition: transform .18s ease, box-shadow .18s ease; height: 100%;
    }
    .metric-card:hover { transform: translateY(-3px); box-shadow: 0 12px 26px rgba(20,20,50,0.10); }
    .metric-icon { font-size: 1.35rem; margin-bottom: 0.3rem; }
    .metric-label { font-size: 0.64rem; font-weight: 800; color:#9AA0B4; text-transform: uppercase; letter-spacing: 0.09em; }
    .metric-value { font-size: 1.05rem; font-weight: 800; color:#111827; margin-top:0.15rem; line-height:1.25; }
    .tax-included { color:#16A34A; } .tax-excluded { color:#F0803C; } .tax-unclear { color:#DC2626; }

    .facility-banner {
        background: linear-gradient(120deg,#F1F6FF,#F6F1FF);
        border: 1px solid #DDE4F5; border-left: 5px solid #2E6AA0;
        border-radius: 14px; padding: 0.95rem 1.2rem; margin: 0.4rem 0 0.2rem;
        display:flex; align-items:center; gap:0.8rem;
    }
    .facility-icon { font-size: 1.5rem; }
    .facility-name { font-weight: 800; color:#12233B; font-size:0.98rem; }
    .facility-address { color:#64748B; font-size:0.82rem; margin-top:0.1rem; }

    .alert-box { border-radius:12px; padding:0.85rem 1.1rem; margin:0.5rem 0; font-size:0.87rem; line-height:1.5; display:flex; gap:0.6rem; }
    .alert-warning { background:#FFFBEB; border:1px solid #FDE68A; color:#92400E; }
    .alert-danger  { background:#FEF2F2; border:1px solid #FECACA; color:#991B1B; }
    .alert-success { background:#F0FDF4; border:1px solid #BBF7D0; color:#166534; }

    .scope-section { background:#FBFAFF; border:1px solid #ECE7F5; border-radius:12px; padding:1.05rem 1.2rem; margin-bottom:0.7rem; }
    .scope-label { font-size:0.66rem; font-weight:800; color:#12314F; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:0.5rem; padding-bottom:0.35rem; border-bottom:2px solid #F0803C; display:inline-block; }
    .scope-text { color:#334155; font-size:0.88rem; line-height:1.6; margin:0; }

    .cost-code-pill {
        background:#12314F; color:#fff; border-radius:10px; padding:0.55rem 0.9rem;
        font-size:1.05rem; font-weight:800; letter-spacing:0.02em; margin-top:0.25rem;
        display:flex; align-items:center; gap:0.5rem; box-shadow:0 6px 14px rgba(18,49,79,0.22);
    }
    .field-label { font-size:0.8rem; font-weight:700; color:#334155; margin-bottom:0.15rem; }

    /* ── Buttons ──────────────────────────────────────────── */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg,#F0803C 0%,#E5661C 100%);
        border:none; border-radius:12px; font-weight:800; font-size:0.98rem;
        padding:0.7rem 1.5rem; box-shadow:0 8px 20px rgba(240,128,60,0.30);
        transition: all .2s ease;
    }
    .stButton > button[kind="primary"]:hover { transform: translateY(-2px); box-shadow:0 12px 26px rgba(240,128,60,0.42); }

    div[data-testid="stFileUploader"] section {
        border-radius:16px; border:2px dashed #C8BEE8; background:#FBFAFF;
    }
    div[data-testid="stFileUploader"] section:hover { border-color:#F0803C; }
    div[data-testid="stExpander"] { border-radius:14px; border:1px solid #ECE7F5; background:#fff; }

    .app-footer { text-align:center; padding:2rem 1rem 0.5rem; color:#9AA0B4; font-size:0.78rem; }
    .app-footer a { color:#F0803C; text-decoration:none; font-weight:700; }
    .footer-divider { width:44px; height:3px; background:linear-gradient(90deg,#F0803C,#6D5AE6); border-radius:2px; margin:0 auto 0.8rem; }
    hr { border:none; border-top:1px solid #ECE7F5; margin:1.1rem 0; }
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
    """Resolve the reviewed contract/site for the generated scope PDF."""
    detected_contract, detected_site = contracts.match_facility(
        analysis.facility_name, quote_text
    )
    contract = st.session_state.get(f"contract_{token}") or detected_contract or ""
    if contract == CONTRACT_PLACEHOLDER:
        contract = ""

    if contracts.is_rrh(contract):
        facility_key = facility_key_from_name(analysis.facility_name)
        default_site = FACILITY_SHORT_NAMES.get(facility_key) if facility_key else ""
        site = st.session_state.get(f"site_{token}") or default_site or ""
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
            st.session_state.get(f"gsite_{token}_{contract}")
            or st.session_state.get(f"gsitetxt_{token}_{contract}")
            or (detected_site if contract == detected_contract else "")
            or (sites[0] if len(sites) == 1 else "")
        )
        if site == SITE_PLACEHOLDER:
            site = ""
        address = analysis.facility_address if site and site == detected_site else ""
        return contract, site, site or analysis.facility_name, address

    return "", detected_site or "", analysis.facility_name, analysis.facility_address


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
    st.session_state["last_sig"] = hashlib.sha256(
        quote_text.encode("utf-8")
    ).hexdigest()
    st.session_state["extracted_text"] = quote_text
    st.session_state["uploaded_file_bytes"] = quote_bytes
    st.session_state["uploaded_file_name"] = "Sample_Quote.txt"
    st.session_state["extract_hash"] = hashlib.sha256(quote_bytes).hexdigest()
    st.session_state.pop("scope_pdf_bytes", None)
    st.session_state.pop("scope_pdf_signature", None)


def _render_routing_controls(
    analysis: QuoteAnalysis,
    quote_text: str,
    token: str,
) -> tuple[str, bool, str, str, str, str | None]:
    """Render contract/site/cost-code controls using the established keys."""
    detected_contract, detected_site = contracts.match_facility(
        analysis.facility_name, quote_text
    )
    contract_options = [CONTRACT_PLACEHOLDER] + contracts.contract_names()
    default_index = (
        contract_options.index(detected_contract)
        if detected_contract in contract_options
        else 0
    )
    contract = st.selectbox(
        "Contract *",
        contract_options,
        index=default_index,
        key=f"contract_{token}",
    )
    if contract == CONTRACT_PLACEHOLDER:
        return "", False, "", "", "", None

    rrh = contracts.is_rrh(contract)
    if rrh:
        facility_key = facility_key_from_name(analysis.facility_name)
        default_site = FACILITY_SHORT_NAMES.get(facility_key) if facility_key else None
        site_options = [SITE_PLACEHOLDER] + SITE_LABELS
        site_index = (
            site_options.index(default_site) if default_site in site_options else 0
        )
        columns = st.columns(3)
        with columns[0]:
            site = st.selectbox(
                "Site *", site_options, index=site_index, key=f"site_{token}"
            )
        if site == SITE_PLACEHOLDER:
            return contract, rrh, "", "", "", None
        site_key = SITE_LABEL_TO_KEY[site]
        valid_categories = valid_categories_for_site(site_key)
        category_labels = [
            WORK_CATEGORY_DISPLAY.get(item, item) for item in valid_categories
        ]
        default_category = (
            valid_categories.index(analysis.work_category)
            if analysis.work_category in valid_categories
            else 0
        )
        with columns[1]:
            category_label = st.selectbox(
                "Work category",
                category_labels,
                index=default_category,
                key=f"cat_{token}_{site_key}",
            )
        category_key = valid_categories[category_labels.index(category_label)]
        cost_code = lookup_cost_code(site_key, category_key) or ""
        with columns[2]:
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
        return contract, rrh, site, category_label, cost_code, site_key

    sites = contracts.sites_for_contract(contract)
    columns = st.columns(3)
    with columns[0]:
        if sites:
            site_options = [SITE_PLACEHOLDER] + sites
            site_index = (
                site_options.index(detected_site)
                if contract == detected_contract and detected_site in site_options
                else 0
            )
            site = st.selectbox(
                "Site *",
                site_options,
                index=site_index,
                key=f"gsite_{token}_{contract}",
            )
            if site == SITE_PLACEHOLDER:
                site = ""
        else:
            site = st.text_input(
                "Site *",
                key=f"gsitetxt_{token}_{contract}",
                placeholder="Enter the site",
            )
    with columns[1]:
        category_label = st.text_input(
            "Work category",
            value=WORK_CATEGORY_DISPLAY.get(
                analysis.work_category, analysis.work_category or ""
            ),
            key=f"gcat_{token}_{contract}",
        )
    with columns[2]:
        cost_code = st.text_input(
            "Job cost code *",
            key=f"gcost_{token}_{contract}",
            placeholder="Paste the cost code",
        )
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
    if not uids:
        st.caption(
            "No asset registry is configured for this site; Asset ID will be blank."
        )
        return ASSET_NONE

    labels = {asset["uid"]: contracts.asset_label(asset) for asset in site_assets}
    broad_guess = guess_asset_uid(
        site_assets,
        quote_text=quote_text,
        hint=analysis.asset_reference,
    )
    guess = exact_guess if exact_guess in uids else broad_guess
    options = [ASSET_NONE, *uids]
    index = options.index(guess) if guess in options else 0
    raw_asset = st.selectbox(
        "Specific asset",
        options,
        index=index,
        format_func=lambda uid: (
            "No asset applies"
            if uid == ASSET_NONE
            else f"{labels[uid]} · {uid}"
        ),
        key=f"asset_{token}_{contract}_{site}",
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
            Built by <a href="mailto:evan.roden@ENFRAsolutions.com">Evan Roden</a>
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

    st.markdown(
        """
        <div class="hero">
            <span class="hero-emoji">📋</span>
            <h1>Purchase Order <span class="zing">Process Control</span></h1>
            <p class="hero-subtitle">
                Upload a vendor quote, confirm the PO rules, build the two-file
                supporting package, and open a prefilled Smartsheet request.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([2, 3, 2])
    with center:
        if st.button(
            "Built by Evan Roden",
            key="name_test",
            use_container_width=True,
            help="Click to load a synthetic sample.",
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
    upload_tab, paste_tab = st.tabs(["📁 Upload file", "📝 Paste text"])
    quote_text = ""

    with upload_tab:
        uploaded = st.file_uploader(
            "Upload quote",
            type=[
                "pdf", "png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp",
                "heic", "heif", "hif", "txt",
            ],
            label_visibility="collapsed",
            key=f"uploader_{st.session_state.get('uploader_nonce', 0)}",
        )
        if uploaded is not None:
            file_bytes = uploaded.getvalue()
            st.session_state["uploaded_file_bytes"] = file_bytes
            st.session_state["uploaded_file_name"] = uploaded.name
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            if st.session_state.get("extract_hash") != file_hash:
                with st.spinner("Reading the quote…"):
                    try:
                        st.session_state["extracted_text"] = extract_text(
                            file_bytes, uploaded.name
                        )
                    except Exception as exc:
                        st.error(f"Could not read that file: {exc}")
                        st.session_state["extracted_text"] = ""
                st.session_state["extract_hash"] = file_hash
            quote_text = st.session_state.get("extracted_text", "")
            if quote_text:
                with st.expander("Preview extracted text", expanded=False):
                    st.text_area(
                        "Raw text",
                        quote_text,
                        height=170,
                        disabled=True,
                        label_visibility="collapsed",
                    )
            else:
                st.warning(
                    "No readable text was found. Try a clearer file or paste the quote text."
                )

    with paste_tab:
        pasted = st.text_area(
            "Paste the full vendor quote text",
            height=200,
            placeholder="Paste the vendor quote here…",
            label_visibility="collapsed",
        )
        if pasted.strip():
            quote_text = pasted.strip()

    if quote_text.strip():
        full_signature = hashlib.sha256(
            quote_text.encode("utf-8", "ignore")
        ).hexdigest()
        if st.session_state.get("last_sig") != full_signature:
            with st.spinner("Reading the quote and extracting the PO details…"):
                try:
                    analysis = analyze_quote(quote_text)
                except Exception as exc:
                    st.error(f"Analysis failed: {exc}")
                    st.stop()
            st.session_state["analysis"] = analysis
            st.session_state["analysis_token"] = full_signature[:12]
            st.session_state["last_sig"] = full_signature
            st.session_state["quote_text"] = quote_text
            st.session_state.pop("scope_pdf_bytes", None)
            st.session_state.pop("scope_pdf_signature", None)

    analysis: QuoteAnalysis | None = st.session_state.get("analysis")
    if analysis is None:
        st.info("Upload or paste a quote above. It will be analyzed automatically.")
        _render_footer()
        return

    token = st.session_state.get("analysis_token", "x")
    cached_quote = st.session_state.get("quote_text", "")

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num mint">2</div>
            <p class="step-title">Review the extracted work</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    metrics = st.columns(3)
    with metrics[0]:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Vendor</div>'
            f'<div class="metric-value">{_h(analysis.vendor_name or "—")}</div></div>',
            unsafe_allow_html=True,
        )
    with metrics[1]:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Site found</div>'
            f'<div class="metric-value">{_h(analysis.facility_name or "—")}</div></div>',
            unsafe_allow_html=True,
        )
    with metrics[2]:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Quote total</div>'
            f'<div class="metric-value">{_h(analysis.total_amount or "—")}</div></div>',
            unsafe_allow_html=True,
        )

    if analysis.facility_name:
        st.markdown(
            f'<div class="facility-banner"><div class="facility-icon">🏥</div>'
            f'<div><div class="facility-name">{_h(analysis.facility_name)}</div>'
            f'<div class="facility-address">{_h(analysis.facility_address)}</div></div></div>',
            unsafe_allow_html=True,
        )
    if analysis.tax_warning:
        st.warning(analysis.tax_warning)

    final_inclusions: list[str] = []
    final_exclusions: list[str] = []
    unified_inclusions, unified_exclusions = _build_unified_lists(analysis)
    with st.expander(
        "Review scope, inclusions, and exclusions (optional)",
        expanded=False,
    ):
        st.caption(
            "The tool selected everything below for the supporting PDF. "
            "Only change an item if the quote was interpreted incorrectly."
        )
        st.markdown(
            f'<div class="scope-section"><div class="scope-label">Scope</div>'
            f'<p class="scope-text" style="white-space:pre-line;">'
            f'{_h(analysis.scope_of_work)}</p></div>',
            unsafe_allow_html=True,
        )
        inclusion_column, exclusion_column = st.columns(2)
        with inclusion_column:
            st.markdown(
                '<div class="scope-label">Inclusions</div>',
                unsafe_allow_html=True,
            )
            for index, (text_value, is_ai) in enumerate(unified_inclusions):
                if st.checkbox(
                    f"{'✎ ' if is_ai else ''}{text_value}",
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
                    f"{'✎ ' if is_ai else ''}{text_value}",
                    key=f"exc_{token}_{index}",
                    value=True,
                ):
                    final_exclusions.append(text_value)
        if any(is_ai for _, is_ai in unified_inclusions + unified_exclusions):
            st.caption("✎ = suggested by the tool rather than stated in the quote")

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num orange">3</div>
            <p class="step-title">Confirm the PO details</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    contract, rrh, site, _category_label, _cost_code, rrh_site_key = (
        _render_routing_controls(analysis, cached_quote, token)
    )
    if not contract:
        st.warning("Choose the contract.")
    elif not site:
        st.warning("Choose or enter the site.")

    request_type_key = f"request_type_{token}"
    request_type_guess = str(
        getattr(analysis, "request_type_guess", "") or "PO"
    ).strip()
    if request_type_guess not in REQUEST_TYPE_LABELS:
        request_type_guess = "PO"
    if request_type_key not in st.session_state:
        st.session_state[request_type_key] = request_type_guess
    request_type = st.selectbox(
        "What kind of request is this? *",
        tuple(REQUEST_TYPE_LABELS),
        format_func=lambda value: REQUEST_TYPE_LABELS[value],
        key=request_type_key,
        help="The tool guesses this from the quote. Change it only if needed.",
    )
    if request_type == "CHANGE ORDER":
        original_po_key = f"original_po_{token}"
        if original_po_key not in st.session_state:
            st.session_state[original_po_key] = str(
                getattr(analysis, "original_po_number", "") or ""
            ).strip()
        st.text_input(
            "Original PO number *",
            key=original_po_key,
            placeholder="Required for a change order",
        )

    if contract:
        requester_key = f"requester_{token}_{contract}"
        if requester_key not in st.session_state:
            st.session_state[requester_key] = remembered_device_account_manager(
                browser_token, contract
            )
        st.text_input(
            "Your name (Requester / Asset Manager) *",
            key=requester_key,
            placeholder="Enter your name once",
            help=(
                "After a successful package, this browser remembers the most "
                "recent name for this ENFRA account."
            ),
        )

        job_key = f"job_number_{token}_{contract}"
        if rrh:
            if st.session_state.get(job_key) not in RRH_JOB_NUMBERS:
                st.session_state[job_key] = RRH_JOB_NUMBERS[0]
            st.selectbox(
                "Job number *",
                RRH_JOB_NUMBERS,
                key=job_key,
                help="RRH O&M is selected automatically for most requests.",
            )
        else:
            st.text_input(
                "Job number *",
                key=job_key,
                placeholder="Enter the account job number",
            )

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
    purchase_route = st.selectbox(
        "How will this work or purchase be handled? *",
        PURCHASE_ROUTES,
        format_func=lambda route: PURCHASE_ROUTE_LABELS[route],
        key=route_key,
        help=(
            "The tool guesses from the quote. Labor and rentals take priority; "
            "equipment applies only to complete Group A equipment purchases."
        ),
    )

    _render_asset_control(
        analysis=analysis,
        quote_text=cached_quote,
        token=token,
        contract=contract,
        rrh=rrh,
        site=site,
        rrh_site_key=rrh_site_key,
    )

    total_value = st.text_input(
        "PO/CO amount — final total including every fee and tax *",
        value=analysis.total_amount or "",
        key=f"total_{token}",
        help=(
            "Use the final amount payable, including sales tax, freight, delivery, "
            "surcharges, and any other quoted fees."
        ),
    )

    vendor_key = f"vendor_{token}"
    if vendor_key not in st.session_state:
        st.session_state[vendor_key] = analysis.vendor_name or ""
    st.text_input("Vendor name *", key=vendor_key)

    contact_columns = st.columns(3)
    with contact_columns[0]:
        st.text_input(
            "Vendor contact name",
            value=analysis.contact_name or "",
            key=f"contact_{token}",
        )
    with contact_columns[1]:
        st.text_input(
            "Vendor contact email",
            value=analysis.contact_email or "",
            key=f"cemail_{token}",
        )
    with contact_columns[2]:
        st.text_input(
            "Short description (≤20 chars)",
            value=(analysis.short_description or "")[:20],
            max_chars=20,
            key=f"desc_{token}",
        )

    st.text_area(
        "Additional information (optional)",
        key=f"instructions_{token}",
        placeholder="Leave blank unless Smartsheet needs another note",
        help="Only add a note that the Smartsheet reviewer needs to see.",
    )

    try:
        classification = classify_po(purchase_route, total_value)
        st.success(
            "The tool will use "
            f"**{classification.object_account}** and "
            f"**{classification.agreement_type}** in Smartsheet."
        )
    except ValueError as exc:
        st.warning(str(exc))

    st.caption(
        "The tool leaves Request Completed, PO #, and Work Order # blank and "
        "sets Dispatch WO to Service Center to NA. Original PO Number is sent "
        "only for a change order."
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
    )
    if (
        st.session_state.get("scope_pdf_bytes")
        and st.session_state.get("scope_pdf_signature") != current_pdf_signature
    ):
        st.session_state.pop("scope_pdf_bytes", None)
        st.session_state.pop("scope_pdf_signature", None)
        st.warning(
            "The site, contract, inclusions, or exclusions changed. Rebuild the "
            "supporting PDF before opening Smartsheet."
        )

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num grape">4</div>
            <p class="step-title">Generate both files and the Smartsheet link</p>
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
        use_container_width=True,
        key=f"generate_package_{token}",
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
            st.stop()
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

    context = build_po_context(st.session_state)
    generated_context = st.session_state.get(generated_key, "")
    if context is not None and generated_context == context.context_id:
        render_inline_smartsheet_handoff(context)
    elif generated_context:
        st.info("A detail changed. Use the button again to refresh both files and the link.")

    _render_footer()


if __name__ == "__main__":
    main()
