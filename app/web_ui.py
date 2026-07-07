"""
Streamlit web interface for the MSAPO Generator.

Mobile-responsive portal where users can:
  1. Upload a vendor quote (PDF, image, or text file)
  2. Optionally paste quote text directly
  3. View the extracted analysis
  4. Review and approve/reject AI assumptions via checkboxes
  5. Download the generated .docx and .pdf
"""

from __future__ import annotations

import base64
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
from app.config import (
    FACILITY_SHORT_NAMES,
    WORK_CATEGORY_DISPLAY,
    WORK_CATEGORY_SUFFIXES,
    facility_key_from_name,
    lookup_cost_code,
    valid_categories_for_site,
)

# ── Design System ────────────────────────────────────────────────────
# Navy: #1B3A5C   Orange: #E8792F   Slate: #1E293B   Surface: #F7F9FC

CUSTOM_CSS = """
<style>
    /* ── Typography ────────────────────────────────────── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        background: #F1F5F9;
    }

    /* Hide default Streamlit chrome */
    #MainMenu, footer, header {visibility: hidden;}

    /* Subtle dot pattern on background */
    .stApp::before {
        content: '';
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background-image: radial-gradient(#CBD5E1 0.5px, transparent 0.5px);
        background-size: 24px 24px;
        opacity: 0.4;
        pointer-events: none;
        z-index: 0;
    }

    /* Main content wrapper */
    .block-container {
        position: relative;
        z-index: 1;
        max-width: 720px !important;
        padding-top: 2rem !important;
    }

    /* ── Hero Header ───────────────────────────────────── */
    .hero {
        background: linear-gradient(135deg, #0F2942 0%, #1B3A5C 40%, #254B73 100%);
        padding: 2rem 2.25rem 1.75rem;
        border-radius: 16px;
        margin-bottom: 1.75rem;
        position: relative;
        overflow: hidden;
        box-shadow: 0 8px 32px rgba(15,41,66,0.25), 0 2px 8px rgba(0,0,0,0.1);
    }
    .hero::before {
        content: '';
        position: absolute;
        top: -50%; right: -20%;
        width: 300px; height: 300px;
        background: radial-gradient(circle, rgba(232,121,47,0.15) 0%, transparent 70%);
        border-radius: 50%;
    }
    .hero::after {
        content: '';
        position: absolute;
        bottom: -30%; left: -10%;
        width: 200px; height: 200px;
        background: radial-gradient(circle, rgba(255,255,255,0.05) 0%, transparent 70%);
        border-radius: 50%;
    }
    .hero h1 {
        color: #FFFFFF;
        font-size: 1.65rem;
        font-weight: 800;
        margin: 0 0 0.35rem 0;
        letter-spacing: -0.03em;
        line-height: 1.2;
        position: relative;
    }
    .hero-subtitle {
        color: rgba(255,255,255,0.6);
        font-size: 0.85rem;
        margin: 0;
        position: relative;
    }
    .hero-accent {
        color: #E8792F;
        font-weight: 700;
    }
    .hero-badge {
        position: absolute;
        top: 1.5rem; right: 1.75rem;
        background: rgba(232,121,47,0.12);
        border: 1px solid rgba(232,121,47,0.25);
        color: #F5A66B;
        padding: 0.3rem 0.85rem;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    /* ── Intro Text ────────────────────────────────────── */
    .intro-text {
        background: white;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 1rem 1.5rem;
        margin-bottom: 1.5rem;
        font-size: 0.9rem;
        color: #475569;
        line-height: 1.6;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    .intro-text strong {
        color: #1E293B;
    }

    /* ── Step Headers ──────────────────────────────────── */
    .step-header {
        display: flex;
        align-items: center;
        gap: 0.85rem;
        margin-bottom: 0.75rem;
        margin-top: 0.5rem;
    }
    .step-num {
        width: 36px; height: 36px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.85rem;
        font-weight: 800;
        flex-shrink: 0;
        transition: all 0.3s ease;
    }
    .step-num.navy { background: #1B3A5C; color: white; }
    .step-num.orange { background: #E8792F; color: white; }
    .step-num.green { background: #16A34A; color: white; }
    .step-title {
        font-size: 1.15rem;
        font-weight: 700;
        color: #0F172A;
        margin: 0;
        letter-spacing: -0.01em;
    }

    /* ── Cards ─────────────────────────────────────────── */
    .content-card {
        background: white;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 1.5rem;
        margin-bottom: 0.75rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    }

    /* ── Metric Cards ──────────────────────────────────── */
    .metric-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.85rem;
        margin-bottom: 1rem;
    }
    .metric-card {
        background: white;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 1.15rem 1.35rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.07);
    }
    .metric-icon {
        font-size: 1.25rem;
        margin-bottom: 0.4rem;
    }
    .metric-label {
        font-size: 0.68rem;
        font-weight: 700;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.3rem;
    }
    .metric-value {
        font-size: 1.15rem;
        font-weight: 800;
        color: #0F172A;
    }

    /* ── Facility Banner ───────────────────────────────── */
    .facility-banner {
        background: linear-gradient(135deg, #EFF6FF 0%, #F0F9FF 100%);
        border: 1px solid #BFDBFE;
        border-left: 4px solid #1B3A5C;
        border-radius: 10px;
        padding: 1.1rem 1.35rem;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 0.85rem;
    }
    .facility-icon {
        font-size: 1.5rem;
        flex-shrink: 0;
    }
    .facility-name {
        font-weight: 800;
        color: #0F172A;
        font-size: 0.95rem;
    }
    .facility-address {
        color: #64748B;
        font-size: 0.82rem;
        margin-top: 0.1rem;
    }

    /* ── Tax Badges ────────────────────────────────────── */
    .tax-included { color: #16A34A; }
    .tax-excluded { color: #E8792F; }
    .tax-unclear { color: #DC2626; }

    /* ── Alert Boxes ───────────────────────────────────── */
    .alert-box {
        border-radius: 10px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.75rem;
        font-size: 0.88rem;
        line-height: 1.5;
        display: flex;
        align-items: flex-start;
        gap: 0.65rem;
    }
    .alert-box .alert-icon { font-size: 1.1rem; flex-shrink: 0; margin-top: 0.05rem; }
    .alert-warning {
        background: #FFFBEB;
        border: 1px solid #FDE68A;
        color: #92400E;
    }
    .alert-danger {
        background: #FEF2F2;
        border: 1px solid #FECACA;
        color: #991B1B;
    }
    .alert-success {
        background: #F0FDF4;
        border: 1px solid #BBF7D0;
        color: #166534;
    }

    /* ── Scope Preview ─────────────────────────────────── */
    .scope-section {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 1.25rem 1.35rem;
        margin-bottom: 0.85rem;
    }
    .scope-label {
        font-size: 0.68rem;
        font-weight: 800;
        color: #1B3A5C;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.6rem;
        padding-bottom: 0.45rem;
        border-bottom: 2px solid #E8792F;
        display: inline-block;
    }
    .scope-text {
        color: #334155;
        font-size: 0.88rem;
        line-height: 1.65;
        margin: 0;
    }

    /* ── List Items ────────────────────────────────────── */
    .list-item {
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        padding: 0.45rem 0.75rem;
        border-radius: 8px;
        font-size: 0.85rem;
        margin-bottom: 0.3rem;
        line-height: 1.4;
    }
    .list-item-explicit {
        background: #F1F5F9;
        color: #334155;
    }
    .list-item-ai {
        background: #FFF7ED;
        color: #9A3412;
        border: 1px dashed #FDBA74;
    }
    .list-bullet {
        color: #94A3B8;
        flex-shrink: 0;
        margin-top: 0.1rem;
    }

    /* ── Section Tags ──────────────────────────────────── */
    .section-tag {
        display: inline-block;
        font-size: 0.65rem;
        font-weight: 800;
        padding: 0.2rem 0.55rem;
        border-radius: 5px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .tag-inclusion { background: #DCFCE7; color: #166534; }
    .tag-exclusion { background: #FEE2E2; color: #991B1B; }
    .tag-scope { background: #DBEAFE; color: #1E40AF; }

    /* ── Download Section ──────────────────────────────── */
    .download-section {
        background: linear-gradient(135deg, #0F2942 0%, #1B3A5C 100%);
        border-radius: 14px;
        padding: 1.5rem;
        text-align: center;
        margin: 1rem 0;
        position: relative;
        overflow: hidden;
    }
    .download-section::before {
        content: '';
        position: absolute;
        top: -50%; right: -30%;
        width: 200px; height: 200px;
        background: radial-gradient(circle, rgba(232,121,47,0.1) 0%, transparent 70%);
        border-radius: 50%;
    }
    .download-title {
        color: rgba(255,255,255,0.9);
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 1rem;
        position: relative;
    }
    .download-title .dl-icon {
        font-size: 1.5rem;
        display: block;
        margin-bottom: 0.35rem;
    }

    /* ── Footer ────────────────────────────────────────── */
    .app-footer {
        text-align: center;
        padding: 1.75rem 1rem 1rem;
        margin-top: 2rem;
        color: #94A3B8;
        font-size: 0.78rem;
    }
    .app-footer a {
        color: #E8792F;
        text-decoration: none;
        font-weight: 600;
    }
    .app-footer a:hover {
        text-decoration: underline;
    }
    .footer-divider {
        width: 40px;
        height: 3px;
        background: linear-gradient(90deg, #E8792F, #1B3A5C);
        border-radius: 2px;
        margin: 0 auto 0.85rem;
    }

    /* ── Streamlit Overrides ───────────────────────────── */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #E8792F 0%, #D4691A 100%);
        border: none;
        border-radius: 10px;
        font-weight: 700;
        font-size: 0.95rem;
        padding: 0.65rem 1.5rem;
        letter-spacing: 0.01em;
        transition: all 0.25s ease;
        box-shadow: 0 2px 8px rgba(232,121,47,0.2);
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #D4691A 0%, #C05E15 100%);
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(232,121,47,0.35);
    }
    .stButton > button[kind="primary"]:active {
        transform: translateY(0);
    }

    div[data-testid="stDownloadButton"] > button {
        border-radius: 10px;
        font-weight: 700;
        font-size: 0.9rem;
        transition: all 0.2s ease;
        border: 2px solid #1B3A5C;
        color: #1B3A5C;
        background: white;
    }
    div[data-testid="stDownloadButton"] > button:hover {
        background: #1B3A5C;
        color: white;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(27,58,92,0.2);
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        background: #F1F5F9;
        border-radius: 10px;
        padding: 3px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        font-weight: 600;
        font-size: 0.85rem;
    }

    div[data-testid="stFileUploader"] {
        border-radius: 12px;
    }
    div[data-testid="stFileUploader"] section {
        border-radius: 12px;
        border: 2px dashed #CBD5E1;
        background: #FAFBFC;
        transition: border-color 0.2s;
    }
    div[data-testid="stFileUploader"] section:hover {
        border-color: #E8792F;
    }

    div[data-testid="stExpander"] {
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        background: white;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    }

    /* Checkbox styling */
    .stCheckbox label {
        font-weight: 500;
        font-size: 0.9rem;
    }

    /* Divider */
    hr {
        border: none;
        border-top: 1px solid #E2E8F0;
        margin: 1.25rem 0;
    }

    /* Spinner styling */
    .stSpinner > div {
        border-color: #E8792F transparent transparent transparent !important;
    }
</style>
"""


def _strip_ai_wrapper(text: str) -> str:
    """Strip [AI ESTIMATE: ...] wrapper, returning just the inner text."""
    m = re.search(r"\[AI ESTIMATE:\s*(.+?)\]", text)
    return m.group(1) if m else text


def _build_unified_lists(
    analysis: QuoteAnalysis,
) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """Build unified (text, is_ai) lists for inclusions and exclusions.

    Merges items from analysis.inclusions/exclusions with any extra
    ai_assumptions that aren't already present.  Returns two lists of
    (clean_text, is_ai_generated) tuples.
    """
    def _process(raw_items: list[str], section_key: str) -> list[tuple[str, bool]]:
        seen: set[str] = set()
        result: list[tuple[str, bool]] = []
        for item in raw_items:
            is_ai = "[AI ESTIMATE:" in item
            clean = _strip_ai_wrapper(item)
            if clean not in seen:
                seen.add(clean)
                result.append((clean, is_ai))
        # Merge any ai_assumptions for this section not already present
        for assumption in analysis.ai_assumptions:
            if assumption.section == section_key and assumption.text not in seen:
                seen.add(assumption.text)
                result.append((assumption.text, True))
        return result

    inclusions = _process(analysis.inclusions, "inclusion")
    exclusions = _process(analysis.exclusions, "exclusion")
    return inclusions, exclusions


def _build_test_analysis() -> QuoteAnalysis:
    """Return a realistic hardcoded QuoteAnalysis for UI testing."""
    return QuoteAnalysis(
        vendor_name="Culligan Water",
        project_description="Monthly water softener salt delivery and system service for UMMC.",
        facility_name="United Memorial Medical Center",
        facility_address="127 North St, Batavia, NY 14020",
        scope_of_work=(
            "1. Deliver and install water softener salt (40 bags) to the mechanical "
            "room at United Memorial Medical Center.\n\n"
            "2. Inspect the existing Culligan water softener system, verify brine "
            "tank levels, and confirm proper regeneration cycles.\n\n"
            "3. Test water hardness at three sample points (incoming supply, post-softener, "
            "and hot water return) and document results."
        ),
        inclusions=[
            "Water softener salt — 40 bags delivered and stacked in mechanical room",
            "System inspection and regeneration cycle verification",
            "Water hardness testing at three sample points",
            "Written service report with test results",
        ],
        exclusions=[
            "Repair or replacement of softener components",
            "Plumbing modifications or new piping",
            "[AI ESTIMATE: Disposal of used salt bags or packaging materials]",
            "[AI ESTIMATE: After-hours or emergency service calls]",
        ],
        tax_status="included",
        tax_warning=None,
        tax_note="Estimated sales tax is included in the total. Actual invoice amount may differ.",
        ai_assumptions=[
            AIAssumption(text="Disposal of used salt bags or packaging materials", section="exclusion"),
            AIAssumption(text="After-hours or emergency service calls", section="exclusion"),
            AIAssumption(text="Access to mechanical room provided by facility staff during business hours", section="inclusion"),
        ],
        contact_name="Liz Davidson",
        contact_email="britt@wnyculligan.com",
        total_amount="$577.47",
        short_description="Water Softener Salt",
        work_category="water_softener",
    )


def _detect_apple_mobile() -> bool:
    """True when the request comes from an iPhone or iPad.

    iPad Safari reports itself as a Mac by default ("Request Desktop
    Website"), so user-agent sniffing alone misses many iPads — the UI
    pairs this with a manual toggle that defaults to the detected value.
    """
    try:
        ua = st.context.headers.get("User-Agent") or ""
    except Exception:
        return False
    return "iPhone" in ua or "iPad" in ua


def _render_apple_mail_share(
    subject: str, body: str, attachments: list[tuple[str, bytes]]
) -> None:
    """Render a share-sheet button that hands the attachments (and body
    text) straight to Apple Mail via the Web Share API.

    mailto: links can't carry attachments and .eml files don't open as
    drafts in iOS Mail, so the share sheet is the only way to get the
    files into a compose window in one tap.
    """
    payload = json.dumps({
        "subject": subject,
        "body": body,
        "files": [
            {
                "name": name,
                "mime": mimetypes.guess_type(name)[0] or "application/octet-stream",
                "b64": base64.b64encode(data).decode("ascii"),
            }
            for name, data in attachments
        ],
    }).replace("<", "\\u003c")  # keep user text from closing the <script> tag
    html = """
<div style="font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif;">
  <button id="share-btn" style="width:100%; background:#E8792F; color:#ffffff; border:none;
      border-radius:10px; padding:14px 0; font-size:16px; font-weight:600; cursor:pointer;">
    &#128228;&nbsp; Share to Apple Mail &mdash; attachments included
  </button>
  <p id="share-hint" style="color:#64748B; font-size:13px; margin:8px 2px 0;">
    Choose <b>Mail</b> in the share sheet, then paste the subject and address it to David.
  </p>
</div>
<script>
  const DATA = __PAYLOAD__;
  const btn = document.getElementById("share-btn");
  const hint = document.getElementById("share-hint");
  const files = DATA.files.map(f => new File(
    [Uint8Array.from(atob(f.b64), c => c.charCodeAt(0))],
    f.name, {type: f.mime}
  ));
  if (!(navigator.canShare && navigator.canShare({files: files}))) {
    btn.disabled = true;
    btn.style.opacity = "0.5";
    hint.innerHTML = "This browser can't share files directly &mdash; use the " +
      "<b>pre-filled draft</b> link below and add the downloaded files by hand, " +
      "or switch to the Outlook option.";
  } else {
    btn.addEventListener("click", async () => {
      try {
        await navigator.share({files: files, title: DATA.subject, text: DATA.body});
      } catch (err) { /* user closed the share sheet — nothing to do */ }
    });
  }
</script>
"""
    components.html(html.replace("__PAYLOAD__", payload), height=140)


def main():
    st.set_page_config(
        page_title="MSAPO Generator",
        page_icon="📋",
        layout="centered",
        initial_sidebar_state="collapsed",
    )

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # ── Hero Header ─────────────────────────────────────────────────────
    hero_col, test_col = st.columns([5, 1])
    with hero_col:
        st.markdown("""
        <div class="hero">
            <div class="hero-badge">RRH Network</div>
            <h1>MSAPO Scope of Work<br>Generator</h1>
            <p class="hero-subtitle">
                Built by <span class="hero-accent">Evan Roden</span>
            </p>
        </div>
        """, unsafe_allow_html=True)
    with test_col:
        if st.button("Test", help="Load sample data to test later stages"):
            st.session_state["analysis"] = _build_test_analysis()
            st.session_state["uploaded_file_bytes"] = b"(test quote file)"
            st.session_state["uploaded_file_name"] = "Test_Quote.pdf"
            st.session_state.pop("docx_path", None)
            st.session_state.pop("pdf_path", None)
            st.rerun()

    st.markdown("""
    <div class="intro-text">
        Upload a vendor quote and instantly generate a standards-compliant
        <strong>MSAPO agreement</strong> (.docx and .pdf) — ready for review and submission.
    </div>
    """, unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════
    # STEP 1 — Upload
    # ════════════════════════════════════════════════════════════════════
    st.markdown("""
    <div class="step-header">
        <div class="step-num navy">1</div>
        <p class="step-title">Provide the Vendor Quote</p>
    </div>
    """, unsafe_allow_html=True)

    tab_upload, tab_paste = st.tabs(["📁 Upload File", "📝 Paste Text"])

    quote_text = ""

    with tab_upload:
        uploaded = st.file_uploader(
            "Upload quote (PDF, image, or text)",
            type=["pdf", "png", "jpg", "jpeg", "tiff", "bmp", "txt", "webp"],
            label_visibility="collapsed",
        )
        if uploaded is not None:
            file_bytes = uploaded.read()
            # Persist for email attachment later
            st.session_state["uploaded_file_bytes"] = file_bytes
            st.session_state["uploaded_file_name"] = uploaded.name
            with st.spinner("Extracting text from file..."):
                try:
                    quote_text = extract_text(file_bytes, uploaded.name)
                except Exception as e:
                    st.error(f"Failed to extract text: {e}")
                    quote_text = ""

            if quote_text:
                with st.expander("Preview extracted text", expanded=False):
                    st.text_area(
                        "Raw text",
                        quote_text,
                        height=180,
                        disabled=True,
                        label_visibility="collapsed",
                    )

    with tab_paste:
        pasted = st.text_area(
            "Paste the full vendor quote text below",
            height=220,
            placeholder="Paste the vendor quote here...",
            label_visibility="collapsed",
        )
        if pasted.strip():
            quote_text = pasted.strip()

    # ════════════════════════════════════════════════════════════════════
    # STEP 2 — Analyze
    # ════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("""
    <div class="step-header">
        <div class="step-num navy">2</div>
        <p class="step-title">Analyze Quote</p>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Analyze Quote", type="primary", use_container_width=True):
        if not quote_text.strip():
            st.error("Please upload a file or paste quote text first.")
            st.stop()

        with st.spinner("Analyzing quote — this may take up to 30 seconds..."):
            try:
                analysis = analyze_quote(quote_text)
            except Exception as e:
                error_msg = str(e)
                if "overloaded" in error_msg.lower() or "529" in error_msg:
                    st.error(
                        "The AI service is temporarily overloaded. "
                        "Please wait a moment and try again."
                    )
                elif "401" in error_msg or "authentication" in error_msg.lower():
                    st.error("API authentication failed. Please check your API key.")
                else:
                    st.error(f"Analysis failed: {e}")
                st.stop()

        st.session_state["analysis"] = analysis
        st.session_state.pop("docx_path", None)
        st.session_state.pop("pdf_path", None)

    # ════════════════════════════════════════════════════════════════════
    # STEP 3 — Review Analysis
    # ════════════════════════════════════════════════════════════════════
    analysis: QuoteAnalysis | None = st.session_state.get("analysis")

    if analysis is not None:
        st.markdown("---")
        st.markdown("""
        <div class="step-header">
            <div class="step-num green">3</div>
            <p class="step-title">Review Analysis</p>
        </div>
        """, unsafe_allow_html=True)

        # ── Summary Metrics ──────────────────────────────────────────
        tax_display = analysis.tax_status.upper()
        tax_class = ""
        tax_icon = ""
        if analysis.tax_status == "included":
            tax_display = "INCLUDED"
            tax_class = "tax-included"
            tax_icon = "✅"
        elif analysis.tax_status == "excluded":
            tax_display = "EXCLUDED"
            tax_class = "tax-excluded"
            tax_icon = "⚠️"
        elif analysis.tax_status == "unclear":
            tax_display = "UNCLEAR"
            tax_class = "tax-unclear"
            tax_icon = "❌"

        st.markdown(f"""
        <div class="metric-grid">
            <div class="metric-card">
                <div class="metric-icon">🏢</div>
                <div class="metric-label">Vendor</div>
                <div class="metric-value">{analysis.vendor_name or "N/A"}</div>
            </div>
            <div class="metric-card">
                <div class="metric-icon">{tax_icon}</div>
                <div class="metric-label">Tax Status</div>
                <div class="metric-value {tax_class}">{tax_display}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Facility ─────────────────────────────────────────────────
        if analysis.facility_name:
            st.markdown(f"""
            <div class="facility-banner">
                <div class="facility-icon">🏥</div>
                <div>
                    <div class="facility-name">{analysis.facility_name}</div>
                    <div class="facility-address">{analysis.facility_address or ''}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # ── Tax Alerts ───────────────────────────────────────────────
        if analysis.tax_warning:
            st.markdown(f"""
            <div class="alert-box alert-danger">
                <span class="alert-icon">🚨</span>
                <div><strong>Tax Warning:</strong> {analysis.tax_warning}</div>
            </div>
            """, unsafe_allow_html=True)

        if analysis.tax_note:
            st.markdown(f"""
            <div class="alert-box alert-warning">
                <span class="alert-icon">📝</span>
                <div><strong>Tax Note:</strong> {analysis.tax_note}</div>
            </div>
            """, unsafe_allow_html=True)

        # ── Scope Preview (read-only) ─────────────────────────────────
        with st.expander("Scope of Work Preview", expanded=True):
            st.markdown(f"""
            <div class="scope-section">
                <div class="scope-label">Project Description</div>
                <p class="scope-text">{analysis.project_description}</p>
            </div>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div class="scope-section">
                <div class="scope-label">Detailed Scope</div>
                <p class="scope-text" style="white-space:pre-line;">{analysis.scope_of_work}</p>
            </div>
            """, unsafe_allow_html=True)

        # ── Editable Inclusions & Exclusions ──────────────────────────
        unified_inc, unified_exc = _build_unified_lists(analysis)

        st.markdown("""
        <div class="scope-section" style="margin-top:0.5rem;">
            <div class="scope-label">Inclusions</div>
        </div>
        """, unsafe_allow_html=True)
        st.caption("Uncheck any item to remove it from the final document.")

        final_inclusions: list[str] = []
        for i, (text, is_ai) in enumerate(unified_inc):
            label = f"{'🤖 ' if is_ai else ''}{text}"
            checked = st.checkbox(label, key=f"inc_{i}", value=True)
            if checked:
                final_inclusions.append(text)

        st.markdown("""
        <div class="scope-section" style="margin-top:1rem;">
            <div class="scope-label">Exclusions</div>
        </div>
        """, unsafe_allow_html=True)
        st.caption("Uncheck any item to remove it from the final document.")

        final_exclusions: list[str] = []
        for i, (text, is_ai) in enumerate(unified_exc):
            label = f"{'🤖 ' if is_ai else ''}{text}"
            checked = st.checkbox(label, key=f"exc_{i}", value=True)
            if checked:
                final_exclusions.append(text)

        if any(is_ai for _, is_ai in unified_inc + unified_exc):
            st.caption("🤖 = AI-inferred item (not explicitly stated in the quote)")

        # ════════════════════════════════════════════════════════════════
        # STEP 4 — Generate
        # ════════════════════════════════════════════════════════════════
        st.markdown("---")
        st.markdown("""
        <div class="step-header">
            <div class="step-num navy">4</div>
            <p class="step-title">Generate MSAPO Document</p>
        </div>
        """, unsafe_allow_html=True)

        if st.button(
            "Generate MSAPO Files",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner("Generating MSAPO document..."):
                try:
                    docx_path = generate_docx(
                        analysis,
                        final_inclusions=final_inclusions,
                        final_exclusions=final_exclusions,
                    )
                    st.session_state["docx_path"] = docx_path
                except Exception as e:
                    st.error(f"Document generation failed: {e}")
                    st.stop()

            with st.spinner("Converting to PDF..."):
                try:
                    pdf_path = convert_to_pdf(docx_path)
                    st.session_state["pdf_path"] = pdf_path
                except PDFConversionError as e:
                    st.warning(
                        f"PDF conversion unavailable: {e}. "
                        "The .docx file is still ready for download."
                    )
                    st.session_state["pdf_path"] = None

            st.markdown("""
            <div class="alert-box alert-success">
                <span class="alert-icon">🎉</span>
                <div><strong>Success!</strong> Your MSAPO document is ready for download.</div>
            </div>
            """, unsafe_allow_html=True)

        # ── Download Area ────────────────────────────────────────────
        docx_path: Path | None = st.session_state.get("docx_path")
        pdf_path: Path | None = st.session_state.get("pdf_path")

        if docx_path or pdf_path:
            st.markdown("""
            <div class="download-section">
                <div class="download-title">
                    <span class="dl-icon">📥</span>
                    Download your generated files
                </div>
            </div>
            """, unsafe_allow_html=True)

            dl_col1, dl_col2 = st.columns(2)

            if docx_path and docx_path.exists():
                with dl_col1:
                    st.download_button(
                        label="📄  Download .docx",
                        data=docx_path.read_bytes(),
                        file_name=docx_path.name,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True,
                    )

            if pdf_path and pdf_path.exists():
                with dl_col2:
                    st.download_button(
                        label="📕  Download .pdf",
                        data=pdf_path.read_bytes(),
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        use_container_width=True,
                    )

        # ════════════════════════════════════════════════════════════════
        # STEP — Email to David
        # ════════════════════════════════════════════════════════════════
        if docx_path and docx_path.exists():
            st.markdown("---")
            st.markdown("""
            <div class="step-header">
                <div class="step-num orange">5</div>
                <p class="step-title">Email to David</p>
            </div>
            """, unsafe_allow_html=True)

            # ── Resolve facility key and default short name ───────
            fac_key = facility_key_from_name(analysis.facility_name)
            default_short = FACILITY_SHORT_NAMES.get(fac_key, "") if fac_key else ""

            # ── Work categories valid for this site ───────────────
            valid_cats = valid_categories_for_site(fac_key)
            cat_display = [WORK_CATEGORY_DISPLAY.get(c, c) for c in valid_cats]

            # Default work_category index
            default_cat_idx = 0
            if analysis.work_category and analysis.work_category in valid_cats:
                default_cat_idx = valid_cats.index(analysis.work_category)

            # ── Editable fields ──────────────────────────────────
            ecol1, ecol2 = st.columns(2)
            with ecol1:
                email_site = st.text_input(
                    "Site Short Name",
                    value=default_short,
                    key="email_site",
                    placeholder="e.g. UMMC",
                )
                email_desc = st.text_input(
                    "Description (max 20 chars)",
                    value=(analysis.short_description or "")[:20],
                    max_chars=20,
                    key="email_desc",
                )
                email_contact = st.text_input(
                    "Contact Name",
                    value=analysis.contact_name or "",
                    key="email_contact",
                )

            with ecol2:
                if fac_key and fac_key in FACILITY_SHORT_NAMES:
                    selected_cat_display = st.selectbox(
                        "Work Category",
                        cat_display,
                        index=default_cat_idx,
                        key="email_cat",
                    )
                    selected_cat_key = valid_cats[cat_display.index(selected_cat_display)]
                    cost_code = lookup_cost_code(fac_key, selected_cat_key) or ""
                    st.markdown(f"""
                    <div style="margin-bottom:1rem;">
                        <label style="font-size:0.85rem; font-weight:600; color:#0F172A;">
                            Job Cost Code
                        </label>
                        <div style="
                            background:#F1F5F9; border:1px solid #E2E8F0;
                            border-radius:8px; padding:0.5rem 0.85rem;
                            font-size:1rem; font-weight:700; color:#1B3A5C;
                            margin-top:0.25rem;
                        ">{cost_code or '—'}</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    selected_cat_key = None
                    cost_code = st.text_input(
                        "Job Cost Code",
                        value="",
                        key="email_cost_code_manual",
                        placeholder="e.g. 01CEABA",
                    )

                email_amount = st.text_input(
                    "Total Amount",
                    value=analysis.total_amount or "",
                    key="email_amount",
                )
                email_contact_email = st.text_input(
                    "Contact Email",
                    value=analysis.contact_email or "",
                    key="email_contact_email",
                )

            # ── Build subject line ────────────────────────────────
            subject = f"{analysis.vendor_name or 'Vendor'} {email_desc} at {email_site} MSA PO".strip()

            # ── Email preview ─────────────────────────────────────
            with st.expander("Preview email", expanded=False):
                st.markdown(f"**To:** david.siegal@enfrasolutions.com")
                st.markdown(f"**Subject:** {subject}")
                st.markdown("---")
                st.markdown(
                    f"Good afternoon, David. Please see below.\n\n"
                    f"- **Site Location:**\n"
                    f"   - RRH {email_site}\n"
                    f"- **Job cost code:**\n"
                    f"   - {cost_code}\n"
                    f"- **Subcontractor name:**\n"
                    f"   - {analysis.vendor_name or ''}\n"
                    f"- **Contact Name:**\n"
                    f"   - {email_contact}\n"
                    f"- **Contact Email:**\n"
                    f"   - {email_contact_email}\n"
                    f"- **Description:**\n"
                    f"   - {email_desc}\n"
                    f"- **Amount:**\n"
                    f"   - {email_amount}\n\n"
                    f"*Your Outlook signature will be added automatically.*"
                )

            # ── Collect attachments ───────────────────────────────
            attachments: list[tuple[str, bytes]] = []
            uploaded_bytes = st.session_state.get("uploaded_file_bytes")
            uploaded_name = st.session_state.get("uploaded_file_name")
            if uploaded_bytes and uploaded_name:
                attachments.append((uploaded_name, uploaded_bytes))
            if docx_path and docx_path.exists():
                attachments.append((docx_path.name, docx_path.read_bytes()))
            if pdf_path and pdf_path.exists():
                attachments.append((pdf_path.name, pdf_path.read_bytes()))

            # ── Build the .eml (opens as draft in desktop Outlook) ─
            eml_bytes = build_eml(
                subject=subject,
                site_short_name=email_site,
                cost_code=cost_code,
                vendor_name=analysis.vendor_name or "",
                contact_name=email_contact,
                contact_email=email_contact_email,
                description=email_desc,
                amount=email_amount,
                attachments=attachments,
            )

            # ── Device-appropriate send flow ──────────────────────
            apple_mobile = st.toggle(
                "📱 I'm on an iPhone or iPad",
                value=_detect_apple_mobile(),
                key="apple_mobile",
                help="iPad Safari often identifies itself as a Mac — turn this "
                     "on manually if the Apple Mail flow doesn't appear.",
            )

            if apple_mobile:
                plain_body = build_plain_body(
                    site_short_name=email_site,
                    cost_code=cost_code,
                    vendor_name=analysis.vendor_name or "",
                    contact_name=email_contact,
                    contact_email=email_contact_email,
                    description=email_desc,
                    amount=email_amount,
                )
                mailto_url = build_mailto_url(subject=subject, body=plain_body)

                st.markdown("**Subject** — tap the copy icon, you'll paste it in Mail:")
                st.code(subject, language=None)
                st.markdown("**To:**")
                st.code(DAVID_EMAIL, language=None)

                _render_apple_mail_share(subject, plain_body, attachments)

                st.markdown(
                    f'<a href="{mailto_url}" style="display:block; text-align:center; '
                    f'color:#1B3A5C; font-size:14px; margin-top:4px;">'
                    f'✉️ Or open a pre-filled draft in Apple Mail (without attachments)</a>',
                    unsafe_allow_html=True,
                )

                with st.expander("Using Outlook on this device instead?"):
                    st.download_button(
                        label="📧  Download Email (.eml for Outlook)",
                        data=eml_bytes,
                        file_name=f"{subject}.eml",
                        mime="message/rfc822",
                        use_container_width=True,
                    )
            else:
                st.download_button(
                    label="📧  Download Email — Open in Outlook & Hit Send",
                    data=eml_bytes,
                    file_name=f"{subject}.eml",
                    mime="message/rfc822",
                    use_container_width=True,
                )
                st.caption("Double-click the downloaded .eml to open it in Outlook as a **draft** "
                           "with the Send button ready. All 3 attachments are already included.")

    # ── Footer ──────────────────────────────────────────────────────
    st.markdown("""
    <div class="app-footer">
        <div class="footer-divider"></div>
        Built by <a href="mailto:evan.roden@ENFRAsolutions.com">Evan Roden</a>
        &nbsp;&bull;&nbsp; evan.roden@ENFRAsolutions.com
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
