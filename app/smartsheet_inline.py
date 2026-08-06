"""Inline prefilled Smartsheet handoff for mobile-safe PO submission.

The production Streamlit app keeps quote bytes, generated documents, and most
reviewed widget values in the active websocket session. On iPhone/iPad Safari,
navigating to a separate Streamlit page can create a fresh session. Rendering
the handoff inline avoids that boundary while retaining exact form labels,
custom-URL prefilling, validation, attachment checks, and browser-scoped
requester learning.
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
from app.po_context import POContext
from app.smartsheet import (
    OBJECT_ACCOUNT_OPTIONS,
    RRH_JOB_NUMBERS,
    SmartsheetConfigurationError,
    build_prefilled_form_url,
    download_names,
    handoff_rows,
    load_config,
    manual_enabled,
    missing_required_fields,
    prefill_enabled,
    preflight_attachments,
    validate_submission_fields,
)
from app.smartsheet_ui import render_manual_handoff


def _browser_token() -> str:
    try:
        token = device_token(st.context.cookies)
    except Exception:
        token = ""
    if not token:
        # Never reload a page that already owns analyzed quote bytes. The next
        # ordinary visit can observe the cookie created by this fallback.
        ensure_device_cookie(reload_parent=False)
    return token


def render_inline_smartsheet_handoff(context: POContext) -> None:
    """Render a prefilled form route without leaving the source workflow."""
    st.markdown("#### Smartsheet PO handoff")
    st.success(
        "Your reviewed PO, quote, and generated attachments are still loaded on "
        "this page."
    )
    st.info(
        "Confirm the few fields below and download the prepared files. The purple "
        "button will open a custom Smartsheet URL with the reviewed PO values "
        "already filled. Keep this page open for attachment uploads and the Copy "
        "fallback."
    )

    try:
        config = load_config()
    except SmartsheetConfigurationError as exc:
        st.error(f"Smartsheet configuration error: {exc}")
        return

    prefix = f"ssi_{context.context_id}_"
    fields = dict(context.fields)
    attachment_names = ", ".join(name for name, _ in context.attachments)
    st.markdown("##### Prepared PO")
    st.text(
        "\n".join(
            (
                f"Vendor: {fields.get('vendor') or '—'}",
                f"Site: {fields.get('site_location') or fields.get('site') or '—'}",
                f"Amount: {fields.get('total') or '—'}",
                f"Package: {attachment_names or '—'}",
            )
        )
    )
    browser_token = _browser_token()
    remembered_requester = (
        remembered_device_requester(browser_token) if browser_token else ""
    )
    requester_key = f"{prefix}requester_name"
    if requester_key not in st.session_state:
        st.session_state[requester_key] = (
            remembered_requester or fields.get("requester_name", "")
        )

    st.markdown("##### 1. Confirm the form-only fields")
    fields["requester_name"] = st.text_input(
        "Requester *",
        key=requester_key,
        help=(
            "After the same requester is used for three distinct POs, this "
            "browser will prefill the name."
        ),
    )
    requester_status = st.empty()
    if browser_token and remembered_requester:
        if st.button(
            "Forget requester on this browser",
            key=f"{prefix}forget_requester",
        ):
            forget_device_requester(browser_token)
            st.session_state[requester_key] = ""
            st.rerun()
    elif not browser_token:
        st.caption("Requester memory is unavailable when this browser blocks cookies.")

    left, right = st.columns(2, gap="small")
    with left:
        if contracts.is_rrh(fields.get("contract")):
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
                key=f"{prefix}job_number",
            )
        else:
            fields["job_number"] = st.text_input(
                "Job number *",
                value=fields.get("job_number", ""),
                key=f"{prefix}job_number",
                help="Paste the exact Smartsheet option for this contract.",
            )
        fields["site_location"] = st.text_input(
            "Smartsheet site number / location *",
            value=fields.get("site_location", ""),
            key=f"{prefix}site_location",
            help="Adjust only if the form's exact dropdown wording differs.",
        )
    with right:
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
        fields["instructions"] = st.text_area(
            "Additional information if needed",
            value=fields.get("instructions", ""),
            height=100,
            key=f"{prefix}instructions",
        )

    # Smartsheet's response-copy query parameter requires the requester's
    # email address, while this workflow stores only the requester's name.
    # Keep this as a deliberate choice inside the authenticated form rather
    # than pretending a boolean value can prefill it.
    fields.pop("send_copy_email", None)
    st.caption(
        "Locked from the reviewed PO: Request type = PO; Agreement type = "
        f"{fields.get('agreement_type') or '—'}; Dispatch service center = NA. "
        "Choose ‘Send me a copy’ inside Smartsheet if needed."
    )

    missing_for_memory = missing_required_fields(
        fields, config.form_required_fields
    )
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
            requester_status.caption(
                "✓ Requester remembered on this browser. Use ‘Forget requester’ "
                "on a shared device."
            )
        elif requester_count:
            remaining = REQUESTER_SUGGEST_THRESHOLD - requester_count
            requester_status.caption(
                f"Requester will be remembered after {remaining} more prepared PO"
                f"{'s' if remaining != 1 else ''} on this browser."
            )

    field_problems = list(validate_submission_fields(fields))
    attachment_problems = list(preflight_attachments(context.attachments))
    blockers = list(context.warnings) + field_problems + attachment_problems
    if blockers:
        st.warning(
            "Resolve these items before opening the form:\n\n- "
            + "\n- ".join(blockers)
        )

    st.markdown("##### 2. Download the verified attachments")
    renamed_files = download_names(context.attachments, context.attachment_base)
    if not renamed_files:
        st.error("No verified attachments are available.")
    else:
        columns = st.columns(min(3, len(renamed_files)), gap="small")
        for index, (label, filename, data) in enumerate(renamed_files):
            columns[index % len(columns)].download_button(
                label,
                data=data,
                file_name=filename,
                mime=mimetypes.guess_type(filename)[0]
                or "application/octet-stream",
                key=f"{prefix}download_{index}",
                use_container_width=True,
            )
        st.caption(
            "Upload these files to the Smartsheet form. The original quote bytes "
            "are unchanged."
        )

    st.markdown("##### 3. Open the prefilled Smartsheet form")
    if not manual_enabled(config):
        st.error("The Smartsheet form link is not configured.")
        return

    missing_form = list(
        missing_required_fields(fields, config.form_required_fields)
    )
    if missing_form:
        st.warning(
            "Complete these required values above to unlock the form: "
            + ", ".join(missing_form)
        )
        return
    if blockers:
        return

    rows = handoff_rows(fields, config)
    if not rows:
        st.warning("No populated fields are available to copy.")
        return

    if not prefill_enabled(config):
        st.error(
            "Automatic Smartsheet prefilling is not enabled. Use the email backup "
            "while the deployment configuration is corrected."
        )
        return

    try:
        prefilled = build_prefilled_form_url(fields, config)
    except SmartsheetConfigurationError as exc:
        st.error(f"Could not build the prefilled Smartsheet link: {exc}")
        return

    included = set(prefilled.included)
    fallback_rows = [
        (field, label, value)
        for field, label, value in rows
        if field not in included
    ]
    st.success(
        f"{len(prefilled.included)} populated field"
        f"{'s are' if len(prefilled.included) != 1 else ' is'} ready to prefill."
    )
    if fallback_rows:
        st.warning(
            "These fields could not be included safely in the custom URL. Use "
            "their Copy buttons below: "
            + ", ".join(label for _, label, _ in fallback_rows)
        )

    st.markdown(
        "1. Tap **Open prefilled Smartsheet form** below. It opens in a new tab.\n"
        "2. Review the populated fields. If Smartsheet leaves anything blank, "
        "return here and use its **Copy** button.\n"
        "3. Upload the verified files downloaded above, then submit the form."
    )
    render_manual_handoff(
        rows,
        prefilled.url,
        key=f"{context.context_id}-inline-prefill",
        link_label="Open prefilled Smartsheet form ↗",
    )
    st.caption(
        "The custom URL fills form values but never submits the PO or includes "
        "attachments. The original quote remains unchanged."
    )
