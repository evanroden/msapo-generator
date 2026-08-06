"""
Streamlit web interface for Email Process Control.

Drop in a vendor quote and the app extracts the details, builds the MSAPO
document (or skips it for equipment-only POs), and hands you a ready-to-send
administrator email — pre-filled for Outlook on desktop and Apple Mail on an
iPhone/iPad, detected automatically.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import base64
import hashlib
import html
import json
import mimetypes
import re
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path

from app.ocr import extract_text
from app.quote_analyzer import analyze_quote, QuoteAnalysis, AIAssumption
from app.document_generator import generate_docx
from app.pdf_converter import convert_to_pdf, PDFConversionError
from app.eml_builder import build_eml, build_plain_body, build_mailto_url, DAVID_EMAIL
from app.assets import (
    assets_for_facility,
    asset_uids_for_facility,
    asset_by_uid,
    asset_label,
    guess_asset_id,
)
from app import contracts
from app import memory
from app.config import (
    FACILITIES,
    FACILITY_SHORT_NAMES,
    WORK_CATEGORY_DISPLAY,
    facility_key_from_name,
    lookup_cost_code,
    valid_categories_for_site,
)

SITE_LABEL_TO_KEY = {label: key for key, label in FACILITY_SHORT_NAMES.items()}
SITE_LABELS = list(FACILITY_SHORT_NAMES.values())
CONTRACT_PLACEHOLDER = "— Select a contract —"
SITE_PLACEHOLDER = "— Select a site —"

# ── Design System ────────────────────────────────────────────────────
# Navy #12314F · Orange #F0803C · Grape #6D5AE6 · Mint #16A34A
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


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════
def _h(value) -> str:
    """HTML-escape a model/user-derived value before it goes into an
    unsafe_allow_html markdown block (the quote is authored by the vendor)."""
    return html.escape(str(value)) if value is not None else ""


def _strip_ai_wrapper(text: str) -> str:
    m = re.search(r"\[AI ESTIMATE:\s*(.+?)\]", text)
    return m.group(1) if m else text


def _build_unified_lists(analysis: QuoteAnalysis):
    """Return (inclusions, exclusions) as lists of (clean_text, is_ai)."""
    def _process(raw_items: list[str], section_key: str) -> list[tuple[str, bool]]:
        seen: set[str] = set()
        result: list[tuple[str, bool]] = []
        for item in raw_items:
            is_ai = "[AI ESTIMATE:" in item
            clean = _strip_ai_wrapper(item)
            if clean not in seen:
                seen.add(clean)
                result.append((clean, is_ai))
        for assumption in analysis.ai_assumptions:
            if assumption.section == section_key and assumption.text not in seen:
                seen.add(assumption.text)
                result.append((assumption.text, True))
        return result

    return _process(analysis.inclusions, "inclusion"), _process(analysis.exclusions, "exclusion")


def _has_breakdown(subtotal: str, tax: str) -> bool:
    """Show subtotal + tax bullets only when the quote itemized both."""
    return bool(subtotal and subtotal.strip()) and bool(tax and tax.strip())


def _parse_amount(value: str | None) -> Decimal | None:
    """Parse a displayed US-dollar amount without changing the user's text."""
    if not value or not value.strip():
        return None
    cleaned = re.sub(r"[^0-9.-]", "", value)
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _pricing_difference(subtotal: str, tax: str, total: str) -> Decimal | None:
    """Return subtotal + tax - total when all three values are parseable."""
    sub = _parse_amount(subtotal)
    sales_tax = _parse_amount(tax)
    grand_total = _parse_amount(total)
    if sub is None or sales_tax is None or grand_total is None:
        return None
    return sub + sales_tax - grand_total


def _document_signature(
    token: str,
    contract: str,
    site_label: str,
    inclusions: list[str],
    exclusions: list[str],
) -> str:
    """Fingerprint every selection that changes the generated MSAPO."""
    payload = {
        "analysis": token,
        "contract": contract,
        "site": site_label,
        "inclusions": inclusions,
        "exclusions": exclusions,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _routing_for_generation(
    analysis: QuoteAnalysis,
    quote_text: str,
    token: str,
) -> tuple[str, str, str | None, str | None]:
    """Use the user's saved routing choices when rebuilding a document.

    Contract/site widgets appear after the build step. Streamlit preserves their
    values in session state, so a required regeneration can still use the final
    corrected routing instead of repeating the original AI guess.
    """
    detected_contract, detected_site = contracts.match_facility(
        analysis.facility_name, quote_text
    )
    contract = st.session_state.get(f"contract_{token}") or detected_contract or ""
    if contract == CONTRACT_PLACEHOLDER:
        contract = detected_contract or ""

    if contracts.is_rrh(contract):
        facility_key = facility_key_from_name(analysis.facility_name)
        default_site = FACILITY_SHORT_NAMES.get(facility_key) if facility_key else ""
        site = st.session_state.get(f"site_{token}") or default_site or ""
        if site == SITE_PLACEHOLDER:
            site = default_site or ""
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


def _doc_basename(contract: str, rrh: bool, site_label: str, description: str) -> str:
    """Contract-aware MSAPO document filename stem (no extension).

    RRH keeps its established convention exactly — "RRH {short-site} {desc} MSAPO".
    Every other contract is prefixed with its own name and chosen site instead of
    a hardcoded "RRH", so a Tulane/NOVANT/etc. administrator never receives a file
    labeled "RRH …". Built in the email step, where the contract and the user's
    final site choice are both known (the document itself is contract-neutral).
    """
    prefix = "RRH" if rrh else (contract or "").strip()
    safe_desc = re.sub(r"[^\w\s\-]", "", description or "SOW")[:50]
    # Don't cut mid-word ("…seals in t") — trim back to the last full word.
    if len(safe_desc) == 50 and " " in safe_desc:
        safe_desc = safe_desc.rsplit(" ", 1)[0]
    parts = [prefix, (site_label or "").strip(), safe_desc.strip(), "MSAPO"]
    name = " ".join(p for p in parts if p)
    # Strip characters that are invalid in filenames / attachment names.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    return re.sub(r"\s+", " ", name).strip() or "MSAPO"


def _build_test_analysis() -> QuoteAnalysis:
    """A realistic sample that exercises every downstream feature: a site with
    assets, an itemized subtotal + tax, and a guessable asset tag (CH-1)."""
    return QuoteAnalysis(
        vendor_name="Northeast Mechanical Services",
        project_description="Absorption chiller CH-1 teardown, inspection, and seasonal repair at Clifton Springs Hospital.",
        facility_name="Clifton Springs Hospital & Clinic",
        facility_address="2 Coulter Rd, Clifton Springs, NY 14432",
        scope_of_work=(
            "1. Isolate and drain absorption chiller CH-1 in the Central Plant.\n\n"
            "2. Inspect the CH-1 solution pump, purge unit, and tube bundle; replace "
            "worn gaskets and the purge valve.\n\n"
            "3. Verify cooling tower CT-1 interlocks and refill CH-1 with lithium "
            "bromide to spec, then run a full commissioning cycle."
        ),
        inclusions=[
            "Absorption chiller CH-1 teardown and reassembly",
            "Gasket and purge valve replacement",
            "Lithium bromide charge to manufacturer spec",
            "Full commissioning cycle and written report",
        ],
        exclusions=[
            "Replacement of the CH-1 tube bundle",
            "Refrigerant reclamation beyond the purge unit",
            "[AI ESTIMATE: After-hours or emergency service calls]",
            "[AI ESTIMATE: Crane or rigging for major component removal]",
        ],
        tax_status="included",
        tax_warning=None,
        tax_note="Estimated sales tax is included in the total. Actual invoice amount may differ.",
        ai_assumptions=[
            AIAssumption(text="After-hours or emergency service calls", section="exclusion"),
            AIAssumption(text="Crane or rigging for major component removal", section="exclusion"),
            AIAssumption(text="Facility provides access to the Central Plant during business hours", section="inclusion"),
        ],
        contact_name="Marcus Bell",
        contact_email="mbell@nemechanical.com",
        subtotal_amount="$4,200.00",
        tax_amount="$346.50",
        total_amount="$4,546.50",
        short_description="Chiller CH-1 Repair",
        work_category="repairs",
    )


def _load_test_into_state() -> None:
    analysis = _build_test_analysis()
    st.session_state["analysis"] = analysis
    st.session_state["analysis_token"] = "TEST"
    st.session_state["quote_text"] = analysis.scope_of_work
    st.session_state["last_sig"] = "TEST"
    st.session_state["uploaded_file_bytes"] = b"(sample quote placeholder)"
    st.session_state["uploaded_file_name"] = "Sample_Quote.pdf"
    st.session_state.pop("docx_path", None)
    st.session_state.pop("pdf_path", None)


def _render_send_section(*, recipient: str, subject: str, body: str, eml_bytes: bytes,
                         attachments: list[tuple[str, bytes]]) -> None:
    """One self-contained, client-side send panel.

    Detects iPhone/iPad vs. desktop in the browser (using navigator.maxTouchPoints,
    which is the only reliable way to catch an iPad that reports itself as a Mac)
    and shows the matching flow — Apple Mail share sheet or Outlook .eml download —
    with a manual switch for edge cases.  No server round-trip, no toggle to babysit.
    """
    payload = json.dumps({
        "subject": subject,
        "body": body,
        "to": recipient,
        "emlName": f"{subject}.eml",
        "emlB64": base64.b64encode(eml_bytes).decode("ascii"),
        "files": [
            {
                "name": name,
                "mime": mimetypes.guess_type(name)[0] or "application/octet-stream",
                "b64": base64.b64encode(data).decode("ascii"),
            }
            for name, data in attachments
        ],
    }).replace("<", "\\u003c")

    html = r"""
<div id="send-root" style="font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif;color:#12233B;">
  <div id="dev-chip" style="font-size:12px;font-weight:700;color:#6D5AE6;margin-bottom:8px;"></div>

  <!-- APPLE PANEL -->
  <div id="apple-panel" style="display:none;">
    <button id="share-btn" style="width:100%;background:linear-gradient(135deg,#F0803C,#E5661C);color:#fff;border:none;border-radius:12px;padding:15px 0;font-size:16px;font-weight:800;cursor:pointer;box-shadow:0 8px 20px rgba(240,128,60,.3);">
      &#128228;&nbsp; Share to Apple Mail &mdash; attachments attached
    </button>
    <div style="display:flex;gap:8px;margin-top:10px;">
      <div style="flex:1;">
        <div style="font-size:11px;font-weight:800;color:#9AA0B4;text-transform:uppercase;letter-spacing:.06em;">To</div>
        <div id="to-val" style="font-size:13px;font-weight:600;word-break:break-all;"></div>
      </div>
      <button class="copy-btn" data-target="to-val" style="align-self:flex-end;">Copy</button>
    </div>
    <div style="display:flex;gap:8px;margin-top:8px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:11px;font-weight:800;color:#9AA0B4;text-transform:uppercase;letter-spacing:.06em;">Subject</div>
        <div id="subj-val" style="font-size:13px;font-weight:600;overflow-wrap:anywhere;"></div>
      </div>
      <button class="copy-btn" data-target="subj-val" style="align-self:flex-end;">Copy</button>
    </div>
    <p style="color:#64748B;font-size:12.5px;margin:12px 2px 0;">
      Tap <b>Share to Apple Mail</b>, choose <b>Mail</b>, then paste the To &amp; Subject above.
      &nbsp;<a id="mailto-link" href="#" style="color:#12314F;font-weight:700;">Prefer a pre-filled draft?</a> (no attachments)
    </p>
  </div>

  <!-- DESKTOP PANEL -->
  <div id="desktop-panel" style="display:none;">
    <a id="eml-link" download="email.eml" href="#" style="display:block;text-align:center;text-decoration:none;background:linear-gradient(135deg,#12314F,#1C4A73);color:#fff;border-radius:12px;padding:15px 0;font-size:16px;font-weight:800;box-shadow:0 8px 20px rgba(18,49,79,.25);">
      &#128231;&nbsp; Download email for Outlook &mdash; then hit Send
    </a>
    <p style="color:#64748B;font-size:12.5px;margin:12px 2px 0;">
      Open the downloaded <b>.eml</b> in Outlook: it opens as a ready-to-send draft with every attachment already included.
    </p>
  </div>

  <div style="margin-top:12px;">
    <a id="switch-link" href="#" style="color:#9AA0B4;font-size:12px;text-decoration:underline;cursor:pointer;"></a>
  </div>
</div>
<script>
  const D = __PAYLOAD__;
  const root = document.getElementById("send-root");
  try {
    const b2blob = (b64, mime) => {
      const bin = atob(b64); const arr = new Uint8Array(bin.length);
      for (let i=0;i<bin.length;i++) arr[i] = bin.charCodeAt(i);
      return new Blob([arr], {type: mime});
    };
    const ua = navigator.userAgent || "";
    const isApple = /iPhone|iPad|iPod/.test(ua) || (navigator.maxTouchPoints > 1 && /Mac/.test(ua));

    const applePanel = document.getElementById("apple-panel");
    const desktopPanel = document.getElementById("desktop-panel");
    const chip = document.getElementById("dev-chip");
    const switchLink = document.getElementById("switch-link");
    const emlLink = document.getElementById("eml-link");
    let showingApple = isApple;

    // Build heavy objects lazily and only for the panel actually shown, and
    // revoke the object URL so it can't leak across Streamlit reruns (repeated
    // reruns leaking object URLs can crash a memory-constrained mobile tab).
    let _files = null, _emlUrl = null;
    const getFiles = () => {
      if (!_files) _files = D.files.map(f => new File([b2blob(f.b64, f.mime)], f.name, {type: f.mime}));
      return _files;
    };
    const revokeEml = () => { if (_emlUrl) { URL.revokeObjectURL(_emlUrl); _emlUrl = null; } };
    const ensureEmlUrl = () => {
      if (!_emlUrl) {
        _emlUrl = URL.createObjectURL(b2blob(D.emlB64, "message/rfc822"));
        emlLink.href = _emlUrl; emlLink.setAttribute("download", D.emlName);
      }
    };

    function paint() {
      applePanel.style.display = showingApple ? "block" : "none";
      desktopPanel.style.display = showingApple ? "none" : "block";
      chip.textContent = showingApple ? "📱  iPhone / iPad detected" : "💻  Desktop detected";
      switchLink.textContent = showingApple ? "On a computer instead? Show the Outlook option" : "On an iPhone or iPad instead? Show the Apple Mail option";
      if (showingApple) { revokeEml(); } else { ensureEmlUrl(); }
    }
    switchLink.addEventListener("click", (e) => { e.preventDefault(); showingApple = !showingApple; paint(); });

    document.getElementById("to-val").textContent = D.to || "(add recipient above)";
    document.getElementById("subj-val").textContent = D.subject;
    document.getElementById("mailto-link").href =
      "mailto:" + encodeURIComponent(D.to) + "?subject=" + encodeURIComponent(D.subject) + "&body=" + encodeURIComponent(D.body);

    const shareBtn = document.getElementById("share-btn");
    shareBtn.addEventListener("click", async () => {
      const files = getFiles();
      if (!(navigator.canShare && navigator.canShare({files}))) {
        alert("This browser can't share files directly. Use the pre-filled draft link, or switch to the Outlook option below.");
        return;
      }
      try { await navigator.share({files, title: D.subject, text: D.body}); } catch (err) {}
    });

    window.addEventListener("pagehide", revokeEml);
    paint();

    document.querySelectorAll(".copy-btn").forEach(btn => {
      btn.style.cssText += "background:#F1EEFB;border:1px solid #DDD6F3;color:#6D5AE6;border-radius:8px;padding:5px 12px;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;";
      btn.addEventListener("click", async () => {
        const txt = document.getElementById(btn.dataset.target).textContent;
        try { await navigator.clipboard.writeText(txt); btn.textContent = "Copied!"; setTimeout(() => btn.textContent = "Copy", 1400); }
        catch (e) { btn.textContent = "Copy failed"; }
      });
    });
  } catch (err) {
    if (root) root.innerHTML = '<div style="padding:12px;border:1px solid #FECACA;background:#FEF2F2;border-radius:10px;color:#991B1B;font-size:13px;">Send panel hit an error: ' + ((err && err.message) ? err.message : err) + '. Please screenshot this — you can still use the email preview above.</div>';
  }
</script>
"""
    components.html(html.replace("__PAYLOAD__", payload), height=340, scrolling=True)


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════
def main():
    st.set_page_config(
        page_title="Email Process Control",
        page_icon="📮",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # ── Hero ────────────────────────────────────────────────────────
    st.markdown("""
    <div class="hero">
        <span class="hero-emoji">📮</span>
        <h1>Email <span class="zing">Process Control</span></h1>
        <p class="hero-subtitle">
            Drop in a vendor quote and get a tidy, ready-to-send administrator email —
            MSAPO paperwork built, pricing tallied, the right contract and cost code confirmed.
            No fuss.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Byline that doubles as the secret sample-loader (click the name)
    bl, bc, br = st.columns([2, 3, 2])
    with bc:
        if st.button("Built by Evan Roden", key="name_test",
                     use_container_width=True,
                     help="click to load a sample and try the whole flow"):
            _load_test_into_state()
            # Reset the uploader so a lingering file can't re-trigger auto-analysis
            # and clobber the sample on the next rerun.
            st.session_state["uploader_nonce"] = st.session_state.get("uploader_nonce", 0) + 1
            st.rerun()

    # ── Order type ──────────────────────────────────────────────────
    epo_mode = st.checkbox(
        "📦  Equipment-only PO — delivered by a third party, no vendor visit "
        "(skips the MSAPO document; sends the quote + details only)",
        key="epo_mode",
    )

    # ════════════════════════════════════════════════════════════════
    # STEP 1 — Provide the quote (auto-analyzes on upload)
    # ════════════════════════════════════════════════════════════════
    st.markdown("""
    <div class="step-header">
        <div class="step-num navy">1</div>
        <p class="step-title">Provide the vendor quote</p>
    </div>
    """, unsafe_allow_html=True)

    tab_upload, tab_paste = st.tabs(["📁 Upload file", "📝 Paste text"])
    quote_text = ""

    with tab_upload:
        uploaded = st.file_uploader(
            "Upload quote (PDF, image, or text)",
            type=["pdf", "png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp", "heic", "heif", "hif", "txt"],
            label_visibility="collapsed",
            key=f"uploader_{st.session_state.get('uploader_nonce', 0)}",
        )
        if uploaded is not None:
            # getvalue() is position-independent — read() can return b"" on a
            # rerun after the buffer's already been consumed, which would blank
            # the quote and silently skip auto-analysis.
            file_bytes = uploaded.getvalue()
            st.session_state["uploaded_file_bytes"] = file_bytes
            st.session_state["uploaded_file_name"] = uploaded.name
            # Extract ONCE per file and cache it. Streamlit reruns the whole
            # script on every widget interaction; re-extracting each time is slow
            # and — for OCR — non-deterministic, which made later steps (e.g. a
            # generated document) reset when you edited a field further down.
            fhash = hashlib.sha256(file_bytes).hexdigest()
            if st.session_state.get("extract_hash") != fhash:
                with st.spinner("Reading your file… (scanned PDFs are read with OCR and take a few seconds)"):
                    try:
                        st.session_state["extracted_text"] = extract_text(file_bytes, uploaded.name)
                    except Exception as e:
                        st.error(f"Couldn't read that file: {e}")
                        st.session_state["extracted_text"] = ""
                st.session_state["extract_hash"] = fhash
            quote_text = st.session_state.get("extracted_text", "")
            if quote_text:
                with st.expander("Preview extracted text", expanded=False):
                    st.text_area("Raw text", quote_text, height=170,
                                 disabled=True, label_visibility="collapsed")
            else:
                st.warning("I couldn't find any readable text in that file. If it's a "
                           "photo or scan, try a clearer copy — or use the **Paste text** tab.")

    with tab_paste:
        pasted = st.text_area(
            "Paste the full vendor quote text",
            height=200, placeholder="Paste the vendor quote here…",
            label_visibility="collapsed",
        )
        if pasted.strip():
            quote_text = pasted.strip()

    # ── Auto-analyze whenever the input changes ─────────────────────
    if quote_text.strip():
        sig = hashlib.sha256(quote_text.encode("utf-8", "ignore")).hexdigest()
        if st.session_state.get("last_sig") != sig:
            with st.spinner("Reading the quote and pulling out the details…"):
                try:
                    analysis = analyze_quote(quote_text)
                except Exception as e:
                    msg = str(e)
                    if "overloaded" in msg.lower() or "529" in msg:
                        st.error("The AI service is briefly overloaded — give it a moment and re-upload.")
                    elif "401" in msg or "authentication" in msg.lower():
                        st.error("API authentication failed. Please check the API key.")
                    else:
                        st.error(f"Analysis failed: {e}")
                    st.stop()
            st.session_state["analysis"] = analysis
            st.session_state["analysis_token"] = sig[:12]
            st.session_state["last_sig"] = sig
            st.session_state["quote_text"] = quote_text
            st.session_state.pop("docx_path", None)
            st.session_state.pop("pdf_path", None)

    analysis: QuoteAnalysis | None = st.session_state.get("analysis")
    if analysis is None:
        st.info("Upload or paste a quote above and it'll be analyzed automatically. "
                "Or click the byline to try a sample.")
        _render_footer()
        return

    tok = st.session_state.get("analysis_token", "x")
    quote_text_cached = st.session_state.get("quote_text", "")

    # ════════════════════════════════════════════════════════════════
    # STEP 2 — Review
    # ════════════════════════════════════════════════════════════════
    st.markdown(f"""
    <div class="step-header">
        <div class="step-num mint">2</div>
        <p class="step-title">Here's what I found</p>
    </div>
    """, unsafe_allow_html=True)

    tax_map = {
        "included": ("INCLUDED", "tax-included", "✅"),
        "excluded": ("EXCLUDED", "tax-excluded", "⚠️"),
        "unclear": ("UNCLEAR", "tax-unclear", "❓"),
    }
    ts = analysis.tax_status or "unclear"
    tax_display, tax_class, tax_icon = tax_map.get(ts, (ts.upper(), "", "•"))

    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f"""<div class="metric-card"><div class="metric-icon">🏢</div>
            <div class="metric-label">Vendor</div>
            <div class="metric-value">{_h(analysis.vendor_name or "—")}</div></div>""", unsafe_allow_html=True)
    with m2:
        st.markdown(f"""<div class="metric-card"><div class="metric-icon">{tax_icon}</div>
            <div class="metric-label">Tax Status</div>
            <div class="metric-value {tax_class}">{_h(tax_display)}</div></div>""", unsafe_allow_html=True)
    with m3:
        st.markdown(f"""<div class="metric-card"><div class="metric-icon">💵</div>
            <div class="metric-label">Total</div>
            <div class="metric-value">{_h(analysis.total_amount or "—")}</div></div>""", unsafe_allow_html=True)

    if analysis.facility_name:
        st.markdown(f"""<div class="facility-banner"><div class="facility-icon">🏥</div>
            <div><div class="facility-name">{_h(analysis.facility_name)}</div>
            <div class="facility-address">{_h(analysis.facility_address or '')}</div></div></div>""",
            unsafe_allow_html=True)

    if analysis.tax_warning:
        st.markdown(f"""<div class="alert-box alert-danger"><span>🚨</span>
            <div><strong>Tax warning:</strong> {_h(analysis.tax_warning)}</div></div>""", unsafe_allow_html=True)
    if analysis.tax_note:
        st.markdown(f"""<div class="alert-box alert-warning"><span>📝</span>
            <div><strong>Tax note:</strong> {_h(analysis.tax_note)}</div></div>""", unsafe_allow_html=True)

    final_inclusions: list[str] = []
    final_exclusions: list[str] = []

    if not epo_mode:
        # Scope preview — collapsed by default
        with st.expander("📄 Scope of Work preview", expanded=False):
            st.markdown(f"""<div class="scope-section">
                <div class="scope-label">Project Description</div>
                <p class="scope-text">{_h(analysis.project_description)}</p></div>""", unsafe_allow_html=True)
            st.markdown(f"""<div class="scope-section">
                <div class="scope-label">Detailed Scope</div>
                <p class="scope-text" style="white-space:pre-line;">{_h(analysis.scope_of_work)}</p></div>""",
                unsafe_allow_html=True)

        unified_inc, unified_exc = _build_unified_lists(analysis)
        inc_col, exc_col = st.columns(2)
        with inc_col:
            st.markdown('<div class="scope-label">Inclusions</div>', unsafe_allow_html=True)
            st.caption("Uncheck to drop from the document.")
            for i, (text, is_ai) in enumerate(unified_inc):
                if st.checkbox(f"{'✎ ' if is_ai else ''}{text}", key=f"inc_{tok}_{i}", value=True):
                    final_inclusions.append(text)
        with exc_col:
            st.markdown('<div class="scope-label">Exclusions</div>', unsafe_allow_html=True)
            st.caption("Uncheck to drop from the document.")
            for i, (text, is_ai) in enumerate(unified_exc):
                if st.checkbox(f"{'✎ ' if is_ai else ''}{text}", key=f"exc_{tok}_{i}", value=True):
                    final_exclusions.append(text)
        if any(is_ai for _, is_ai in unified_inc + unified_exc):
            st.caption("✎ = suggested (not explicitly stated in the quote)")

    # ════════════════════════════════════════════════════════════════
    # STEP 3 — Generate MSAPO document (skipped for equipment-only POs)
    # ════════════════════════════════════════════════════════════════
    docx_path: Path | None = st.session_state.get("docx_path")
    pdf_path: Path | None = st.session_state.get("pdf_path")

    if not epo_mode:
        st.markdown("""
        <div class="step-header">
            <div class="step-num grape">3</div>
            <p class="step-title">Build the MSAPO document</p>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🛠️  Generate MSAPO files", type="primary", use_container_width=True):
            selected_contract, selected_site, facility_display, facility_address = (
                _routing_for_generation(analysis, quote_text_cached, tok)
            )
            with st.spinner("Assembling the MSAPO document…"):
                try:
                    docx_path = generate_docx(
                        analysis,
                        final_inclusions=final_inclusions,
                        final_exclusions=final_exclusions,
                        facility_display=facility_display,
                        facility_address_display=facility_address,
                    )
                    st.session_state["docx_path"] = docx_path
                    st.session_state["document_signature"] = _document_signature(
                        tok,
                        selected_contract,
                        selected_site,
                        final_inclusions,
                        final_exclusions,
                    )
                except Exception as e:
                    st.error(f"Document generation failed: {e}")
                    st.stop()
            with st.spinner("Converting to PDF…"):
                try:
                    pdf_path = convert_to_pdf(docx_path)
                    st.session_state["pdf_path"] = pdf_path
                except PDFConversionError as e:
                    st.warning(f"PDF conversion unavailable: {e}. The .docx is still ready.")
                    st.session_state["pdf_path"] = None
            st.markdown("""<div class="alert-box alert-success"><span>✓</span>
                <div><strong>Done.</strong> Your MSAPO document is built and attached to the email below.</div></div>""",
                unsafe_allow_html=True)
            docx_path = st.session_state.get("docx_path")
            pdf_path = st.session_state.get("pdf_path")

    # ════════════════════════════════════════════════════════════════
    # STEP 4 — Confirm routing and send the email
    # ════════════════════════════════════════════════════════════════
    email_ready = epo_mode or (docx_path and docx_path.exists())
    if not email_ready:
        st.caption("Generate the MSAPO files above to unlock the email step.")
        _render_footer()
        return

    step_n = "3" if epo_mode else "4"
    st.markdown(f"""
    <div class="step-header">
        <div class="step-num orange">{step_n}</div>
        <p class="step-title">Send the email {'(equipment-only PO)' if epo_mode else ''}</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Contract → recipient ────────────────────────────────────────
    # Recognition supplies a default, but an unknown quote must be confirmed by
    # the user instead of silently becoming an RRH purchase order.
    det_contract, det_site = contracts.match_facility(analysis.facility_name, quote_text_cached)
    crow = st.columns([1, 1])
    with crow[0]:
        _cnames = contracts.contract_names()
        _contract_options = [CONTRACT_PLACEHOLDER] + _cnames
        _cidx = _contract_options.index(det_contract) if det_contract in _contract_options else 0
        contract = st.selectbox(
            "Contract", _contract_options, index=_cidx, key=f"contract_{tok}"
        )
        if det_contract and not contracts.is_rrh(det_contract) and contract == det_contract:
            st.caption(f"↳ Recognized from the quote: **{det_site or det_contract}**")
    if contract == CONTRACT_PLACEHOLDER:
        st.warning("Choose the contract before preparing the email or final MSAPO.")
        _render_footer()
        return
    rrh = contracts.is_rrh(contract)
    with crow[1]:
        # RRH always goes to David; other contracts get their own administrator.
        recipient = st.text_input(
            "Send to (administrator email)",
            value=(DAVID_EMAIL if rrh else ""),
            key=f"recip_{tok}_{contract}",
            placeholder="administrator@company.com",
        )
        # Learned admin emails for THIS contract (>=5 uses). RRH is fixed to
        # David, so no picker there.
        if not rrh:
            admin_sugs = memory.suggest_admin_emails(contract)
            if admin_sugs:
                _ph = "— pick a known administrator —"

                def _fill_recipient(tok=tok, contract=contract, ph=_ph):
                    sel = st.session_state.get(f"recip_pick_{tok}_{contract}")
                    if sel and sel != ph:
                        st.session_state[f"recip_{tok}_{contract}"] = sel

                st.selectbox(
                    "Known administrators for this contract",
                    [_ph] + admin_sugs,
                    key=f"recip_pick_{tok}_{contract}",
                    on_change=_fill_recipient,
                )

    row1 = st.columns([1, 1, 1])
    if rrh:
        # ── RRH — dedicated flow: short site names + autofilled cost code ──
        fac_key = facility_key_from_name(analysis.facility_name)
        default_site_label = FACILITY_SHORT_NAMES.get(fac_key) if fac_key else None
        site_options = [SITE_PLACEHOLDER] + SITE_LABELS
        default_site_idx = (
            site_options.index(default_site_label)
            if default_site_label in site_options
            else 0
        )
        with row1[0]:
            site_label = st.selectbox(
                "Site", site_options, index=default_site_idx, key=f"site_{tok}"
            )
        if site_label == SITE_PLACEHOLDER:
            st.warning("Choose the RRH site before preparing the email or final MSAPO.")
            _render_footer()
            return
        sel_key = SITE_LABEL_TO_KEY[site_label]
        valid_cats = valid_categories_for_site(sel_key)
        cat_labels = [WORK_CATEGORY_DISPLAY.get(c, c) for c in valid_cats]
        default_cat_idx = valid_cats.index(analysis.work_category) if analysis.work_category in valid_cats else 0
        with row1[1]:
            cat_label = st.selectbox("Work category", cat_labels, index=default_cat_idx, key=f"cat_{tok}_{sel_key}")
        sel_cat = valid_cats[cat_labels.index(cat_label)]
        cost_code = lookup_cost_code(sel_key, sel_cat) or ""
        with row1[2]:
            if cost_code:
                st.markdown('<div class="field-label">Job cost code</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="cost-code-pill">🏷️ {cost_code}</div>', unsafe_allow_html=True)
            else:
                cost_code = st.text_input(
                    "Job cost code",
                    value="",
                    key=f"manualcost_{tok}_{sel_key}",
                    placeholder="Enter the site cost code",
                )
                st.caption("No automatic cost-code mapping is configured for this site.")
        site_line = f"RRH {site_label}"
    else:
        # ── Generic contract — dependent site dropdown + free-text cost code ──
        sites = contracts.sites_for_contract(contract)
        with row1[0]:
            if sites:
                site_options = [SITE_PLACEHOLDER] + sites
                _sidx = (
                    site_options.index(det_site)
                    if contract == det_contract and det_site in site_options
                    else 0
                )
                site_label = st.selectbox(
                    "Site", site_options, index=_sidx, key=f"gsite_{tok}_{contract}"
                )
                if site_label == SITE_PLACEHOLDER:
                    st.warning("Choose the site before preparing the email or final MSAPO.")
                    _render_footer()
                    return
            else:
                site_label = st.text_input("Site", value="", key=f"gsitetxt_{tok}_{contract}")
                if not site_label.strip():
                    st.warning("Enter the site before preparing the email or final MSAPO.")
                    _render_footer()
                    return
        with row1[1]:
            generic_category = WORK_CATEGORY_DISPLAY.get(
                analysis.work_category, analysis.work_category or ""
            )
            cat_label = st.text_input(
                "Work category",
                value=generic_category,
                key=f"gcat_{tok}_{contract}",
                placeholder="e.g. Chiller repair",
            )
        with row1[2]:
            cost_code = st.text_input("Job cost code", value="",
                                      key=f"gcost_{tok}_{contract}", placeholder="Paste the cost code")
        site_line = site_label

    if not epo_mode and docx_path and docx_path.exists():
        current_signature = _document_signature(
            tok, contract, site_label, final_inclusions, final_exclusions
        )
        if st.session_state.get("document_signature") != current_signature:
            st.session_state.pop("docx_path", None)
            st.session_state.pop("pdf_path", None)
            st.warning(
                "The contract, site, inclusions, or exclusions changed after the "
                "MSAPO was generated. Generate the files again before sending."
            )
            _render_footer()
            return

    # ── Applicable Asset ID — hidden for EPO and when the contract/site
    #    has no asset tags; otherwise a site-filtered dropdown with a guess. ──
    asset_id_value = "None Applicable"
    if not epo_mode:
        hint = analysis.asset_reference
        if rrh:
            site_assets = assets_for_facility(sel_key)
            guess = guess_asset_id(quote_text_cached, sel_key, hint=hint)
        else:
            site_assets = contracts.assets_for_site(contract, site_label)
            guess = contracts.guess_uid(quote_text_cached, contract, site_label, hint=hint)
        uids = [a["uid"] for a in site_assets]
        labels = {a["uid"]: contracts.asset_label(a) for a in site_assets}
        if uids:
            arow = st.columns([2, 1])
            with arow[1]:
                # Default to "no asset" unless a specific asset was confidently
                # identified — never fall back to the first alphabetical asset
                # (which used to leave e.g. the air separator wrongly selected).
                no_asset = st.checkbox("No asset applicable",
                                       key=f"noasset_{tok}_{contract}_{site_label}",
                                       value=(guess not in uids))
            with arow[0]:
                if not no_asset:
                    default_asset_idx = uids.index(guess) if guess in uids else 0
                    asset_id_value = st.selectbox(
                        "Applicable Asset ID", uids, index=default_asset_idx,
                        format_func=lambda u: f"{labels[u]}  ·  {u}",
                        key=f"asset_{tok}_{contract}_{site_label}",
                    )
                    a_show = next((a for a in site_assets if a["uid"] == asset_id_value), None)
                    if a_show:
                        name = _h(a_show.get("asset") or a_show["uid"])
                        if a_show.get("equipment"):
                            name += f' · {_h(a_show["equipment"])}'
                        serves = f' ({_h(a_show["serves"])})' if a_show.get("serves") else ""
                        st.markdown(
                            f'<div style="margin:-6px 0 4px;">'
                            f'<span style="font-weight:700;color:#12233B;">{name}</span>'
                            f'<span style="color:#94A3B8;font-size:0.72rem;">{serves}</span><br>'
                            f'<span style="color:#94A3B8;font-size:0.75rem;font-weight:500;">{_h(asset_id_value)}</span>'
                            f'</div>', unsafe_allow_html=True)
                else:
                    asset_id_value = "None Applicable"
                    st.markdown('<div class="field-label">Applicable Asset ID</div>', unsafe_allow_html=True)
                    st.markdown('<div class="cost-code-pill" style="background:#64748B;">None Applicable</div>',
                                unsafe_allow_html=True)
        # else: no asset tags for this contract/site → no asset field shown

    # ── Contact suggestions, scoped to THIS contract only ───────────
    # Learned pairs (entered together >=5 times), plus — when the vendor is
    # identified but the quote didn't give a clear contact — every rep we've
    # seen for that vendor on this contract (vendors rarely have many).
    contact_sugs: list[tuple[str, str]] = list(memory.suggest_contacts(contract))
    if analysis.vendor_name and not (analysis.contact_name and analysis.contact_email):
        for pair in memory.vendor_reps(contract, analysis.vendor_name):
            if pair not in contact_sugs:
                contact_sugs.append(pair)
    if contact_sugs:
        _cph = "— pick a known contact to fill both fields —"
        _by_label = {f"{n}  <{e}>": (n, e) for n, e in contact_sugs}

        def _fill_contact(tok=tok, contract=contract, ph=_cph, by_label=_by_label):
            sel = st.session_state.get(f"contact_pick_{tok}_{contract}")
            if sel and sel != ph:
                n, e = by_label[sel]
                st.session_state[f"contact_{tok}"] = n
                st.session_state[f"cemail_{tok}"] = e

        st.selectbox(
            f"Known contacts on {contract}",
            [_cph] + list(_by_label.keys()),
            key=f"contact_pick_{tok}_{contract}",
            on_change=_fill_contact,
        )

    # Contact + description
    row2 = st.columns([1, 1, 1])
    with row2[0]:
        email_contact = st.text_input("Contact name", value=analysis.contact_name or "", key=f"contact_{tok}")
    with row2[1]:
        email_contact_email = st.text_input("Contact email", value=analysis.contact_email or "", key=f"cemail_{tok}")
    with row2[2]:
        email_desc = st.text_input("Short description (≤20 chars)",
                                   value=(analysis.short_description or "")[:20],
                                   max_chars=20, key=f"desc_{tok}")

    # Pricing
    st.markdown('<div class="field-label" style="margin-top:0.4rem;">Pricing — leave subtotal & tax blank if the quote shows a single all-in total</div>', unsafe_allow_html=True)
    prow = st.columns(3)
    with prow[0]:
        subtotal_val = st.text_input("Subtotal (pre-tax)", value=analysis.subtotal_amount or "", key=f"sub_{tok}")
    with prow[1]:
        tax_val = st.text_input("Sales tax", value=analysis.tax_amount or "", key=f"tax_{tok}")
    with prow[2]:
        total_val = st.text_input("Total amount", value=analysis.total_amount or "", key=f"total_{tok}")

    vendor = analysis.vendor_name or "Vendor"
    breakdown = _has_breakdown(subtotal_val, tax_val)
    pricing_difference = _pricing_difference(subtotal_val, tax_val, total_val)
    if breakdown and pricing_difference is not None and abs(pricing_difference) > Decimal("0.01"):
        st.warning(
            "Subtotal plus sales tax does not equal the total. Confirm the quote "
            "amounts before sending."
        )

    # ── Assemble bullets + subject per order type ───────────────────
    if epo_mode:
        subject = f"{vendor} {email_desc} at {site_label} EPO".strip()
        bullets = [
            ("Site Location", site_line),
            ("Work Category", cat_label),
            ("Description", email_desc),
            ("Job cost code", cost_code or "—"),
            ("Contact Name", email_contact),
            ("Contact Email", email_contact_email),
        ]
    else:
        subject = f"{vendor} {email_desc} at {site_label} MSA PO".strip()
        bullets = [
            ("Site Location", site_line),
            ("Job cost code", cost_code or "—"),
            ("Applicable Asset ID", asset_id_value),
            ("Subcontractor name", vendor),
            ("Contact Name", email_contact),
            ("Contact Email", email_contact_email),
            ("Description", email_desc),
        ]
    if breakdown:
        bullets.append(("Subtotal (pre-tax)", subtotal_val))
        bullets.append(("Sales Tax", tax_val))
    bullets.append(("Amount", total_val))

    plain_body = build_plain_body(bullets)

    if not recipient.strip():
        st.caption("⬆︎ Add the administrator's email above before sending.")

    with st.expander("Preview the email", expanded=False):
        st.markdown(f"**To:** {_h(recipient) or '—'}")
        st.markdown(f"**Subject:** {subject}")
        st.markdown("---")
        st.text(plain_body)
        st.caption("Your Outlook/Apple Mail signature is added automatically.")

    # ── Attachments ─────────────────────────────────────────────────
    attachments: list[tuple[str, bytes]] = []
    up_bytes = st.session_state.get("uploaded_file_bytes")
    up_name = st.session_state.get("uploaded_file_name")
    if up_bytes and up_name:
        attachments.append((up_name, up_bytes))
    elif quote_text_cached:
        # Quote was pasted, not uploaded — attach the text so the email
        # (especially an EPO, which has no other attachment) still carries it.
        attachments.append(("Vendor Quote.txt", quote_text_cached.encode("utf-8")))
    if not epo_mode:
        # Name the attachments per the selected contract + site (the on-disk
        # name from generate_docx is RRH-shaped and set before the contract is
        # known, so it must not reach the recipient for non-RRH contracts).
        doc_name = _doc_basename(contract, rrh, site_label, analysis.project_description)
        if docx_path and docx_path.exists():
            attachments.append((f"{doc_name}.docx", docx_path.read_bytes()))
        if pdf_path and pdf_path.exists():
            attachments.append((f"{doc_name}.pdf", pdf_path.read_bytes()))

    eml_bytes = build_eml(to=recipient, subject=subject, bullets=bullets, attachments=attachments)

    _render_send_section(recipient=recipient, subject=subject, body=plain_body,
                         eml_bytes=eml_bytes, attachments=attachments)

    # Keep the handoff in this Streamlit session. A direct URL visit creates a
    # fresh session and cannot safely reuse the reviewed quote or attachments.
    _render_smartsheet_handoff_link("4" if epo_mode else "5")

    # ── Learning: remember this send's details for this contract ────
    # Sending happens client-side (share sheet / .eml), so the app can't see
    # it — this button is the explicit "I sent it" signal. Once per quote+
    # contract to keep the >=5-uses counts honest.
    rec_key = f"recorded_{tok}_{contract}"
    if st.session_state.get(rec_key):
        st.caption("✓ Details remembered for this contract — frequently used "
                   "emails start auto-suggesting after 5 uses.")
    elif st.button("✓ I sent it — remember these details for next time",
                   key=f"rec_btn_{tok}_{contract}", use_container_width=True):
        saved = memory.record_send(
            contract=contract,
            admin_email=recipient,
            vendor=analysis.vendor_name,
            contact_name=email_contact,
            contact_email=email_contact_email,
        )
        st.session_state[rec_key] = True
        if saved:
            st.rerun()
        else:
            st.caption("Couldn't reach the memory store — details not saved this time.")

    _render_footer()


def _render_smartsheet_handoff_link(step_number: str) -> None:
    """Expose the prepared PO handoff without relying on sidebar discovery.

    st.page_link performs Streamlit's in-session page transition. This is
    intentional: navigating directly to /Smartsheet_PO creates a new websocket
    session and loses the reviewed quote, generated documents, and verified
    attachment fingerprints held in st.session_state.
    """
    st.markdown(
        f"""
        <div class="step-header">
            <div class="step-num mint">{_h(step_number)}</div>
            <p class="step-title">Submit the PO request</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Continue in this tab so the reviewed PO values and verified attachments "
        "carry into Smartsheet."
    )
    st.page_link(
        "pages/2_Smartsheet_PO.py",
        label="Continue to Smartsheet PO handoff",
        icon="📋",
        use_container_width=True,
    )


def _render_footer() -> None:
    st.markdown("""
    <div class="app-footer">
        <div class="footer-divider"></div>
        Built by <a href="mailto:evan.roden@ENFRAsolutions.com">Evan Roden</a>
        &nbsp;•&nbsp; a friendlier way to push paper 📮
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
