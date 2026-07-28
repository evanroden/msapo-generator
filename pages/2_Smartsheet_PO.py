"""Future ENFRA Smartsheet PO handoff.

This page is intentionally configuration-driven and inert until a form URL or
verified API configuration exists. It shares Streamlit session state with the
current quote/email workflow.
"""

from __future__ import annotations

import mimetypes

import streamlit as st

from app.po_context import build_po_context
from app.smartsheet import (
    SmartsheetConfigurationError,
    api_readiness,
    build_prefilled_form_url,
    download_names,
    handoff_rows,
    load_config,
    manual_enabled,
    prefill_enabled,
    submit_po,
    validate_column_mapping,
)
from app.smartsheet_ui import render_manual_handoff


st.set_page_config(
    page_title="Smartsheet PO Handoff",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {max-width: 1050px; padding-top: 1.4rem;}
      .ss-card {background:#fff;border:1px solid #E2E8F0;border-radius:14px;padding:1rem 1.1rem;margin:.5rem 0;}
      .ss-title {font-weight:800;color:#12233B;font-size:1.05rem;}
      .ss-muted {color:#64748B;font-size:.86rem;line-height:1.45;}
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    st.page_link("run_web.py", label="← Back to Email Process Control", icon="📮")
except Exception:
    st.caption("Return to the main Email Process Control page to revise the quote.")

st.title("📋 Smartsheet PO Handoff")
st.caption(
    "Prepared for three possible ENFRA workflows: manual copy/paste, exact-label "
    "form URL prefilling, or direct API submission."
)

try:
    config = load_config()
except SmartsheetConfigurationError as exc:
    st.error(f"Smartsheet configuration error: {exc}")
    st.stop()

context = build_po_context(st.session_state)
if context is None:
    st.info(
        "Analyze a vendor quote in Email Process Control first. This page will then "
        "reuse the finalized PO details and attachments."
    )
    st.stop()

if context.warnings:
    st.warning("Review before submission:\n\n- " + "\n- ".join(context.warnings))

fields = dict(context.fields)

st.subheader("1. Confirm the submission record")
left, right = st.columns(2)
with left:
    fields["requester_name"] = st.text_input(
        "Name of person completing form",
        value=fields.get("requester_name", ""),
        key="ss_requester_name",
    )
    fields["order_type"] = st.selectbox(
        "PO type",
        ["MSAPO", "Equipment-only PO"],
        index=1 if fields.get("order_type") == "Equipment-only PO" else 0,
        key="ss_order_type",
    )
    fields["contract"] = st.text_input(
        "Contract", value=fields.get("contract", ""), key="ss_contract"
    )
    fields["site"] = st.text_input(
        "Site", value=fields.get("site", ""), key="ss_site"
    )
    fields["facility_address"] = st.text_area(
        "Address/location",
        value=fields.get("facility_address", ""),
        height=90,
        key="ss_facility_address",
    )
    fields["work_category"] = st.text_input(
        "Work category",
        value=fields.get("work_category", ""),
        key="ss_work_category",
    )
    fields["cost_code"] = st.text_input(
        "Job cost code", value=fields.get("cost_code", ""), key="ss_cost_code"
    )
    fields["asset_id"] = st.text_input(
        "ENFRA Unique Identifier",
        value=fields.get("asset_id", ""),
        key="ss_asset_id",
    )

with right:
    fields["vendor"] = st.text_input(
        "Subcontractor/vendor", value=fields.get("vendor", ""), key="ss_vendor"
    )
    fields["contact_name"] = st.text_input(
        "Vendor contact name",
        value=fields.get("contact_name", ""),
        key="ss_contact_name",
    )
    fields["contact_email"] = st.text_input(
        "Vendor contact email",
        value=fields.get("contact_email", ""),
        key="ss_contact_email",
    )
    fields["administrator_email"] = st.text_input(
        "Contract administrator email",
        value=fields.get("administrator_email", ""),
        key="ss_administrator_email",
    )
    fields["description"] = st.text_input(
        "Short description",
        value=fields.get("description", ""),
        max_chars=20,
        key="ss_description",
    )
    fields["subtotal"] = st.text_input(
        "Subtotal", value=fields.get("subtotal", ""), key="ss_subtotal"
    )
    fields["tax"] = st.text_input(
        "Sales tax", value=fields.get("tax", ""), key="ss_tax"
    )
    fields["total"] = st.text_input(
        "Total amount", value=fields.get("total", ""), key="ss_total"
    )
    tax_options = ["", "included", "excluded", "unclear"]
    current_tax = fields.get("tax_status", "")
    fields["tax_status"] = st.selectbox(
        "Tax status",
        tax_options,
        index=tax_options.index(current_tax) if current_tax in tax_options else 0,
        key="ss_tax_status",
    )

fields["scope_of_work"] = st.text_area(
    "Description of work / scope",
    value=fields.get("scope_of_work", ""),
    height=190,
    key="ss_scope_of_work",
)
fields["instructions"] = st.text_area(
    "Additional instructions",
    value=fields.get("instructions", ""),
    height=100,
    key="ss_instructions",
)

with st.expander("Fields that depend on the final ENFRA form", expanded=False):
    st.caption(
        "These are deliberately blank unless a person supplies them. Email Process "
        "Control does not infer scheduling, billing, customer, or staffing decisions."
    )
    future_left, future_right = st.columns(2)
    with future_left:
        yn = ["", "Yes", "No"]
        fields["related_to_om"] = st.selectbox(
            "Related to Asset Management O&M Agreement?",
            yn,
            key="ss_related_to_om",
        )
        fields["billing_method"] = st.text_input(
            "Billing method", key="ss_billing_method"
        )
        fields["customer_po"] = st.text_input(
            "Customer purchase order", key="ss_customer_po"
        )
        fields["estimated_start_date"] = st.text_input(
            "Estimated start date (MM/DD/YYYY)", key="ss_start_date"
        )
        fields["estimated_completion_date"] = st.text_input(
            "Estimated completion date (MM/DD/YYYY)", key="ss_completion_date"
        )
    with future_right:
        fields["customer_representative"] = st.text_input(
            "Customer representative requesting service",
            key="ss_customer_representative",
        )
        fields["service_branch_tech_needed"] = st.selectbox(
            "Service branch technician needed?",
            yn,
            key="ss_service_branch_tech_needed",
        )
        fields["send_copy_email"] = st.selectbox(
            "Send me a copy of my responses?",
            yn,
            key="ss_send_copy_email",
        )

st.subheader("2. Files")
renamed_files = download_names(context.attachments, context.attachment_base)
if not renamed_files:
    st.warning("No attachments are available.")
else:
    cols = st.columns(min(3, len(renamed_files)))
    for index, (label, filename, data) in enumerate(renamed_files):
        cols[index % len(cols)].download_button(
            label,
            data=data,
            file_name=filename,
            mime=mimetypes.guess_type(filename)[0] or "application/octet-stream",
            key=f"ss_download_{index}_{filename}",
            use_container_width=True,
        )
    st.caption(
        "The original vendor quote bytes are unchanged. Renamed downloads share a "
        "prefix so they appear together in the file picker."
    )

st.subheader("3. Choose the available Smartsheet route")
manual_tab, prefill_tab, api_tab = st.tabs(
    ["Manual copy/paste", "URL prefill", "API submission"]
)

with manual_tab:
    if not manual_enabled(config):
        st.info(
            "Manual mode will appear after SMARTSHEET_FORM_URL is configured. It "
            "requires no API access."
        )
    else:
        rows = handoff_rows(fields, config)
        if rows:
            render_manual_handoff(
                rows,
                config.form_url or "",
                key=f"{context.attachment_base}-manual",
            )
        else:
            st.warning("No populated fields are available to copy.")

with prefill_tab:
    if not config.form_url:
        st.info("Configure SMARTSHEET_FORM_URL first.")
    elif not prefill_enabled(config):
        st.info(
            "URL prefill stays disabled until the final form is tested and exact "
            "field labels are configured. Set SMARTSHEET_URL_PREFILL_ENABLED=true "
            "and SMARTSHEET_FORM_FIELD_MAP_JSON only after verification."
        )
    else:
        try:
            prefilled = build_prefilled_form_url(fields, config)
            st.link_button(
                "Open prefilled Smartsheet form ↗",
                prefilled.url,
                use_container_width=True,
            )
            st.success(f"Prepared {len(prefilled.included)} prefilled field(s).")
            if prefilled.skipped:
                st.caption(
                    "No exact form-label mapping for: " + ", ".join(prefilled.skipped)
                )
            st.warning(
                "Smartsheet form links cannot carry the quote or MSAPO files. "
                "Attach the downloads above before submitting."
            )
        except SmartsheetConfigurationError as exc:
            st.error(str(exc))

with api_tab:
    readiness = api_readiness(config)
    st.markdown(f"**Mode:** `{readiness.mode}`")
    if readiness.problems:
        for problem in readiness.problems:
            st.caption(f"• {problem}")

    if config.api_mode == "disabled":
        st.info(
            "API submission is disabled by default. The manual and URL routes can "
            "be used independently."
        )
    else:
        if st.button("Validate live sheet column IDs", key="ss_validate_mapping"):
            with st.spinner("Checking the configured sheet…"):
                mapping_result = validate_column_mapping(config)
            st.session_state["ss_mapping_result"] = mapping_result

        mapping_result = st.session_state.get("ss_mapping_result")
        if mapping_result:
            if mapping_result.get("ok"):
                st.success("Every configured column ID exists on the live sheet.")
                for logical, column in mapping_result.get("mapped", {}).items():
                    st.caption(
                        f"• {logical}: {column.get('title')} "
                        f"({column.get('type')}, {column.get('id')})"
                    )
            else:
                problems = mapping_result.get("problems") or mapping_result.get("missing") or []
                st.error("Column validation failed: " + ", ".join(map(str, problems)))

        if config.api_mode == "dry_run":
            st.info(
                "Dry-run mode validates credentials and explicit column IDs but "
                "cannot create a row."
            )
        elif readiness.ready:
            submit_disabled = bool(context.warnings)
            if submit_disabled:
                st.warning("Resolve the review warnings above before API submission.")
            if st.button(
                "Submit PO to Smartsheet",
                type="primary",
                use_container_width=True,
                disabled=submit_disabled,
                key="ss_submit_live",
            ):
                with st.spinner("Creating or safely resuming the Smartsheet row…"):
                    result = submit_po(
                        fields,
                        context.attachments,
                        config=config,
                    )
                st.session_state["ss_submit_result"] = result

            result = st.session_state.get("ss_submit_result")
            if result:
                if result.get("ok"):
                    if result.get("duplicate"):
                        st.success(
                            f"This PO was already submitted as row {result.get('row_id')}; "
                            "no duplicate row was created."
                        )
                    elif result.get("partial"):
                        st.warning(
                            f"Row {result.get('row_id')} exists, but one or more "
                            "attachments need a retry. Re-submit to resume the same row."
                        )
                    else:
                        st.success(
                            f"Submitted as Smartsheet row {result.get('row_id')} with "
                            f"{result.get('attached', 0)} attachment(s)."
                        )
                    for skipped in result.get("skipped_attachments", []):
                        st.caption(f"• {skipped}")
                else:
                    st.error(result.get("error", "Smartsheet submission failed."))
                    for problem in result.get("problems", []):
                        st.caption(f"• {problem}")

st.divider()
st.caption(
    "All three routes use the same reviewed PO record. Manual and URL modes never "
    "receive the Smartsheet API token; API mode requires explicit column IDs and "
    "persistent duplicate-prevention state."
)
