"""Streamlit interface for Purchase Order Process Control.

The application converts a reviewed vendor quote into a prefilled Smartsheet PO
request and a two-file supporting package: the unchanged quote plus a concise
MSAPO form PDF. It does not create or send email.

What depends on this module
---------------------------
``run_web.py`` -- and therefore the deployed container -- calls :func:`main`.
``app.expense_ui.render_expense_workflow`` is the other half of the same page;
the workflow selector at the top of :func:`main` picks one of the two. The
import therefore runs one way only: this module imports the expense page, never
the reverse. That is why the shared "still needs a value" highlight lives in
``app.ui_highlight`` instead of here -- importing it back from this module would
be a cycle.

Where the truth actually lives
------------------------------
This page RENDERS and COLLECTS; it does not decide. The Smartsheet-facing
snapshot is rebuilt from ``st.session_state`` by ``app.po_context``, the routing
rules live in ``app.po_rules``, and the question/correction placement rules live
in ``app.workflow_review``. Several session-state key formats (``contract_``,
``site_``, ``gsite_``, ``gsitetxt_``, ``cat_``, ``manualcost_``, ``gcat_``,
``gcost_``, ``asset_``, ``inc_``, ``exc_``, ``scope_``, ``desc_``, ``total_``,
``vendor_``, ``contact_``, ``cemail_``, ``instructions_``, ``requester_``,
``job_number_``) are read back by ``app.po_context`` by exact string. Renaming a
key here does not raise anywhere: po_context just reads a missing key, falls
back to its default, and the field silently reaches Smartsheet blank or stale.

A warning about editing this file at all
----------------------------------------
``tests/test_smartsheet_handoff_entrypoint.py`` reads this file as PLAIN TEXT
and asserts both on exact substrings and on their exact COUNTS -- how many step
headers exist, how many PDF-builder calls, how many generate labels. A comment
that merely quotes one of those phrases changes a count and fails the suite with
no logic change whatsoever. Read that test before adding prose here.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import streamlit as st

from app import contracts
from app.ui_highlight import highlight_needed_fields
from app.asset_guess import guess_asset_uid, lowest_numbered_of_type
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
from app.smartsheet import AGREEMENT_TYPE_OPTIONS, OBJECT_ACCOUNT_OPTIONS
from app.po_rules import (
    PURCHASE_ROUTE_LABELS,
    PURCHASE_ROUTES,
    classify_po,
    infer_purchase_route,
    normalize_asset_id,
    parse_amount,
)
from app.quote_analyzer import AIAssumption, QuoteAnalysis, analyze_quote
from app.document_generator import build_msapo_pdf
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
# The five em-dash strings below are "the operator has not chosen yet" sentinels
# that ride inside real option lists, because a Streamlit selectbox has no empty
# state. Two properties are load-bearing:
#
#   * they must never collide with a real contract, site, job number or asset
#     UID. The em-dash wrapper is what guarantees that -- no catalog entry in
#     app/data/contracts.json or app/job_numbers.py looks like this.
#   * ``app.po_context`` keeps its OWN copies of the contract and site literals
#     (``_CONTRACT_PLACEHOLDER``, ``_SITE_PLACEHOLDER``) and compares session
#     values against them. Changing a literal here without changing it there
#     raises nothing: po_context stops recognising the placeholder and exports
#     the prompt text itself into the Smartsheet SITE field as though the
#     operator had typed it. SILENT, and visible only on the submitted form.
#
# ASSET_NONE is the same kind of shared literal: ``po_rules.normalize_asset_id``
# maps "none applicable" (case-folded) to an empty Asset ID, and
# ``po_context._asset_value`` writes this exact spelling as its own default.
CONTRACT_PLACEHOLDER = "— Select a contract —"
SITE_PLACEHOLDER = "— Select a site —"
CATEGORY_PLACEHOLDER = "— Select a work category —"
JOB_NUMBER_PLACEHOLDER = "— Select a job number —"
ASSET_NONE = "None Applicable"
ASSET_PLACEHOLDER = "— Choose an asset or No asset —"
# Keys, not labels, are what reach Smartsheet and what po_context re-validates
# against {"PO", "CHANGE ORDER"}. The dict is also the option ORDER for the
# selectbox, so "PO" first is deliberate: it is the overwhelmingly common case
# and the fallback whenever the analyzer's guess is unrecognised.
REQUEST_TYPE_LABELS = {
    "PO": "New purchase order",
    "CHANGE ORDER": "Change order to an existing PO",
}


@dataclass(frozen=True)
class RoutingSnapshot:
    """Current routing values before their widgets are placed on the page.

    Exists because placement has to be decided BEFORE rendering. Each field goes
    to either the visible questions container or the collapsed corrections panel,
    and that choice depends on values the widgets have not produced yet this
    rerun. Reading session state up front is the only way to know.

    Reading it is also the only SAFE way. Writing a widget key after that widget
    has rendered is silently discarded by Streamlit -- and on the approver-style
    controls it additionally fires ``on_change``, so one ignored write cascades
    into a cleared field. See §2.2 of
    docs/COMMIT_NOTES_2026-08-13_EXPENSE_DISCLOSURE_AND_NEEDS_YOU_HIGHLIGHT.md.

    ``rrh_site_key`` is the FACILITIES dictionary key (for example
    "united_memorial"), not the short label the operator sees; it is None
    whenever the site has not resolved to a configured RRH facility.
    """

    contract: str
    rrh: bool
    site: str
    category_label: str
    cost_code: str
    rrh_site_key: str | None


# Every rule below that begins ``.st-key-`` depends on Streamlit emitting a
# container class named after a widget key. That coupling fails SILENTLY: rename
# the key in main() and the selector matches nothing -- no error, no warning,
# just an unstyled control. Two are live here (workflow_mode and
# load_synthetic_test); the highlight bar targets a third, po_needs_you, from
# app/ui_highlight.py.
#
# Three rules in this stylesheet currently match NOTHING. They are left in place
# because removal is a separate verified phase, but do not read them as evidence
# of a live style:
#   * ``.epc-needs-value`` -- the needs-a-value bar was first baked in here, then
#     moved to ``app.ui_highlight.highlight_needed_fields``, which emits the same
#     declarations per rerun. Emitting from the caller is precisely what makes
#     the bar transient. Nothing ever puts this class on an element. Its comment
#     is still the only record of WHY the mark is a left bar and not an outline,
#     so read it before restyling.
#   * ``.scope-section`` and ``.scope-text`` -- left from the read-only scope
#     preview that the inclusion/exclusion checkbox lists replaced.
#
# Related: the step-1 header markup in main() carries a second class token,
# ``navy``, for which no rule exists anywhere in this repository. It is harmless
# only because the base step-number style already paints the ocean colour. It is
# not a colour modifier; do not add a sibling token expecting one to work.
#
# tests/test_web_ui_app.py slices this string with ``str.split`` on exact
# selector text and then on the next "}". Reformatting a rule it slices -- even
# only the whitespace -- breaks those tests without changing a rendered pixel.
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

    /* Streamlit does not render its internal `kind` prop into the browser DOM.
       Single-select segments do expose stable radio semantics, including
       aria-checked, so style that accessible state directly. */
    .st-key-workflow_mode div[role="radiogroup"] {
        background: rgba(255,255,255,0.82) !important;
        border: 1px solid var(--enfra-concrete) !important;
        border-radius: 8px !important;
        box-sizing: border-box !important;
        column-gap: 4px !important;
        display: grid !important;
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        padding: 4px !important;
        row-gap: 0 !important;
        width: 100% !important;
    }
    .st-key-workflow_mode button[role="radio"] {
        -webkit-tap-highlight-color: transparent;
        border: 0 !important;
        border-radius: 5px !important;
        box-sizing: border-box !important;
        font-size: 1rem !important;
        font-weight: 700 !important;
        line-height: 1.2 !important;
        margin: 0 !important;
        max-width: none !important;
        min-height: 52px !important;
        min-width: 0 !important;
        padding: 0.7rem 0.85rem !important;
        touch-action: manipulation;
        white-space: normal !important;
        width: 100% !important;
    }
    .st-key-workflow_mode button[role="radio"][aria-checked="false"] {
        background: #FFFFFF !important;
        box-shadow: none !important;
        color: var(--enfra-ocean) !important;
    }
    .st-key-workflow_mode button[role="radio"][aria-checked="true"] {
        background: var(--enfra-ocean) !important;
        box-shadow: inset 0 -4px 0 var(--enfra-yellow) !important;
        color: #FFFFFF !important;
    }
    .st-key-workflow_mode button[role="radio"] p,
    .st-key-workflow_mode button[role="radio"] span {
        color: inherit !important;
        font-weight: inherit !important;
    }
    @media (hover: hover) and (pointer: fine) {
        .st-key-workflow_mode button[role="radio"][aria-checked="false"]:hover {
            background: var(--enfra-iced) !important;
        }
        .st-key-workflow_mode button[role="radio"][aria-checked="true"]:hover {
            background: #174B41 !important;
        }
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
    /* A field the operator still has to fill. Reuses the needs-banner idiom --
       a yellow left bar -- so the banner and the individual fields it refers to
       read as one system. Deliberately a LEFT BAR rather than a full outline,
       because a full outline in the same colour is the focus ring; the two must
       stay visually distinct or "needs a value" and "currently editing" become
       the same signal. The highlight disappears on the rerun after the field is
       filled, because placement/emission is recomputed from the live values. */
    .epc-needs-value {
        background: #FCFCF3;
        border-left: 4px solid var(--enfra-yellow);
        border-radius: 4px;
        padding: 0.35rem 0 0.35rem 0.7rem;
        margin: 0.25rem 0;
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

    .stButton > button[kind="primary"],
    [data-testid="stDownloadButton"] button[kind="primary"],
    [data-testid="stLinkButton"] a[kind="primary"] {
        background: var(--enfra-yellow);
        border: 2px solid var(--enfra-ocean);
        border-radius: 4px;
        box-shadow: 0 5px 14px rgba(9,43,36,0.18);
        color: var(--enfra-ocean);
        font-size: 0.98rem;
        font-weight: 700;
        min-height: 46px;
    }
    .stButton > button[kind="primary"] p,
    [data-testid="stDownloadButton"] button[kind="primary"] p,
    [data-testid="stLinkButton"] a[kind="primary"] p {
        color: inherit !important;
    }
    .stButton > button[kind="primary"]:hover,
    [data-testid="stDownloadButton"] button[kind="primary"]:hover,
    [data-testid="stLinkButton"] a[kind="primary"]:hover {
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
        .st-key-workflow_mode button[role="radio"] {
            font-size: 0.94rem !important;
            min-height: 56px !important;
            padding: 0.6rem 0.35rem !important;
        }
    }

    @media (pointer: coarse) {
        button, a[role="button"] { min-height: 44px; }
        div[data-testid="stCheckbox"] label { min-height: 44px; }
        input, textarea, [role="combobox"] { font-size: 16px !important; }

        /* One tap must place the caret. Without touch-action, WebKit holds the
           first tap while it watches for a second (double-tap-to-zoom), and on
           a text field that reads as the tap being ignored: the field shows the
           tap highlight but no caret or keyboard arrives until you tap again.
           "manipulation" keeps scrolling and pinch-zoom while dropping the
           double-tap gesture, which nothing here relies on.

           This already existed on the workflow selector buttons and was simply
           never applied to the inputs. */
        input, textarea, [role="combobox"],
        div[data-baseweb="input"], div[data-baseweb="base-input"],
        div[data-baseweb="textarea"], div[data-baseweb="select"] {
            touch-action: manipulation;
            -webkit-tap-highlight-color: transparent;
        }
        /* The visible box is a BaseWeb wrapper around a smaller input. Make the
           whole box read and behave as a text target so a tap near its edge
           lands on the field rather than on inert padding. */
        div[data-baseweb="input"], div[data-baseweb="base-input"],
        div[data-baseweb="textarea"] { cursor: text; }
        div[data-baseweb="input"] input,
        div[data-baseweb="base-input"] input { width: 100%; }
    }
</style>
"""


def _h(value: object) -> str:
    """Escape a value for interpolation into ``unsafe_allow_html`` markup.

    EVERY value that reaches an ``st.markdown(..., unsafe_allow_html=True)`` call
    on this page must go through this. The strings involved -- vendor name,
    facility name and address, cost code, category -- come from OCR text and from
    the model, so an apostrophe or an angle bracket in a real quote is enough to
    break the card layout, and a crafted quote would inject markup outright.

    ``value or ""`` deliberately collapses None to the empty string; no caller
    passes a numeric zero that would be wrongly blanked.
    """
    return html.escape(str(value or ""))


def _parse_amount(value: object) -> Decimal | None:
    """Compatibility wrapper around the canonical currency parser.

    Kept as a name because ``tests/test_web_ui_helpers.py`` imports it directly
    and pins the currency-format behaviour from this module. Do NOT reimplement
    the parsing here: ``po_rules.parse_amount`` deliberately REFUSES ambiguous
    input (an earlier version stripped every non-digit and silently turned "1e3"
    into 13), and the submission gate depends on rejection rather than repair.
    """
    return parse_amount(value)


def _pricing_difference(
    subtotal: object, tax: object, total: object
) -> Decimal | None:
    """Return subtotal plus tax minus total when all values are parseable.

    Returns None when ANY of the three is unparseable, so the caller cannot read
    a missing tax line as a zero discrepancy.

    No production call site remains: the live subtotal/tax/total reconciliation
    is ``po_context.build_po_context``, which raises the same comparison as a
    submission warning with a one-cent tolerance. Only
    ``tests/test_web_ui_helpers.py`` exercises this, so it is not dead by this
    project's definition -- but any change to the money rules belongs in
    po_rules/po_context, not here, or the two will disagree.
    """
    parsed = tuple(_parse_amount(value) for value in (subtotal, tax, total))
    if any(value is None for value in parsed):
        return None
    sub, sales_tax, grand_total = parsed
    return sub + sales_tax - grand_total


def _strip_ai_wrapper(text: str) -> str:
    """Unwrap an "[AI ESTIMATE: ...]" marker the analyzer may put on an item.

    The marker is how an inferred inclusion/exclusion is distinguished from one
    quoted verbatim; the wrapper is stripped for DISPLAY while the caller keeps
    the flag separately.

    ``app.po_context`` holds a byte-identical copy of this function. That
    duplication is load-bearing, not laziness: the checkbox keys are positional
    (``inc_<token>_<index>``), and po_context re-derives the same list to map
    each index back to an item. If the two ever strip differently, one list
    shifts by an entry and po_context attributes the operator's ticks to the
    WRONG inclusions -- with no error anywhere. Change both or neither.
    """
    match = re.search(r"\[AI ESTIMATE:\s*(.+?)\]", text)
    return match.group(1).strip() if match else text.strip()


def _build_unified_lists(
    analysis: QuoteAnalysis,
) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """Return de-duplicated inclusion/exclusion choices with AI flags.

    Each entry is ``(display text, was inferred by the tool)``. Quoted items come
    first, then any ai_assumptions for that section that are not already present.

    The ORDER is a contract, not a preference. ``po_context._unified_review_items``
    reproduces this exact sequence to resolve the positional checkbox keys, so
    reordering, re-sorting or changing the de-duplication rule here without
    changing it there silently re-assigns the operator's selections to different
    items in the generated PDF and in the Smartsheet scope text.
    """

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

    Returns ``(contract, site, facility_display_name, facility_address)``.

    The last two are what belong ON the generated document, and they are NOT the
    analyzer's values: when the operator corrects the site to a different RRH
    facility, both are re-read from FACILITIES for the site actually chosen and
    passed to the MSAPO builder.

    Unlike :func:`_routing_snapshot`, an unrecognised mirrored contract is
    rejected here (``is_known_contract``) and the whole confirmation is dropped,
    so a contracts.json edit that removes an account cannot carry a stale name
    onto a freshly generated document.
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
    """Resolve routing defaults without rendering or creating blank widgets.

    Must mirror what :func:`_render_routing_controls` is about to show, because
    its result decides whether the routing block appears in the visible
    questions container or inside the collapsed corrections panel. It is a
    read-only twin: it must not call any ``st.*`` widget, since instantiating a
    widget here would claim the key and leave a duplicate control on the page.

    Placeholder values are explicit unresolved choices. They must not fall back
    to analyzer detections here: doing that would mark routing complete and hide
    the very selector the operator deliberately cleared.
    """
    detected_contract, detected_site = contracts.match_facility(
        analysis.facility_name, quote_text
    )
    contract_options = set(contracts.contract_names())
    raw_confirmed = st.session_state.get(f"routing_{token}")
    confirmed = raw_confirmed if isinstance(raw_confirmed, dict) else {}
    stored_contract = str(st.session_state.get(f"contract_{token}", "") or "")
    confirmed_contract = str(confirmed.get("contract", "") or "")
    if stored_contract == CONTRACT_PLACEHOLDER:
        contract = ""
    elif stored_contract in contract_options:
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
        if stored_site == SITE_PLACEHOLDER:
            site = ""
        elif stored_site in SITE_LABELS:
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
            else ""
        )
        stored_category = str(
            st.session_state.get(f"cat_{token}_{site_key}", "") or ""
        )
        if stored_category == CATEGORY_PLACEHOLDER:
            category_label = ""
        else:
            category_label = (
                stored_category
                if stored_category in category_labels
                else guessed_category
            )
        if not category_label:
            return RoutingSnapshot(contract, True, site, "", "", site_key)
        category_key = valid_categories[category_labels.index(category_label)]
        # Same two-source rule the renderer uses: a mapped site+category yields
        # a fixed code shown as a read-only pill, and ONLY an unmapped pair falls
        # back to whatever the operator typed. Reversing the precedence would let
        # a stale typed value override the configured code for a site that has
        # one -- and the operator would never see it, because when a mapping
        # exists no text field is rendered at all.
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
        if stored_site == SITE_PLACEHOLDER:
            site = ""
        else:
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
    """Return the current site assets, labels, and unique-best suggestion.

    Returns ``(site_assets, {uid: label}, suggested_uid_or_None)``. An empty
    asset list is a legitimate answer -- several configured sites have no
    registry -- and the caller must treat it as "Asset ID stays blank", not as
    an error.

    Called TWICE per rerun on purpose, once by main() to decide placement before
    the widgets exist and once inside :func:`_render_asset_control` to build the
    options. Both calls must agree, which is why the guessing lives here rather
    than in either caller. It is pure with respect to session state -- no widget,
    no write -- so the duplicate call is safe if not free.
    """
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
    # Third stage, only when the first two decline. The scorer refuses to break
    # a tie between units of the same type, which left the operator with nothing
    # in exactly the cases where the scope made the type obvious ("repair the
    # chiller"). Fall back to the lowest-numbered unit of that type.
    #
    # This stage alone searches quote text PLUS the analyzer's project
    # description and scope, because it matches on an equipment head noun and
    # the noun is often only in the model's summary -- OCR of a scanned quote
    # frequently loses it. The two earlier stages match tags and must stay on
    # the raw quote so a hallucinated summary cannot invent an asset tag.
    #
    # Ordering is not cosmetic: lowest-numbered is a guess of last resort, so it
    # may only run when the exact-tag and scorer stages have both declined.
    # Promoting it would present an arbitrary unit as a confident match -- the
    # exact failure ("AS-1 always suggested") the scorer's tie refusal exists to
    # prevent. See docs/COMMIT_NOTES_2026-08-13_ASSET_AND_ROUTING_ACCURACY.md §2.
    type_guess = (
        None
        if (exact_guess in uids or broad_guess)
        else lowest_numbered_of_type(
            site_assets,
            quote_text=" ".join(
                (
                    str(quote_text or ""),
                    str(getattr(analysis, "project_description", "") or ""),
                    str(getattr(analysis, "scope_of_work", "") or ""),
                )
            ),
            hint=analysis.asset_reference,
        )
    )
    guess = exact_guess if exact_guess in uids else (broad_guess or type_guess)
    return site_assets, labels, guess


def _render_tax_alert(status: object) -> None:
    """Render the one prominent non-blocking alert when tax was not included.

    Deliberately NON-BLOCKING and deliberately not a checkbox. The operator can
    generate with the alert on screen; the tool has no way to know whether tax
    applies, so gating on it would train people to tick past it. An earlier
    design did exactly that and the confirmation control was removed --
    tests/test_smartsheet_handoff_entrypoint.py still asserts that no
    tax-confirmation state name comes back.

    Renders nothing when the quote states tax is included, which is why the
    empty-message early return matters: an always-on banner is an ignored banner.
    """
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
    """The synthetic quote behind the byline button -- a fixture, not a demo.

    Its values are chosen so the whole quick path resolves without an API key:
    the facility matches an RRH site in FACILITIES, "CH-1" resolves to a real
    registry asset, and the amounts reconcile (subtotal + tax == total) so
    po_context raises no discrepancy warning. Changing any of those breaks the
    CI test that walks the full path including the LibreOffice render.

    A DIAGNOSTIC TRAP worth knowing before reproducing an operator's report: this
    sample fills vendor representative name and email, so those fields sit inside
    the collapsed corrections panel. A real quote that leaves them undetermined
    shows them in the visible questions container instead. A repro driven from
    this sample is therefore NOT in the same UI state as most bug reports.
    """
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
    """Seed session state so the sample behaves exactly like a real upload.

    Every key here has a consumer that VALIDATES it, which is why this looks
    over-specified:

    * ``analysis_token`` must equal the first 12 hex of the SHA-256 of
      ``quote_text``; po_context recomputes it and warns "the analysis
      fingerprint does not match" otherwise.
    * ``last_sig`` must be the FULL digest of the same text, or main() decides
      the quote changed and fires a real analyzer call -- which needs an API key
      and defeats the point of the sample.
    * ``extract_hash`` must be the digest of ``uploaded_file_bytes`` and
      ``extracted_text`` must equal ``quote_text``, or
      ``po_context._active_quote_attachment`` rejects the upload and silently
      substitutes a synthesised text file as the first attachment.

    The pops are the other half: a stale PDF or a stale error from a previous
    quote would otherwise survive into the sample's run and make it look either
    already-generated or already-failed.
    """
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
    """Retire the sample the moment the operator touches a real quote source.

    Wired as ``on_change`` on the source radio, the uploader and the paste box.
    It has to be a callback rather than inline code: the callback runs before the
    rerun renders, so ``choose_quote_text`` sees the flag already cleared. Doing
    it inline would leave the sample winning for one full render, and the
    operator would watch their own upload be ignored.
    """
    st.session_state["synthetic_quote_active"] = False


def _retry_extraction() -> None:
    """Clear the sticky per-file extraction failure so the read is attempted again.

    The failure is keyed by file hash, and that stickiness is the point: without
    it the same unreadable file is re-OCR'd on every rerun of the page. Popping
    the pair is therefore the ONLY way back, which is why it is a named callback
    rather than a condition folded into the render.
    """
    st.session_state.pop("extraction_error_hash", None)
    st.session_state.pop("extraction_error_message", None)


def _retry_analysis() -> None:
    """Clear the sticky per-quote analysis failure so the model is called again.

    Same shape as :func:`_retry_extraction`, keyed by quote signature instead of
    file hash: without the marker a failing quote would re-bill an API call on
    every rerun.
    """
    st.session_state.pop("analysis_error_signature", None)
    st.session_state.pop("analysis_error_message", None)


def _render_analysis_retry(signature: str) -> None:
    """Show the fail-closed analysis error plus its retry control.

    Fail-closed matters here: the caller has already dropped the previous
    analysis, so the page shows an error and STOPS rather than continuing with a
    stale quote's extracted values under a new quote's text.

    The button key is scoped by signature so a different failing quote gets a
    different widget; reusing one key would carry the previous quote's press
    state onto the new failure.
    """
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
    """Render sanitized contract/site/cost-code overrides in page order.

    Returns ``(contract, rrh, site, category_label, cost_code, rrh_site_key)``,
    with empty strings for anything the operator has not resolved. Callers must
    treat an empty contract or site as "blocked", never as "use the default" --
    the pre-generation gate in main() depends on that.

    Guarantees and assumptions:

    * Each selectbox's session key is REPAIRED before the widget is created --
      ``if state.get(key) not in options: state[key] = <default>``. Streamlit
      raises if a key holds a value absent from the option list, and the option
      lists here change as contracts.json changes and as the operator switches
      contract, so the repair is what stops a stale value from crashing a rerun.
      It must stay BEFORE the widget call: a write afterwards is discarded.
    * ``routing_<token>`` is a plain (non-widget) mirror of the confirmed
      contract/site. Streamlit deletes widget keys for widgets that did not
      render, so after a rerun where these controls were hidden the widget keys
      are gone and only this mirror survives. It is popped, not left stale,
      whenever the selection becomes incomplete -- otherwise generation would
      later resurrect a contract the operator had already backed out of.
    * The early returns are intentional: a contract with no site chosen yields
      no category and no cost code, and inventing either would produce a
      confident wrong Smartsheet cost code.

    The RRH branch and the generic branch are NOT interchangeable. RRH sites map
    through FACILITIES to a fixed cost code and a restricted category list; every
    other account is free text or a contracts.json site list with a typed cost
    code. Collapsing them would either invent RRH cost codes or discard them.
    """
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
            else CATEGORY_PLACEHOLDER
        )
        category_options = [CATEGORY_PLACEHOLDER] + category_labels
        category_state_key = f"cat_{token}_{site_key}"
        if st.session_state.get(category_state_key) not in category_options:
            st.session_state[category_state_key] = default_category
        category_label = st.selectbox(
            "Work category *",
            category_options,
            key=category_state_key,
        )
        if category_label == CATEGORY_PLACEHOLDER:
            st.session_state[f"routing_{token}"] = {
                "contract": contract,
                "site": site,
            }
            return contract, rrh, site, "", "", site_key
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
    """Show one AI-suggested asset dropdown and export the full registry UID.

    Returns the RAW selection -- a registry UID, ``ASSET_NONE``, or
    ``ASSET_PLACEHOLDER``. It is not normalised here on purpose: main() has to
    distinguish "the operator confirmed no asset applies" from "the operator has
    not answered", and ``normalize_asset_id`` maps both to the empty string.
    Normalising early would let an unanswered asset question pass the gate.

    The placeholder is added to the options ONLY when there is a genuine
    question -- no confident guess and nothing already stored. Offering it
    unconditionally would make "unanswered" a permanently selectable state on
    quotes the tool identified correctly, and blocking on it would then nag on
    every one of them.

    The full UID is exported deliberately, not a shortened code. An earlier
    review proposed a five-digit JDE code; the account team has no verified
    mapping for it and the product owner directed that configured asset codes
    ship whole (see ``po_rules.normalize_asset_id``).
    """
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
    """Render the page footer.

    Called from every exit path in main(), including the early ones, so the page
    never ends abruptly mid-render on a blocked or empty quote.
    """
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
    """Render the whole page: workflow selector, then the three purchase steps.

    Called by ``run_web.py``. Returns None; everything it produces lands in
    ``st.session_state`` for ``app.po_context`` to reassemble.

    Two ordering rules govern almost every oddity below.

    1. PLACEMENT IS COMPUTED BEFORE THE WIDGETS RENDER. Each field goes to the
       visible questions container or to the collapsed corrections panel, and
       that decision needs values the widgets have not produced yet -- so the
       block between the analysis check and step 2 reads session state and
       repairs defaults, and only then does the rendering start. Writing a
       widget key after its widget has rendered is silently discarded by
       Streamlit, so this order is not a preference.
    2. NO EARLY RETURN AFTER THE ANALYSIS EXISTS. Streamlit deletes the keys of
       widgets that did not render, so returning early from the reviewed path
       would erase the operator's own corrections. Invalidation therefore
       suppresses generation and the handoff, never the fields.
       ``tests/test_web_ui_helpers.py`` pins rule 2 by scanning this function's
       source for a return statement after that point.

    ``st.form`` is the obvious refactor and it is WRONG here. The gate below
    reads every field on every rerun to build ``draft_problems``; inside a form
    those values do not update until submit, so the gate would compute from
    stale values and could accept an incomplete purchase order. The full
    reasoning, including what would have to change first, is §5 of
    docs/COMMIT_NOTES_2026-08-12_TOUCH_AND_RENDERER_RELIABILITY.md.
    """
    st.set_page_config(
        page_title="Process Control",
        page_icon=str(
            Path(__file__).resolve().parents[1]
            / "branding"
            / "process-control-icon.png"
        ),
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    # Split deliberately. Previously one try/except wrapped BOTH the cookie read
    # and the bootstrap, which caused two problems: a read failure skipped
    # bootstrap entirely (so the cookie could never be created), and a bootstrap
    # failure was indistinguishable from "no cookie yet" -- which is how an
    # invalid height=0 silently disabled every device-scoped memory feature on
    # both workflows for the life of the deployment.
    try:
        browser_token = device_token(st.context.cookies)
    except Exception:
        browser_token = ""
    if not browser_token:
        try:
            ensure_device_cookie()
        except Exception as exc:  # noqa: BLE001 - convenience feature, never fatal
            # Still non-blocking: memory is a convenience and must not take the
            # page down. But it is now visible in the server log rather than
            # vanishing, so a regression cannot hide again.
            print(f"device cookie bootstrap failed: {exc.__class__.__name__}: {exc}")
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    preserve_expense_draft_state()

    # required=True is load-bearing, not cosmetic. A single-select
    # segmented_control defaults to required=False, which lets the operator
    # DESELECT the active segment — easy to do by accident on a phone, where the
    # segment is a 56px tap target. Deselecting returns None, which is neither
    # workflow, so the expense report silently vanished and the Purchase Order
    # page rendered with no segment highlighted. Forcing a selection makes the
    # control unable to represent "no workflow" at all.
    workflow_mode = st.segmented_control(
        "Choose workflow",
        (PURCHASE_WORKFLOW, EXPENSE_WORKFLOW),
        default=PURCHASE_WORKFLOW,
        key="workflow_mode",
        label_visibility="collapsed",
        width="stretch",
        required=True,
    )
    # Defence in depth: required=True prevents deselection, but a stale or
    # hand-set session value could still be None/unknown. Never let an
    # unrecognized mode fall through to the PO branch by accident.
    if workflow_mode not in (PURCHASE_WORKFLOW, EXPENSE_WORKFLOW):
        workflow_mode = PURCHASE_WORKFLOW
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

    # The byline doubles as the synthetic-sample trigger. It is intentionally
    # unlabelled and NOT gated behind an environment flag: it is the only way to
    # exercise the full path -- render included -- on a deployment with no API
    # key, and a flag would make it absent exactly where it is needed. A test
    # pins its availability, so hiding it later is a deliberate act.
    _, center, _ = st.columns([2, 3, 2])
    with center:
        if st.button(
            "Built by Evan Roden",
            key="load_synthetic_test",
            width="stretch",
            help="Load the built-in synthetic quote for a safe workflow test.",
        ):
            _load_test_into_state()
            # Bumping the nonce changes the uploader's widget key, which is the
            # only way to make Streamlit forget a file the operator already
            # dropped in. Without it the previous upload is still mounted, and
            # on the next rerun its extraction overwrites the sample's seeded
            # quote -- the sample would appear to load and then vanish.
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
            # Derived from the Smartsheet attachment ceiling, not chosen. The
            # quote the operator uploads IS one of the two attachments, so a file
            # the uploader accepts but Smartsheet later refuses is a failure the
            # operator only discovers after generating everything. Integer
            # division rounds DOWN, which errs on the safe side; keep it that way.
            max_upload_size=MAX_ATTACHMENT_BYTES // (1024 * 1024),
            label_visibility="collapsed",
            key=f"uploader_{st.session_state.get('uploader_nonce', 0)}",
            on_change=_deactivate_synthetic_quote,
        )
        if uploaded is not None:
            file_bytes = uploaded.getvalue()
            st.session_state["uploaded_file_bytes"] = file_bytes
            st.session_state["uploaded_file_name"] = uploaded.name
            # Every decision below keys off the file's CONTENT hash, never its
            # name. Two consequences worth keeping: re-uploading the same file
            # does not re-run OCR (it can take tens of seconds on a scan), and a
            # failure is remembered per file, so a broken PDF cannot put the page
            # into an OCR loop that re-fails on every rerun. The retry button is
            # the only way to clear that memory -- which is why it exists.
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
                        # A successful read of an image-only PDF returns an
                        # empty string rather than raising. Left alone that is a
                        # SILENT failure of the worst kind: the analyzer would be
                        # handed nothing and the operator would be shown a
                        # confidently blank form. Promote it to the same visible
                        # error path as a genuine exception.
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

    # Exactly one source wins, decided outside the UI. Both widgets keep their
    # session values while hidden, so choosing here by hand would let a stale
    # pasted quote outrank the file the operator is currently looking at.
    quote_text, quote_source = choose_quote_text(
        input_mode,
        uploaded_text=uploaded_text,
        pasted_text=pasted_text,
        synthetic_active=bool(st.session_state.get("synthetic_quote_active")),
        synthetic_text=st.session_state.get("quote_text", ""),
    )

    # Both guards below CLEAR the analysis before returning. That is the point:
    # without it the page would keep rendering the previous quote's vendor,
    # totals and scope under a new quote's input, and generate a package
    # describing a document nobody is looking at.
    length_problem = quote_length_problem(quote_text)
    if length_problem:
        clear_active_analysis(st.session_state)
        st.error(length_problem)
        _render_footer()
        return

    if not quote_text:
        if st.session_state.get("analysis") is not None:
            clear_active_analysis(st.session_state)
        st.caption("Upload or paste a quote above. It will be analyzed automatically.")
        _render_footer()
        return

    # The quote text itself is the cache key for the (paid, slow) analyzer call.
    # "ignore" on the encode is required, not tidy: OCR of a scanned quote
    # regularly yields lone surrogates, and a UnicodeEncodeError here would take
    # the whole page down on a file the operator cannot tell apart from any
    # other. po_context re-derives the same digest with the same error handler to
    # confirm the stored analysis belongs to the stored text -- both sides must
    # use "ignore" or every quote containing one bad byte reports a fingerprint
    # mismatch it cannot resolve.
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
                # 12 hex characters, and po_context recomputes exactly this
                # slice to verify the analysis matches the stored quote. Widen
                # or narrow it here and every generated package reports a
                # fingerprint mismatch warning; the tool would still generate,
                # just always with a warning nobody can clear.
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

    # Everything from here to the step-2 header is the pre-render seeding pass.
    # Two idioms recur and mean different things:
    #
    #   ``if key not in state``            -- seed ONCE from the analysis. Used
    #                                         for free text, so a later rerun can
    #                                         never overwrite the operator's own
    #                                         correction with the model's value,
    #                                         not even when they blank the field.
    #   ``if state.get(key) not in <opts>`` -- REPAIR whenever the stored value
    #                                         is not selectable. Used for every
    #                                         selectbox, because Streamlit raises
    #                                         if a key holds a value missing from
    #                                         the options and the option lists
    #                                         change with the chosen contract.
    #
    # Every key is scoped by ``token`` (and by contract or site where the option
    # list depends on one) so switching quotes cannot carry a value across.
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
    model_route = str(getattr(analysis, "purchase_route_guess", "") or "").strip()
    # The deterministic second opinion. It reads the raw quote joined with the
    # analyzer's own summary, because a scanned quote's OCR often loses the
    # sentence that names the work while the summary keeps it. The rules
    # themselves discard the vendor's terms and conditions before matching --
    # on one real quote that boilerplate was 92% of the document and outvoted
    # the actual scope. See po_rules.scope_region.
    inferred_route = infer_purchase_route(
        " ".join(
            (
                cached_quote,
                str(getattr(analysis, "project_description", "") or ""),
                str(getattr(analysis, "scope_of_work", "") or ""),
            )
        )
    )
    route_guess = model_route if model_route in PURCHASE_ROUTES else inferred_route
    # Object Account and Agreement Type are derived entirely from this one
    # answer, and a wrong answer is invisible downstream -- it just appears in
    # Smartsheet as a confident 5511-SUBCONTRACTOR. Two independent signals are
    # available, so treat their DISAGREEMENT as the confidence measure: when the
    # analyzer and the deterministic text rules reach different conclusions, or
    # the analyzer offered nothing at all, put the control in front of the
    # operator instead of leaving it inside the collapsed corrections panel.
    route_uncertain = (
        model_route not in PURCHASE_ROUTES or model_route != inferred_route
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

    # Vendor-representative recall, and the bookkeeping that keeps it honest.
    #
    # Memory is scoped to (account, vendor). Both can change mid-session -- the
    # operator corrects the vendor spelling, or picks a different contract -- so
    # the pair is fingerprinted into ``contact_seed_context`` and the seeding
    # re-runs whenever that fingerprint moves. NUL joins the two halves because
    # it cannot occur in either value; a hyphen would let "A-B" + "C" collide
    # with "A" + "B-C".
    #
    # The two ``seeded_*`` keys record what THIS page filled in, and they are the
    # only defence against a specific silent corruption: without them, a value
    # recalled for the previous vendor is indistinguishable from a value the
    # operator typed, so switching vendors would keep the old representative and
    # attach the wrong person's email to the purchase order. A field is reverted
    # only when it still holds exactly what was seeded -- an edited field is left
    # alone, always.
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

    # 20 characters is the Smartsheet Description of Work column's hard cap, not
    # a style choice. It is enforced three times over -- when seeding, when
    # reading, and by max_chars on the widget -- because a value that exceeds it
    # is not rejected at submission: it is TRUNCATED by the form, so the operator
    # would see a description they never wrote. The full reviewed scope lives in
    # the generated PDF; this field is only ever the short label.
    description_key = f"desc_{token}"
    if description_key not in st.session_state:
        st.session_state[description_key] = (
            analysis.short_description or ""
        )[:20]
    # Defensive, and normally unreachable through the UI because the widget caps
    # input. It catches a value seeded before the cap existed, or restored from
    # an older session, rather than letting it reach the form over-length.
    elif len(str(st.session_state.get(description_key, "") or "")) > 20:
        st.session_state[description_key] = str(
            st.session_state.get(description_key, "") or ""
        )[:20]
    description_value = str(
        st.session_state.get(description_key, "") or ""
    ).strip()[:20]

    scope_key = f"scope_{token}"
    if scope_key not in st.session_state:
        st.session_state[scope_key] = str(analysis.scope_of_work or "").strip()
    scope_value = str(st.session_state.get(scope_key, "") or "").strip()

    instructions_key = f"instructions_{token}"
    instructions_value = str(
        st.session_state.get(instructions_key, "") or ""
    ).strip()

    # Job number, seeded here only so ``needs.job_number`` can be computed before
    # anything renders. The selectbox itself is built again further down against
    # the POST-render contract; both must agree on the key format, which
    # po_context also reads by exact string.
    #
    # The default differs by account and the asymmetry is deliberate: RRH has one
    # obviously correct O&M job, so it is preselected, while every other account
    # gets the placeholder and must be answered. Preselecting the first catalog
    # entry for a non-RRH account would send a confident wrong job number to
    # Smartsheet with nothing on screen suggesting a choice was ever made.
    #
    # The conditional below binds as ``(a or b) if rrh else (c or d)`` -- Python
    # gives ``or`` higher precedence than the conditional expression. That is the
    # intent; do not "clarify" it by moving the parentheses.
    job_key = ""
    job_value = ""
    if routing_snapshot.contract:
        job_key = f"job_number_{token}_{routing_snapshot.contract}"
        job_options = job_numbers_for_contract(routing_snapshot.contract)
        # Suggests ONLY on an exact job identifier quoted in the text, or when
        # the account has a single option. It deliberately returns nothing on a
        # tie -- an invented job number is worse than an unanswered one.
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
    # "Resolved" includes a site with NO registry at all. Several configured
    # sites have none, and treating that as an open question would put an
    # unanswerable prompt in front of the operator forever. It is the inverse of
    # ``needs_choice`` in _render_asset_control -- keep the two in step or the
    # asset dropdown appears in one container while the page blocks on the other.
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
    # Retain the previous placement for ONE rerun so the field an operator just
    # answered does not jump away at commit time. Store only the live result:
    # otherwise the OR can never clear and the warning/highlight remains forever
    # after every required value has been supplied.
    review_needs_key = f"review_needs_{token}"
    needs: ReviewNeeds = retain_review_needs(
        st.session_state.get(review_needs_key),
        current_needs,
    )
    st.session_state[review_needs_key] = current_needs

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

    # The checkbox keys are POSITIONAL -- inc_<token>_<index> -- and
    # ``po_context._reviewed_lists`` rebuilds the same lists to map each index
    # back to an item. Enumeration order is therefore part of the data contract,
    # not a rendering detail. Sorting these lists, filtering them, or skipping an
    # empty entry would shift every following index and silently attribute the
    # operator's ticks to different inclusions on the generated document.
    #
    # The lists are also built OUTSIDE the expander body while the checkboxes are
    # built inside it: expander contents execute whether or not the panel is
    # open, so final_inclusions/final_exclusions are complete either way. Moving
    # this behind an "if expanded" guard would make an unopened panel generate a
    # PDF with no inclusions at all.
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
        # Reassigns scope_value from the widget, and everything downstream --
        # the PDF signature and the rendered document -- uses the reassigned
        # value. This is the ONLY path by which an operator's scope edit reaches
        # the attachment: the PDF builder is handed this string explicitly
        # because the document template would otherwise read the untouched
        # analysis text and discard every correction, on the exact page contract
        # administration signs.
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

    if current_needs.any:
        st.markdown(
            '<div class="needs-banner"><strong>Needed from you</strong><br>'
            'The tool could not safely determine one or more values below. '
            'Every question shown below is required before generation.</div>',
            unsafe_allow_html=True,
        )

    # Only unresolved fields render inside this container -- each field goes
    # to `questions if needs.X else corrections` -- so highlighting the
    # container highlights exactly the fields that still need a value, and a
    # field stops being highlighted the moment it moves to corrections. The
    # key is what Streamlit turns into the st-key- class the rule targets.
    #
    # Both handles are created here and entered repeatedly below with
    # ``with questions if needs.X else corrections``. Streamlit containers are
    # re-enterable, which is what allows placement to be decided per field while
    # the page still reads top to bottom. Creating a fresh container per field
    # instead would break the single st-key- hook the highlight depends on.
    questions = st.container(key="po_needs_you")
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

    # Rebuilt against the POST-render contract, which can differ from the
    # snapshot's for one rerun after the operator switches accounts. The key
    # embeds the contract name, so each account keeps its own answer and
    # switching back restores it rather than resetting to a suggestion.
    #
    # RRH is the only account whose option list omits the placeholder: it has a
    # single correct O&M job and forcing a redundant confirmation on the busiest
    # account is pure friction. Every other account keeps the placeholder so an
    # unanswered job number stays unanswered instead of defaulting to whichever
    # catalog entry happens to sort first.
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

    with questions if route_uncertain else corrections:
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
        if route_uncertain:
            st.caption(
                "This one drives Object Account and Agreement Type, and the "
                "quote did not read clearly either way. Confirm it before "
                "generating."
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

    # The optional note has two mutually exclusive homes: here once it holds
    # text, and behind the toggle further down while it is empty. Only one
    # renders per run, so the widget key survives either way and po_context still
    # finds it.
    #
    # The requester is the person filling the form in, and it deliberately never
    # comes from a deployment default -- po_context keeps its ``env`` parameter
    # only for old callers and ignores it for exactly this reason. Memory is
    # scoped to (this browser, this account) and is written only after a package
    # passes validation, so an abandoned draft never teaches a name.
    #
    # ``browser_token`` may legitimately be "" when the cookie has not been
    # established yet; the memory layer treats an empty token as "no device" and
    # returns nothing, so every cookie-less browser is isolated rather than
    # sharing one bucket.
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

    # Emitted AFTER the fields render, because the requester's value is not
    # known until then and CSS applies regardless of emission order.
    #
    # The container holds exactly the values still in question -- every other
    # field goes to `corrections` once resolved -- plus the requester, which is
    # always required and has no resolved/unresolved split of its own. So:
    # highlight the whole group while the tool is still asking for something,
    # otherwise highlight just the requester while it is blank. Never both, so a
    # field never carries two nested bars.
    # Uses the container's STATIC key rather than the requester's, whose key
    # embeds the contract name and so depends on class-name normalisation.
    # When nothing is in question the container holds only the requester --
    # every other field has moved to `corrections` -- so highlighting the
    # container is precise in both cases.
    if current_needs.any or (requester_key and not requester_value):
        highlight_needed_fields(["po_needs_you"])

    # The empty-note half of the pair above. Behind a toggle rather than always
    # visible because the Smartsheet reviewer reads every note that arrives, so
    # an always-present box invites filler; short-circuiting on
    # ``instructions_value`` is what guarantees only one of the two text areas
    # claims the key on any given run.
    # The toggle renders UNCONDITIONALLY, and the box renders whenever the
    # toggle is on OR a note already exists. Both halves matter.
    #
    # This used to read `if not instructions_value and st.toggle(...)`, so the
    # run after the operator typed a note the whole condition short-circuited:
    # the box AND the toggle vanished from the page, and a second copy of the
    # field appeared inside the collapsed corrections panel. The text was
    # retained and still sent, but from the operator's seat an optional note
    # they had just typed simply disappeared.
    #
    # It also did not belong in that panel. It is labelled "Change a value the
    # tool already filled", and this note is operator-authored -- the tool never
    # filled it. There is now exactly ONE text area for this key, in the flow
    # where it was typed, which is also what keeps two widgets from claiming the
    # same session key on one run.
    #
    # Toggling off does NOT hide existing text. Silently concealing content the
    # operator wrote is the failure this whole change is about; they clear the
    # box to remove the note.
    reveal_note = st.toggle(
        "Add Additional Information",
        key=f"show_optional_{token}",
        help="Use this only when the Smartsheet reviewer needs an extra note.",
    )
    if reveal_note or instructions_value:
        st.text_area(
            "Additional information (optional)",
            key=instructions_key,
            placeholder="Only enter something the Smartsheet reviewer needs",
            help="Only add a note the Smartsheet reviewer needs to see.",
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

    # Object Account and Agreement Type are OPERATOR-EDITABLE, defaulting to the
    # route-derived pair. Which coding a job takes depends on the contract
    # vehicle -- MSA versus CSA -- and on whether the vendor is coming onsite,
    # none of which a text rule can see. Deriving them alone left two values the
    # form accepts unreachable (5490-OTHER and "03 - CSAPO (CONSTRUCTION)"), so
    # ISDC-funded work could not be coded at all.
    #
    # They live in `corrections` because that panel is exactly "Change a value
    # the tool already filled" -- which is what these are. The route selector
    # above still drives the default, so the common case needs no interaction.
    #
    # Track-the-default, the same protocol as the expense job coding: a shadow
    # `_prior_default_` key records what was last offered, so a field still
    # holding the previous default follows a new one when the route changes,
    # while a field the operator set stays put. Plain setdefault would freeze
    # the first route's coding in place and silently contradict the route shown
    # beside it.
    for _field_key, _options, _derived in (
        (
            f"object_account_{token}",
            OBJECT_ACCOUNT_OPTIONS,
            classification.object_account if classification else "",
        ),
        (
            f"agreement_type_{token}",
            AGREEMENT_TYPE_OPTIONS,
            classification.agreement_type if classification else "",
        ),
    ):
        _prior_key = f"{_field_key}_prior_default"
        _prior = st.session_state.get(_prior_key)
        if _field_key not in st.session_state or (
            st.session_state.get(_field_key) == _prior
        ):
            st.session_state[_field_key] = _derived
        st.session_state[_prior_key] = _derived
        # A stored value outside the catalog would raise in the selectbox rather
        # than degrade, so it is corrected before render. po_context re-validates
        # independently, because Streamlit keeps state for widgets that did not
        # render this run.
        if st.session_state.get(_field_key) not in _options:
            st.session_state[_field_key] = _derived if _derived in _options else "NA"

    with corrections:
        st.selectbox(
            "Object Account",
            OBJECT_ACCOUNT_OPTIONS,
            key=f"object_account_{token}",
            help=(
                "Defaults from how the work is handled. Change it when the "
                "funding or contract vehicle needs a different account, such as "
                "5490-OTHER for ISDC-funded work."
            ),
        )
        st.selectbox(
            "Agreement Type for PO",
            AGREEMENT_TYPE_OPTIONS,
            key=f"agreement_type_{token}",
            help=(
                "Defaults from how the work is handled. Change it when the "
                "contract vehicle differs -- for example CSAPO (CONSTRUCTION) "
                "under a CSA rather than an MSA."
            ),
        )

    object_account_value = str(st.session_state.get(f"object_account_{token}", "") or "")
    agreement_type_value = str(st.session_state.get(f"agreement_type_{token}", "") or "")

    asset_id = normalize_asset_id(selected_asset)
    summary_route = PURCHASE_ROUTE_LABELS.get(purchase_route, "Route not found")
    summary_primary = (
        f"{REQUEST_TYPE_LABELS.get(request_type, request_type)} · "
        f"{contract or 'Account needed'} · {site or 'Site needed'} · "
        f"{category_label or 'Category needed'} / {cost_code or 'Cost code needed'}"
    )
    summary_detail = (
        f"{summary_route} · "
        f"{object_account_value or 'Account pending'} · "
        f"{agreement_type_value or 'Agreement pending'} · "
        f"Asset: {asset_id or 'None'} · Total: {total_value or 'Needed'}"
    )
    st.markdown(
        f'<div class="request-summary"><strong>{_h(summary_primary)}</strong>'
        f'<span class="request-summary-detail">{_h(summary_detail)}</span></div>',
        unsafe_allow_html=True,
    )

    # THE SUBMISSION GATE. Rebuilt from live values on every rerun and consumed
    # twice: it disables the generate button, and it is the list telling the
    # operator what is still missing. Both consumers depend on these values being
    # current, which is the concrete reason st.form cannot be dropped in around
    # these fields -- inside a form they would not update until submit, so the
    # gate could refuse a complete request or accept an incomplete one and push
    # a partial purchase order into the Smartsheet handoff.
    #
    # Note the deliberate asymmetry in where values are read from: fields whose
    # widget always renders are read through their local variable, while fields
    # that may be absent this run (job number, original PO number) are read from
    # session state, because a hidden widget's local variable does not exist.
    #
    # These checks intentionally overlap ``po_context``'s own warnings. This one
    # stops the operator early with plain instructions; that one is the last line
    # of defence over the whole reassembled context, including the attachments
    # this list knows nothing about. Deleting either does not make the other
    # cover it.
    draft_problems: list[str] = []
    if not contract:
        draft_problems.append("choose the contract")
    if not site:
        draft_problems.append("choose the site")
    if not category_label:
        draft_problems.append("choose the work category")
    elif not cost_code:
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
    if not scope_value:
        draft_problems.append("confirm the scope of work")
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
    # Guarded so the two amount complaints cannot both appear: classify_po
    # rejects a missing amount with its own wording, which would otherwise
    # duplicate the line directly above in different words and read as two
    # separate problems with one field.
    if classification_error and parsed_total is not None and parsed_total > 0:
        draft_problems.append(classification_error)

    if draft_problems:
        concise_problems = [
            problem.rstrip(". ") for problem in dict.fromkeys(draft_problems)
        ]
        st.warning(
            "Before generating: " + "; ".join(concise_problems) + "."
        )

    # Routing is resolved a second time, from the mirror rather than from the
    # widgets, because by the time the package is generated the widget keys may
    # already be gone -- Streamlit drops the key of any widget that did not
    # render on the rerun that produced this state.
    #
    selected_contract, selected_site, facility_name, facility_address = _routing_for_generation(
        analysis, cached_quote, token
    )
    # Fingerprint of everything that changes the DOCUMENT's content. po_context
    # recomputes the identical signature and refuses to attach a PDF whose
    # signature does not match, so the two calls must stay argument-for-argument
    # identical. Adding a field to one only -- say the facility address -- makes
    # every package report a stale-document warning that no amount of
    # regenerating can clear.
    current_pdf_signature = _document_signature(
        token,
        selected_contract,
        selected_site,
        final_inclusions,
        final_exclusions,
        vendor=str(st.session_state.get(vendor_key, "") or "").strip(),
        scope=scope_value,
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
        "One button creates the MSAPO form PDF, keeps the "
        "unchanged quote, and prepares the prefilled Smartsheet link."
    )
    # ONE action produces everything: the PDF, the retained quote, and the
    # prefilled link. There is no separate submit, no email route, and no
    # switch to another page -- several tests assert on this file's raw text to
    # keep those from creeping back, because each previously existed and each
    # gave the operator a way to reach Smartsheet with only half a package.
    generated_key = f"generated_context_{token}"
    if st.button(
        "Generate both files and Smartsheet link",
        type="primary",
        width="stretch",
        key=f"generate_package_{token}",
        disabled=bool(draft_problems),
    ):
        try:
            # Contract administration requires the full MSAPO agreement form,
            # not the simplified Scope/Inclusions/Exclusions sheet. Only the
            # bytes' ORIGIN changes here: the session key, attachment plumbing,
            # and signature checks below are deliberately untouched.
            #
            # The spinner is not decoration. The former scope sheet was built
            # in-memory with PyMuPDF and returned instantly, so no progress
            # indicator was needed. Rendering the MSAPO form shells out to
            # LibreOffice, which takes seconds -- longer on a cold start on a
            # small container -- and with no feedback the button reads as dead
            # and invites repeat taps.
            with st.spinner("Building the MSAPO form PDF…"):
                scope_pdf = build_msapo_pdf(
                    analysis=analysis,
                    scope=scope_value,
                    inclusions=final_inclusions,
                    exclusions=final_exclusions,
                    facility_display=facility_name or selected_site,
                    facility_address_display=facility_address,
                    vendor_display=str(
                        st.session_state.get(vendor_key, "") or ""
                    ).strip(),
                )
        except Exception as exc:
            st.error(
                f"The MSAPO form PDF could not be generated: {exc} "
                "Nothing was submitted. Use the button again, and if it keeps "
                "failing report this message."
            )
        else:
            st.session_state["scope_pdf_bytes"] = scope_pdf
            st.session_state["scope_pdf_signature"] = current_pdf_signature
            context = build_po_context(st.session_state)
            if context is not None:
                st.session_state[generated_key] = context.context_id
                # THREE independent checks, not one with redundancy. ``ready``
                # covers the reassembled context's own warnings,
                # validate_submission_fields covers the Smartsheet field rules,
                # and preflight_attachments covers size and type limits the
                # other two never see. Memory is only taught from a package that
                # would genuinely have been accepted -- otherwise a rejected
                # draft would train the requester and vendor-representative
                # suggestions offered to the next person on this browser.
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

    # Rebuilt unconditionally, outside the click branch, and compared by context
    # ID. This is the staleness gate for the handoff: the ID is a hash of every
    # field plus the hash of every attachment, so ANY change after generation --
    # a corrected total, a different asset, a re-uploaded quote -- produces a
    # different ID and the handoff is replaced by the "use the button again"
    # warning rather than offering a link that no longer matches the files.
    #
    # Yes, this repeats the build performed inside the click branch on the run
    # where the button was pressed. Collapsing them is not safe: the click branch
    # only exists on that one run, and every other rerun needs a freshly built
    # context to compare against.
    context = build_po_context(st.session_state)
    generated_context = st.session_state.get(generated_key, "")
    if context is not None and generated_context == context.context_id:
        render_inline_smartsheet_handoff(context)
    elif generated_context:
        st.warning(
            "A detail changed. Use the button again to refresh both files and the link."
        )

    _render_footer()


if __name__ == "__main__":
    main()
