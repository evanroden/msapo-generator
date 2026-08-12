"""Inline, mobile-safe Smartsheet handoff for the streamlined PO workflow.

All user-editable values now appear before the final generation button in the
main page. This handoff therefore has one job: expose the two verified files
and the prefilled form link without asking the operator to repeat any fields.
Manual copy values remain available only inside a troubleshooting expander.
"""

from __future__ import annotations

import mimetypes

import streamlit as st

from app.po_context import POContext
from app.smartsheet import (
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
from app.smartsheet_ui import render_manual_handoff, render_prefilled_link


def render_inline_smartsheet_handoff(context: POContext) -> None:
    """Render downloads and a prefilled form link in the active session."""
    st.markdown("#### Your files and Smartsheet link are ready")

    try:
        config = load_config()
    except SmartsheetConfigurationError as exc:
        st.error(f"Smartsheet configuration error: {exc}")
        return

    fields = dict(context.fields)
    prefix = f"ssi_{context.context_id}_"
    summary = (
        f"**{fields.get('request_type') or 'PO'}** · "
        f"{fields.get('vendor') or 'Vendor not found'} · "
        f"{fields.get('site_location') or fields.get('site') or 'Site not found'} · "
        f"{fields.get('total') or 'Amount not found'}"
    )
    st.success(summary)
    st.caption(
        f"Object Account: {fields.get('object_account') or '—'} · "
        f"Agreement Type: {fields.get('agreement_type') or '—'} · "
        f"Asset ID: {fields.get('asset_id') or 'No asset'}"
    )

    field_problems = list(validate_submission_fields(fields))
    attachment_problems = list(preflight_attachments(context.attachments))
    blockers = list(context.warnings) + field_problems + attachment_problems
    if blockers:
        st.warning(
            "Fix these items above, then generate the package again:\n\n- "
            + "\n- ".join(blockers)
        )
        return

    st.markdown("##### 1. Save both files")
    renamed_files = download_names(context.attachments, context.attachment_base)
    if len(renamed_files) != 2:
        st.error("The package must contain exactly the original quote and one scope PDF.")
        return
    columns = st.columns(2, gap="small")
    for index, (label, filename, data) in enumerate(renamed_files):
        columns[index].download_button(
            f"Download {label}",
            data=data,
            file_name=filename,
            mime=mimetypes.guess_type(filename)[0] or "application/octet-stream",
            key=f"{prefix}download_{index}",
            width="stretch",
        )
        columns[index].caption(filename)
    st.warning(
        "Keep both files. Near the end of the Smartsheet form, upload the original quote "
        "and the MSAPO form PDF."
    )
    st.caption(
        "Windows Chrome/Edge: save both files, open the Downloads folder in "
        "File Explorer, select both, and drag them together onto Smartsheet's "
        "attachment box. iPhone/iPad: choose both files from Files."
    )

    st.markdown("##### 2. Open the prefilled Smartsheet form")
    st.caption(
        "Smartsheet needs to have been opened or signed into within the last few hours. "
        "The button opens a new browser tab; on iPhone or iPad, iOS may "
        "hand the same link to the signed-in Smartsheet app. If the values do "
        "not appear, sign back in, return here, and use the same button again."
    )
    if not manual_enabled(config):
        st.error("The Smartsheet form link is not configured.")
        return

    missing = list(missing_required_fields(fields, config.form_required_fields))
    if missing:
        st.warning(
            "Complete these values above, then generate again: " + ", ".join(missing)
        )
        return
    if not prefill_enabled(config):
        st.error("Automatic Smartsheet prefilling is not enabled.")
        return

    try:
        prefilled = build_prefilled_form_url(fields, config)
    except SmartsheetConfigurationError as exc:
        st.error(f"Could not build the prefilled Smartsheet link: {exc}")
        return
    if prefilled.missing_required:
        st.error(
            "The Smartsheet link could not include every required value: "
            + ", ".join(prefilled.missing_required)
            + ". The form link has been withheld."
        )
        return

    rows = handoff_rows(fields, config)
    if not rows:
        st.error("No populated fields are available for the Smartsheet link.")
        return

    render_prefilled_link(prefilled.url)
    st.caption(
        "The link fills the form but does not submit it or attach the two files."
    )

    with st.expander("Troubleshooting: show manual field values", expanded=False):
        if prefilled.skipped:
            st.warning(
                "These values did not fit in the custom URL: "
                + ", ".join(prefilled.skipped)
            )
        st.caption(
            "Use these copy controls only if a field remains blank after reopening "
            "Smartsheet and tapping the link again."
        )
        render_manual_handoff(
            rows,
            prefilled.url,
            key=f"{context.context_id}-manual-fallback",
            link_label="Open Smartsheet in a new tab ↗",
        )
