from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}, found {count}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_web_ui() -> None:
    path = "app/web_ui.py"

    replace_once(
        path,
        '''Drop in a vendor quote and the app extracts the details, builds the MSAPO
document (or skips it for equipment-only POs), and hands you a ready-to-send
email to David — pre-filled for Outlook on desktop and Apple Mail on an
iPhone/iPad, detected automatically.''',
        '''Drop in a vendor quote and the app extracts the details, builds the MSAPO
document (or skips it for equipment-only POs), and hands you a ready-to-send
administrator email — pre-filled for Outlook on desktop and Apple Mail on an
iPhone/iPad, detected automatically.''',
    )

    replace_once(
        path,
        "from __future__ import annotations\n\nimport base64",
        "from __future__ import annotations\n\nfrom decimal import Decimal, InvalidOperation\n\nimport base64",
    )

    replace_once(
        path,
        '''from app.config import (
    FACILITY_SHORT_NAMES,
    WORK_CATEGORY_DISPLAY,''',
        '''from app.config import (
    FACILITIES,
    FACILITY_SHORT_NAMES,
    WORK_CATEGORY_DISPLAY,''',
    )

    replace_once(
        path,
        '''SITE_LABEL_TO_KEY = {label: key for key, label in FACILITY_SHORT_NAMES.items()}
SITE_LABELS = list(FACILITY_SHORT_NAMES.values())''',
        '''SITE_LABEL_TO_KEY = {label: key for key, label in FACILITY_SHORT_NAMES.items()}
SITE_LABELS = list(FACILITY_SHORT_NAMES.values())
CONTRACT_PLACEHOLDER = "— Select a contract —"
SITE_PLACEHOLDER = "— Select a site —"''',
    )

    replace_once(
        path,
        '''def _has_breakdown(subtotal: str, tax: str) -> bool:
    """Show subtotal + tax bullets only when the quote itemized both."""
    return bool(subtotal and subtotal.strip()) and bool(tax and tax.strip())


def _doc_basename''',
        '''def _has_breakdown(subtotal: str, tax: str) -> bool:
    """Show subtotal + tax bullets only when the quote itemized both."""
    return bool(subtotal and subtotal.strip()) and bool(tax and tax.strip())


def _parse_amount(value: str | None) -> Decimal | None:
    """Parse a displayed US-dollar amount without changing the user's text."""
    if not value or not value.strip():
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", value)
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


def _doc_basename''',
    )

    replace_once(
        path,
        '''            Drop in a vendor quote and get a tidy, ready-to-send email to David —
            MSAPO paperwork built, pricing tallied, the right cost code picked.
            No fuss.''',
        '''            Drop in a vendor quote and get a tidy, ready-to-send administrator email —
            MSAPO paperwork built, pricing tallied, the right contract and cost code confirmed.
            No fuss.''',
    )

    replace_once(
        path,
        '''        if st.button("🛠️  Generate MSAPO files", type="primary", use_container_width=True):
            # Show the recognized (canonical) site in the document for non-RRH
            # contracts, whose facility names the analyzer doesn't normalize.
            _dc, _ds = contracts.match_facility(analysis.facility_name, quote_text_cached)
            facility_display = _ds if (_dc and not contracts.is_rrh(_dc)) else None
            with st.spinner("Assembling the MSAPO document…"):
                try:
                    docx_path = generate_docx(
                        analysis,
                        final_inclusions=final_inclusions,
                        final_exclusions=final_exclusions,
                        facility_display=facility_display,
                    )
                    st.session_state["docx_path"] = docx_path
                except Exception as e:
                    st.error(f"Document generation failed: {e}")
                    st.stop()''',
        '''        if st.button("🛠️  Generate MSAPO files", type="primary", use_container_width=True):
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
                    st.stop()''',
    )

    replace_once(
        path,
        '''    # STEP 4 — Email to David''',
        '''    # STEP 4 — Confirm routing and send the email''',
    )

    replace_once(
        path,
        '''    # ── Contract → recipient ────────────────────────────────────────
    # Recognize the facility from the quote and default the contract/site to it;
    # falls back to RRH when nothing is recognized (protecting the RRH default).
    det_contract, det_site = contracts.match_facility(analysis.facility_name, quote_text_cached)
    crow = st.columns([1, 1])
    with crow[0]:
        _cnames = contracts.contract_names()
        _cidx = _cnames.index(det_contract) if det_contract in _cnames else 0
        contract = st.selectbox("Contract", _cnames, index=_cidx, key=f"contract_{tok}")
        if det_contract and not contracts.is_rrh(det_contract) and contract == det_contract:
            st.caption(f"↳ Recognized from the quote: **{det_site or det_contract}**")
    rrh = contracts.is_rrh(contract)''',
        '''    # ── Contract → recipient ────────────────────────────────────────
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
    rrh = contracts.is_rrh(contract)''',
    )

    replace_once(
        path,
        '''    row1 = st.columns([1, 1, 1])
    if rrh:
        # ── RRH — dedicated flow: short site names + autofilled cost code ──
        fac_key = facility_key_from_name(analysis.facility_name)
        default_site_label = FACILITY_SHORT_NAMES.get(fac_key) if fac_key else None
        default_site_idx = SITE_LABELS.index(default_site_label) if default_site_label in SITE_LABELS else 0
        with row1[0]:
            site_label = st.selectbox("Site", SITE_LABELS, index=default_site_idx, key=f"site_{tok}")
        sel_key = SITE_LABEL_TO_KEY[site_label]
        valid_cats = valid_categories_for_site(sel_key)
        cat_labels = [WORK_CATEGORY_DISPLAY.get(c, c) for c in valid_cats]
        default_cat_idx = valid_cats.index(analysis.work_category) if analysis.work_category in valid_cats else 0
        with row1[1]:
            cat_label = st.selectbox("Work category", cat_labels, index=default_cat_idx, key=f"cat_{tok}_{sel_key}")
        sel_cat = valid_cats[cat_labels.index(cat_label)]
        cost_code = lookup_cost_code(sel_key, sel_cat) or ""
        with row1[2]:
            st.markdown('<div class="field-label">Job cost code</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="cost-code-pill">🏷️ {cost_code or "—"}</div>', unsafe_allow_html=True)
        site_line = f"RRH {site_label}"
    else:
        # ── Generic contract — dependent site dropdown + free-text cost code ──
        sites = contracts.sites_for_contract(contract)
        # Default to the recognized site when it belongs to the chosen contract.
        _sidx = sites.index(det_site) if (contract == det_contract and det_site in sites) else 0
        with row1[0]:
            if sites:
                site_label = st.selectbox("Site", sites, index=_sidx, key=f"gsite_{tok}_{contract}")
            else:
                site_label = st.text_input("Site", value="", key=f"gsitetxt_{tok}_{contract}")
        with row1[1]:
            cat_label = st.text_input("Work category", value="",
                                      key=f"gcat_{tok}_{contract}", placeholder="e.g. Chiller repair")
        with row1[2]:
            cost_code = st.text_input("Job cost code", value="",
                                      key=f"gcost_{tok}_{contract}", placeholder="Paste the cost code")
        site_line = site_label''',
        '''    row1 = st.columns([1, 1, 1])
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
            return''',
    )

    replace_once(
        path,
        '''    vendor = analysis.vendor_name or "Vendor"
    breakdown = _has_breakdown(subtotal_val, tax_val)

    # ── Assemble bullets + subject per order type ───────────────────''',
        '''    vendor = analysis.vendor_name or "Vendor"
    breakdown = _has_breakdown(subtotal_val, tax_val)
    pricing_difference = _pricing_difference(subtotal_val, tax_val, total_val)
    if breakdown and pricing_difference is not None and abs(pricing_difference) > Decimal("0.01"):
        st.warning(
            "Subtotal plus sales tax does not equal the total. Confirm the quote "
            "amounts before sending."
        )

    # ── Assemble bullets + subject per order type ───────────────────''',
    )


def patch_document_generator() -> None:
    path = "app/document_generator.py"

    replace_once(
        path,
        '''    final_exclusions: list[str] | None = None,
    facility_display: str | None = None,
) -> None:''',
        '''    final_exclusions: list[str] | None = None,
    facility_display: str | None = None,
    facility_address_display: str | None = None,
) -> None:''',
    )

    replace_once(
        path,
        '''    facility_display, when given, overrides the facility name written into the
    document — used to show the recognized canonical site for non-RRH contracts
    (whose facilities the analyzer doesn't otherwise normalize).''',
        '''    facility_display and facility_address_display, when given, override the
    facility values written into the document. This ensures a user's corrected
    routing choice is reflected in the attachment rather than only its filename.''',
    )

    replace_once(
        path,
        '''        run.font.size = Pt(11)
        doc.add_paragraph(analysis.facility_address or "")''',
        '''        run.font.size = Pt(11)
        address = (
            analysis.facility_address
            if facility_address_display is None
            else facility_address_display
        )
        doc.add_paragraph(address or "")''',
    )

    replace_once(
        path,
        '''    final_exclusions: list[str] | None = None,
    facility_display: str | None = None,
) -> Path:''',
        '''    final_exclusions: list[str] | None = None,
    facility_display: str | None = None,
    facility_address_display: str | None = None,
) -> Path:''',
    )

    replace_once(
        path,
        '''        final_exclusions=final_exclusions,
        facility_display=facility_display,
    )''',
        '''        final_exclusions=final_exclusions,
        facility_display=facility_display,
        facility_address_display=facility_address_display,
    )''',
    )


def patch_config() -> None:
    path = "app/config.py"

    replace_once(
        path,
        '''    "unity": "Unity",
    "st_marys": "St. Mary's",''',
        '''    "unity": "Unity",
    "unity_specialty": "Unity Specialty",
    "st_marys": "St. Mary's",''',
    )

    replace_once(
        path,
        '''    "unity": _FULL,
    "st_marys": _FULL,''',
        '''    "unity": _FULL,
    # The facility is real and selectable, but no automatic cost-code letter is
    # configured. The UI therefore requires a manual cost code for this site.
    "unity_specialty": _NO_SOFTENER,
    "st_marys": _FULL,''',
    )


def patch_quote_analyzer() -> None:
    path = "app/quote_analyzer.py"

    replace_once(
        path,
        '''You are an expert construction and facilities project analyst working for a \
healthcare system. Your job is to read a vendor quote and extract structured \
data so that a Scope of Work (MSAPO agreement) can be generated.''',
        '''You are an expert construction and facilities project analyst supporting \
multiple facilities-management contracts. Your job is to read a vendor quote \
and extract structured data so that a Scope of Work (MSAPO agreement) can be generated.''',
    )

    replace_once(
        path,
        '''   - Unity Hospital, 1555 Long Pond Rd, Rochester, NY 14626
   - St. Mary's Medical Campus, 89 Genesee St, Rochester, NY 14611''',
        '''   - Unity Hospital, 1555 Long Pond Rd, Rochester, NY 14626
   - Unity Specialty Hospital, 89 Genesee St, Rochester, NY 14611
   - St. Mary's Medical Campus, 89 Genesee St, Rochester, NY 14611''',
    )

    replace_once(
        path,
        '''   - Massena Hospital, 1 Hospital Dr, Massena, NY 13662
   - Clifton Springs Hospital & Clinic, 2 Coulter Rd, Clifton Springs, NY 14432
   If none match,''',
        '''   - Massena Hospital, 1 Hospital Dr, Massena, NY 13662
   If none match,''',
    )


def cleanup_scaffold() -> None:
    Path("scripts/apply_workflow_correctness.py").unlink(missing_ok=True)
    Path(".github/workflows/apply-workflow-correctness.yml").unlink(missing_ok=True)


if __name__ == "__main__":
    patch_web_ui()
    patch_document_generator()
    patch_config()
    patch_quote_analyzer()
    cleanup_scaffold()
