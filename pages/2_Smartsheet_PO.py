"""Future ENFRA Smartsheet PO handoff.

The page shares session state with Email Process Control, but isolates every
widget and result by a verified PO context ID. Existing workflow values are
read-only here; corrections that affect the document must be made in the source
workflow and regenerated before submission.
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
    missing_required_fields,
    preflight_attachments,
    prefill_enabled,
    reconcile_submission,
    submit_po,
    validate_column_mapping,
    validate_submission_fields,
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
    "form URL prefilling, or direct API submission. All routes are off until configured."
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

# A new quote must never inherit another quote's widget values or API result.
previous_context = st.session_state.get("_smartsheet_context_id")
if previous_context != context.context_id:
    for state_key in list(st.session_state.keys()):
        if state_key.startswith("ssw_"):
            del st.session_state[state_key]
    st.session_state["_smartsheet_context_id"] = context.context_id
prefix = f"ssw_{context.context_id}_"

if context.warnings:
    st.error(
        "Return to Email Process Control and resolve these source-record problems "
        "before API submission:\n\n- " + "\n- ".join(context.warnings)
    )

fields = dict(context.fields)


def locked_text(label: str, field: str) -> str:
    value = fields.get(field, "")
    st.text_input(label, value=value, disabled=True, key=f"{prefix}{field}")
    return value


def locked_area(label: str, field: str, height: int) -> str:
    value = fields.get(field, "")
    st.text_area(
        label,
        value=value,
        height=height,
        disabled=True,
        key=f"{prefix}{field}",
    )
    return value


st.subheader("1. Verify the source record")
st.caption(
    "Fields already reviewed in Email Process Control are locked here. Change them "
    "there and regenerate the MSAPO so the form and attachments cannot diverge."
)
left, right = st.columns(2)
with left:
    fields["requester_name"] = st.text_input(
        "Name of person completing form",
        value=fields.get("requester_name", ""),
        key=f"{prefix}requester_name",
    )
    locked_text("PO type", "order_type")
    locked_text("Contract", "contract")
    locked_text("Site", "site")
    fields["facility_address"] = st.text_area(
        "Address/location",
        value=fields.get("facility_address", ""),
        height=90,
        key=f"{prefix}facility_address",
    )
    locked_text("Work category", "work_category")
    locked_text("Job cost code", "cost_code")
    locked_text("ENFRA Unique Identifier", "asset_id")

with right:
    locked_text("Subcontractor/vendor", "vendor")
    locked_text("Vendor contact name", "contact_name")
    locked_text("Vendor contact email", "contact_email")
    locked_text("Contract administrator email", "administrator_email")
    locked_text("Short description", "description")
    locked_text("Subtotal", "subtotal")
    locked_text("Sales tax", "tax")
    locked_text("Total amount", "total")
    locked_text("Tax status", "tax_status")

locked_area("Reviewed description of work / scope", "scope_of_work", 220)
fields["instructions"] = st.text_area(
    "Additional instructions",
    value=fields.get("instructions", ""),
    height=100,
    key=f"{prefix}instructions",
)

with st.expander("Fields that depend on the final ENFRA form", expanded=True):
    st.caption(
        "These stay blank until a person supplies them. The application does not infer "
        "billing, scheduling, customer, or staffing decisions."
    )
    future_left, future_right = st.columns(2)
    yes_no = ["", "Yes", "No"]
    with future_left:
        fields["related_to_om"] = st.selectbox(
            "Related to Asset Management O&M Agreement?",
            yes_no,
            key=f"{prefix}related_to_om",
        )
        fields["billing_method"] = st.text_input(
            "Billing method", key=f"{prefix}billing_method"
        )
        fields["customer_po"] = st.text_input(
            "Customer purchase order", key=f"{prefix}customer_po"
        )
        fields["estimated_start_date"] = st.text_input(
            "Estimated start date (MM/DD/YYYY)", key=f"{prefix}start_date"
        )
        fields["estimated_completion_date"] = st.text_input(
            "Estimated completion date (MM/DD/YYYY)", key=f"{prefix}completion_date"
        )
    with future_right:
        fields["customer_representative"] = st.text_input(
            "Customer representative requesting service",
            key=f"{prefix}customer_representative",
        )
        fields["service_branch_tech_needed"] = st.selectbox(
            "Service branch technician needed?",
            yes_no,
            key=f"{prefix}service_branch_tech_needed",
        )
        fields["send_copy_email"] = st.selectbox(
            "Send me a copy of my responses?",
            yes_no,
            key=f"{prefix}send_copy_email",
        )

field_problems = list(validate_submission_fields(fields))
attachment_problems = list(preflight_attachments(context.attachments))
if field_problems or attachment_problems:
    st.warning(
        "Current submission preflight:\n\n- "
        + "\n- ".join(field_problems + attachment_problems)
    )

st.subheader("2. Files")
renamed_files = download_names(context.attachments, context.attachment_base)
if not renamed_files:
    st.error("No verified attachments are available.")
else:
    cols = st.columns(min(3, len(renamed_files)))
    for index, (label, filename, data) in enumerate(renamed_files):
        cols[index % len(cols)].download_button(
            label,
            data=data,
            file_name=filename,
            mime=mimetypes.guess_type(filename)[0] or "application/octet-stream",
            key=f"{prefix}download_{index}",
            use_container_width=True,
        )
    st.caption(
        "The vendor quote bytes are unchanged. The downloads share a safe prefix so "
        "they appear together in the file picker."
    )

st.subheader("3. Use the route ENFRA permits")
manual_tab, prefill_tab, api_tab = st.tabs(
    ["Manual copy/paste", "URL prefill", "API submission"]
)

with manual_tab:
    if not manual_enabled(config):
        st.info(
            "Manual mode appears after SMARTSHEET_FORM_URL is configured. It needs no API token."
        )
    else:
        missing_form = missing_required_fields(fields, config.form_required_fields)
        if missing_form:
            st.error(
                "Complete these confirmed form-required fields first: "
                + ", ".join(missing_form)
            )
        rows = handoff_rows(fields, config)
        if rows:
            render_manual_handoff(
                rows,
                config.form_url or "",
                key=f"{context.context_id}-manual",
            )
        else:
            st.warning("No populated fields are available to copy.")

with prefill_tab:
    if not config.form_url:
        st.info("Configure SMARTSHEET_FORM_URL first.")
    elif not prefill_enabled(config):
        st.info(
            "URL prefill remains disabled until the final form is tested and exact "
            "field labels are configured."
        )
    else:
        try:
            prefilled = build_prefilled_form_url(fields, config)
            if prefilled.missing_required:
                st.error(
                    "Complete these form-required fields before opening the prefilled form: "
                    + ", ".join(prefilled.missing_required)
                )
            else:
                st.link_button(
                    "Open prefilled Smartsheet form ↗",
                    prefilled.url,
                    use_container_width=True,
                )
                st.success(f"Prepared {len(prefilled.included)} prefilled field(s).")
            if prefilled.skipped:
                st.caption("Not included in the URL: " + "; ".join(prefilled.skipped))
            st.warning(
                "A form URL cannot carry the quote or MSAPO files. Attach the verified downloads above."
            )
        except SmartsheetConfigurationError as exc:
            st.error(str(exc))

with api_tab:
    readiness = api_readiness(config)
    st.markdown(f"**Mode:** `{readiness.mode}`")
    for problem in readiness.problems:
        st.caption(f"• {problem}")

    mapping_key = f"{prefix}mapping_result"
    result_key = f"{prefix}submit_result"

    if config.api_mode == "disabled":
        st.info(
            "API submission is disabled by default. Manual and URL modes remain independent."
        )
    else:
        if st.button("Validate live sheet configuration", key=f"{prefix}validate_mapping"):
            with st.spinner("Checking exact column IDs, titles, types, options, and writability…"):
                st.session_state[mapping_key] = validate_column_mapping(config)

        mapping_result = st.session_state.get(mapping_key)
        if mapping_result:
            if mapping_result.get("ok"):
                st.success("Every configured column matches the live sheet specification.")
                for logical, column in mapping_result.get("mapped", {}).items():
                    st.caption(
                        f"• {logical}: {column.get('title')} "
                        f"({column.get('type')}, {column.get('id')})"
                    )
            else:
                st.error(
                    "Column validation failed: "
                    + "; ".join(map(str, mapping_result.get("problems", [])))
                )

        if config.api_mode == "dry_run":
            st.info(
                "Dry-run mode validates credentials and schema but cannot create a row."
            )
        elif config.api_mode == "live":
            missing_api = list(missing_required_fields(fields, config.required_fields))
            blockers = list(context.warnings) + field_problems + attachment_problems
            if missing_api:
                blockers.append("Required API values are missing: " + ", ".join(missing_api))
            blockers.extend(readiness.problems)
            submit_disabled = bool(blockers)
            if blockers:
                st.error("API submission is blocked:\n\n- " + "\n- ".join(blockers))

            if st.button(
                "Submit PO to Smartsheet",
                type="primary",
                use_container_width=True,
                disabled=submit_disabled,
                key=f"{prefix}submit_live",
            ):
                with st.spinner("Creating or safely resuming the Smartsheet row…"):
                    st.session_state[result_key] = submit_po(
                        fields,
                        context.attachments,
                        config=config,
                    )

            result = st.session_state.get(result_key)
            if result:
                if result.get("ok"):
                    if result.get("duplicate"):
                        st.success(
                            f"This exact PO already exists as row {result.get('row_id')}; "
                            "no duplicate row was created."
                        )
                    elif result.get("partial"):
                        st.warning(
                            f"Row {result.get('row_id')} exists, but one or more "
                            "attachments need a safe retry."
                        )
                    else:
                        st.success(
                            f"Submitted as row {result.get('row_id')} with "
                            f"{result.get('attached', 0)} verified attachment(s)."
                        )
                    for skipped in result.get("skipped_attachments", []):
                        st.caption(f"• {skipped}")
                else:
                    st.error(result.get("error", "Smartsheet submission failed."))
                    for problem in result.get("problems", []):
                        st.caption(f"• {problem}")
                    if result.get("uncertain"):
                        st.warning(
                            "Do not press Submit again. Smartsheet may already contain the row. "
                            "Use exact-key reconciliation below."
                        )
                        if st.button(
                            "Search Smartsheet for the exact submission key",
                            key=f"{prefix}reconcile",
                            use_container_width=True,
                        ):
                            with st.spinner("Searching and verifying the submission-key cell…"):
                                reconciliation = reconcile_submission(
                                    fields,
                                    context.attachments,
                                    config=config,
                                )
                            if reconciliation.get("ok"):
                                st.success(
                                    f"Reconciled to row {reconciliation.get('row_id')}. "
                                    "You may now submit again to resume attachments."
                                )
                                st.session_state.pop(result_key, None)
                            else:
                                st.error(reconciliation.get("error", "Reconciliation failed."))

st.divider()
st.caption(
    "The example ENFRA work-order form informs the field model but is not treated "
    "as the final PO schema. Activation still requires the final form/sheet and a controlled live test."
)
