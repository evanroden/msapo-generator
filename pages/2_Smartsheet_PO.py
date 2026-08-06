"""ENFRA Smartsheet PO handoff.

The page shares session state with Email Process Control, but isolates every
widget and result by a verified PO context ID. Existing workflow values are
read-only here; corrections that affect the MSAPO must be made in the source
workflow and regenerated before any handoff route is enabled.
"""

from __future__ import annotations

import mimetypes

import streamlit as st

from app import contracts
from app.device_identity import device_token, ensure_device_cookie
from app.memory import (
    REQUESTER_SUGGEST_THRESHOLD,
    forget_device_requester,
    record_device_requester,
    remembered_device_requester,
)
from app.po_context import (
    POContext,
    PREPARED_PO_CONTEXT_STATE_KEY,
    build_po_context,
)
from app.smartsheet import (
    OBJECT_ACCOUNT_OPTIONS,
    RRH_JOB_NUMBERS,
    SmartsheetConfigurationError,
    api_readiness,
    build_prefilled_form_url,
    download_names,
    handoff_rows,
    load_config,
    manual_enabled,
    missing_required_fields,
    prefill_enabled,
    preflight_attachments,
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

try:
    st.page_link("run_web.py", label="← Back to Email Process Control", icon="📮")
except Exception:
    st.caption("Return to Email Process Control to revise the quote.")

st.title("📋 Smartsheet PO Handoff")
st.caption(
    "Prepared for the live PO form through manual copy/paste, with exact-label URL "
    "prefilling and direct API submission kept behind separate safety gates."
)

try:
    config = load_config()
except SmartsheetConfigurationError as exc:
    st.error(f"Smartsheet configuration error: {exc}")
    st.stop()

context = st.session_state.get(PREPARED_PO_CONTEXT_STATE_KEY)
if not isinstance(context, POContext):
    context = build_po_context(st.session_state)
if context is None:
    st.error(
        "No prepared PO reached this page. On some mobile browsers, opening a "
        "separate Streamlit page starts a new session and loses the in-memory quote."
    )
    st.info(
        "Return to Email Process Control and tap **Prepare Smartsheet submission**. "
        "The handoff now opens inline on the same page with the prepared values "
        "and attachment buttons visible."
    )
    st.stop()

if st.session_state.get("_smartsheet_context_id") != context.context_id:
    for state_key in list(st.session_state.keys()):
        if state_key.startswith("ssw_"):
            del st.session_state[state_key]
    st.session_state["_smartsheet_context_id"] = context.context_id
prefix = f"ssw_{context.context_id}_"
fields = dict(context.fields)
try:
    browser_token = device_token(st.context.cookies)
except Exception:
    browser_token = ""
if not browser_token:
    ensure_device_cookie()

if context.warnings:
    st.error(
        "Resolve these source-record problems in Email Process Control before any "
        "Smartsheet route can open:\n\n- " + "\n- ".join(context.warnings)
    )


def locked_text(label: str, field: str) -> None:
    st.text_input(
        label,
        value=fields.get(field, ""),
        disabled=True,
        key=f"{prefix}locked_{field}",
    )


def locked_area(label: str, field: str, height: int) -> None:
    st.text_area(
        label,
        value=fields.get(field, ""),
        height=height,
        disabled=True,
        key=f"{prefix}locked_{field}",
    )


st.subheader("1. Verify the source record")
st.caption(
    "The quote-derived values remain locked to Email Process Control. Request type "
    "is always PO, and service-center dispatch is always NA for this workflow."
)
left, right = st.columns(2)
with left:
    requester_key = f"{prefix}requester_name"
    remembered_requester = (
        remembered_device_requester(browser_token) if browser_token else ""
    )
    if requester_key not in st.session_state:
        st.session_state[requester_key] = (
            remembered_requester or fields.get("requester_name", "")
        )
    fields["requester_name"] = st.text_input(
        "Requester *",
        key=requester_key,
        help=(
            "After the same requester is used for three distinct prepared POs, "
            "this browser will prefill the name."
        ),
    )
    requester_memory_status = st.empty()
    if browser_token and remembered_requester:
        if st.button("Forget requester on this browser", key=f"{prefix}forget_requester"):
            forget_device_requester(browser_token)
            st.session_state[requester_key] = ""
            st.rerun()
    elif not browser_token:
        st.caption("Requester memory is unavailable when this browser blocks cookies.")

    locked_text("Request type", "request_type")
    locked_text("Contract", "contract")
    locked_text("Source site", "site")
    if contracts.is_rrh(fields.get("contract")):
        job_key = f"{prefix}job_number"
        current_job = fields.get("job_number", "")
        job_index = (
            RRH_JOB_NUMBERS.index(current_job)
            if current_job in RRH_JOB_NUMBERS
            else 0
        )
        fields["job_number"] = st.selectbox(
            "Job number *",
            RRH_JOB_NUMBERS,
            index=job_index,
            key=job_key,
        )
    else:
        fields["job_number"] = st.text_input(
            "Job number *",
            value=fields.get("job_number", ""),
            key=f"{prefix}job_number",
            help="Paste the exact Smartsheet job-number option for this contract.",
        )
    fields["site_location"] = st.text_input(
        "Smartsheet site number / location *",
        value=fields.get("site_location", ""),
        key=f"{prefix}site_location",
        help=(
            "Starts with the reviewed source site. Adjust only when Smartsheet's "
            "exact dropdown wording differs."
        ),
    )
    locked_text("Cost code", "cost_code")

    default_account = fields.get("object_account", "")
    account_index = (
        OBJECT_ACCOUNT_OPTIONS.index(default_account)
        if default_account in OBJECT_ACCOUNT_OPTIONS
        else 0
    )
    fields["object_account"] = st.selectbox(
        "Object account *",
        OBJECT_ACCOUNT_OPTIONS,
        index=account_index,
        key=f"{prefix}object_account",
    )
    locked_text("Agreement type for PO", "agreement_type")

with right:
    locked_text("Dispatch WO to service center?", "dispatch_service_center")
    locked_text("Vendor", "vendor")
    locked_text("Vendor contact name", "contact_name")
    locked_text("Vendor contact email", "contact_email")
    locked_text("PO/CO amount", "total")
    locked_text("Asset ID", "asset_id")
    locked_area("Description of work", "description_of_work", 260)

fields["instructions"] = st.text_area(
    "Additional information if needed",
    value=fields.get("instructions", ""),
    height=100,
    key=f"{prefix}instructions",
)
fields["send_copy_email"] = (
    "true"
    if st.checkbox(
        "Send me a copy of my responses",
        key=f"{prefix}send_copy_email",
    )
    else ""
)

missing_for_memory = missing_required_fields(fields, config.form_required_fields)
if (
    browser_token
    and fields.get("requester_name")
    and not context.warnings
    and manual_enabled(config)
    and not missing_for_memory
):
    requester_count = record_device_requester(
        device_token=browser_token,
        requester_name=fields["requester_name"],
        context_id=context.context_id,
    )
    if requester_count >= REQUESTER_SUGGEST_THRESHOLD:
        requester_memory_status.caption(
            "✓ Requester remembered on this browser. Use ‘Forget requester’ on a shared device."
        )
    elif requester_count:
        remaining = REQUESTER_SUGGEST_THRESHOLD - requester_count
        requester_memory_status.caption(
            f"Requester will be remembered after {remaining} more prepared PO"
            f"{'s' if remaining != 1 else ''} on this browser."
        )

field_problems = list(validate_submission_fields(fields))
attachment_problems = list(preflight_attachments(context.attachments))
source_blockers = list(context.warnings) + field_problems + attachment_problems
if field_problems or attachment_problems:
    st.warning(
        "Current preflight problems:\n\n- "
        + "\n- ".join(field_problems + attachment_problems)
    )

st.subheader("2. Verified attachments")
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
        "The quote bytes are unchanged. Safe adjacent filenames make manual attachment easier."
    )

st.subheader("3. Use the route ENFRA permits")
manual_tab, prefill_tab, api_tab = st.tabs(
    ["Manual copy/paste", "URL prefill", "API submission"]
)

with manual_tab:
    if not manual_enabled(config):
        st.info("Configure SMARTSHEET_FORM_URL to enable manual handoff.")
    else:
        missing_form = list(
            missing_required_fields(fields, config.form_required_fields)
        )
        blockers = source_blockers + (
            ["Required form values are missing: " + ", ".join(missing_form)]
            if missing_form
            else []
        )
        if blockers:
            st.error("Manual handoff is blocked:\n\n- " + "\n- ".join(blockers))
        else:
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
            "URL prefill remains disabled until the final form's exact labels and "
            "option values are tested and configured."
        )
    elif source_blockers:
        st.error("URL prefill is blocked:\n\n- " + "\n- ".join(source_blockers))
    else:
        try:
            prefilled = build_prefilled_form_url(fields, config)
            if prefilled.missing_required:
                st.error(
                    "Complete these required form values first: "
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
                "A form URL cannot carry files. Attach the verified downloads above."
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
        st.info("API submission is disabled by default.")
    else:
        if st.button(
            "Validate live sheet configuration", key=f"{prefix}validate_mapping"
        ):
            with st.spinner(
                "Checking exact column IDs, titles, types, options, and writability…"
            ):
                st.session_state[mapping_key] = validate_column_mapping(config)

        mapping_result = st.session_state.get(mapping_key)
        if mapping_result:
            if mapping_result.get("ok"):
                st.success("Every configured column matches the live specification.")
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
            st.info("Dry-run validates credentials and schema but cannot create a row.")
        elif config.api_mode == "live":
            missing_api = list(
                missing_required_fields(fields, config.required_fields)
            )
            blockers = source_blockers + list(readiness.problems)
            if missing_api:
                blockers.append(
                    "Required API values are missing: " + ", ".join(missing_api)
                )
            if blockers:
                st.error("API submission is blocked:\n\n- " + "\n- ".join(blockers))

            if st.button(
                "Submit PO to Smartsheet",
                type="primary",
                use_container_width=True,
                disabled=bool(blockers),
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
                            "Do not submit again. Smartsheet may already contain the row. "
                            "Use exact-key reconciliation."
                        )
                        if st.button(
                            "Search for the exact submission key",
                            key=f"{prefix}reconcile",
                            use_container_width=True,
                        ):
                            with st.spinner(
                                "Searching and verifying the submission-key cell…"
                            ):
                                reconciliation = reconcile_submission(
                                    fields,
                                    context.attachments,
                                    config=config,
                                )
                            if reconciliation.get("ok"):
                                st.success(
                                    f"Reconciled to row {reconciliation.get('row_id')}. "
                                    "Submit again only to resume missing attachments."
                                )
                                st.session_state.pop(result_key, None)
                            else:
                                st.error(
                                    reconciliation.get(
                                        "error", "Reconciliation failed."
                                    )
                                )

st.divider()
st.caption(
    "See docs/FAILURE_MODES_AND_CONTROLS.md. The example ENFRA work-order form "
    "informs the model but is not treated as the final PO schema."
)
