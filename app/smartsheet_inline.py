"""Inline manual Smartsheet handoff for mobile-safe PO submission.

The production Streamlit app keeps quote bytes, generated documents, and most
reviewed widget values in the active websocket session. On iPhone/iPad Safari,
navigating to a separate Streamlit page can create a fresh session. Rendering
the manual handoff inline avoids that boundary while retaining the exact form
labels, validation, attachment checks, and browser-scoped requester learning.
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
    download_names,
    handoff_rows,
    load_config,
    manual_enabled,
    missing_required_fields,
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
    """Render the supported manual route without leaving the source workflow."""
    st.markdown("#### Smartsheet PO handoff")
    st.success(
        "Your reviewed PO, quote, and generated attachments are still loaded on "
        "this page."
    )
    st.info(
        "Smartsheet does not receive these values automatically yet. Confirm the "
        "few fields below, download the prepared files, then use the purple form "
        "button and the Copy buttons to complete the form. Keep this page open."
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

    fields["send_copy_email"] = (
        "true"
        if st.checkbox(
            "Send me a copy of my Smartsheet responses",
            key=f"{prefix}send_copy_email",
        )
        else ""
    )
    st.caption(
        "Locked from the reviewed PO: Request type = PO; Agreement type = "
        f"{fields.get('agreement_type') or '—'}; Dispatch service center = NA."
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

    st.markdown("##### 3. Open Smartsheet and copy the prepared values")
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

    st.markdown(
        "1. Tap **Open Smartsheet form** below. It opens in a new tab.\n"
        "2. Return to this tab and tap **Copy** beside each value in order.\n"
        "3. Paste into the matching Smartsheet field, upload the files above, "
        "and submit."
    )
    render_manual_handoff(
        rows,
        config.form_url or "",
        key=f"{context.context_id}-inline-manual",
    )
    st.caption(
        "This manual pilot prepares the entry but does not submit it automatically."
    )
