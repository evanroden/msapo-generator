"""Inline, mobile-safe Smartsheet handoff for the streamlined PO workflow.

All user-editable values now appear before the final generation button in the
main page. This handoff therefore has one job: expose the two verified files
and the prefilled form link without asking the operator to repeat any fields.
Manual copy values remain available only inside a troubleshooting expander.

Why "inline" and not a page: this used to live on a separate Streamlit page. On
mobile, navigating between pages could start a fresh session and discard the
uploaded quote and the generated PDF, leaving the operator on a handoff screen
with nothing to hand off. ``pages/2_Smartsheet_PO.py`` survives only as a
non-submitting notice for old bookmarks.

Why no editable controls here: a second editable copy of any exported value is
FM-C04. The moment this screen could change a field, the values in the link and
the values baked into the attached PDF could disagree with nothing to detect it.
Every correction happens above the generation button; ``web_ui.py`` then
re-derives the context on every rerun and only renders this when the context ID
still matches what was generated.

tests/test_smartsheet_handoff_entrypoint.py reads this file's SOURCE TEXT and
asserts on specific phrases in the operator guidance below -- several of those
sentences exist because a real operator got stuck at that exact step -- so
rewording them is a test-visible change, not cosmetic.
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
    """Render downloads and a prefilled form link in the active session.

    Assumes ``context`` is the freshly rebuilt PO context whose ID the caller has
    already matched against the one recorded when the files were generated;
    this function does no staleness checking of its own.

    Fail-closed by construction: every gate below returns early rather than
    degrading. There is intentionally no partial mode -- an operator shown a
    link that is missing a required value has no way to notice, whereas an
    operator shown a blocking message can fix the input and regenerate.

    Renders only; it writes no session state and may be called on every rerun.
    """
    st.markdown("#### Your files and Smartsheet link are ready")

    # Configuration is read on every rerun rather than cached, so an operations
    # change to the Render environment takes effect on the next interaction
    # instead of requiring anyone to notice that a restart is needed.
    try:
        config = load_config()
    except SmartsheetConfigurationError as exc:
        st.error(f"Smartsheet configuration error: {exc}")
        return

    fields = dict(context.fields)
    # Every widget key on this screen is namespaced by the context ID. The ID is
    # a hash of every field plus every attachment, so a different quote gets a
    # different widget namespace and cannot inherit the previous PO's state
    # (FM-C01).
    prefix = f"ssi_{context.context_id}_"
    # The "not found" wording is intentional and must not become an empty string
    # or a dash: this line is the operator's last chance to notice that
    # extraction missed the vendor, site or amount before they open the form.
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

    # Three independent sources, concatenated rather than short-circuited so the
    # operator sees every problem at once. They do not overlap: context.warnings
    # covers reassembly of the PO (missing contract, unreconciled totals),
    # validate_submission_fields covers Smartsheet's own field rules, and
    # preflight_attachments covers file size, emptiness and name collisions.
    # Dropping any one of them leaves a whole class of rejection undetected
    # until the operator is already inside the Smartsheet form.
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
    # Exactly two, not "at least two". download_names labels positionally
    # (1 = the unchanged vendor quote, 2 = the generated MSAPO form PDF) and the
    # two-column layout below indexes 0 and 1, so any other count would either
    # mislabel a file or raise an IndexError mid-render. Purchasing rejects a
    # submission that is missing either file, so blocking here is correct.
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
            # The key is namespaced by context ID (see `prefix`). Fixed widget
            # keys across Streamlit reruns were FM-C01: a new quote inherited the
            # previous PO's widget state. Any key added to this screen must carry
            # the same prefix.
            key=f"{prefix}download_{index}",
            width="stretch",
        )
        # The filename is repeated as a caption because the button label shows
        # only the kind ("Quote · PDF"); on a phone the operator has to match
        # what landed in Files against what the form asks for.
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
    # These three sentences are the answer to the most common support question:
    # the link opened the right form and every box was empty. That is what an
    # EXPIRED Smartsheet session looks like -- the form loads, the query values
    # are discarded, and nothing reports an error. Signing back in and reusing
    # the same button fixes it. Phrases here are asserted by the entrypoint test.
    st.caption(
        "Smartsheet needs to have been opened or signed into within the last few hours. "
        "The button opens a new browser tab; on iPhone or iPad, iOS may "
        "hand the same link to the signed-in Smartsheet app. If the values do "
        "not appear, sign back in, return here, and use the same button again."
    )
    if not manual_enabled(config):
        st.error("The Smartsheet form link is not configured.")
        return

    # The FORM's required list, not the API's. The two are configured separately
    # because the live form and the sheet can disagree about what is mandatory,
    # and this screen only ever drives the form.
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
    # A SECOND required-value check, and not redundant with the one above. That
    # one asks "is the value present?"; this one asks "did it actually survive
    # encoding into the URL?" -- a field can be fully populated and still be
    # dropped for a missing label mapping or the URL length ceiling (FM-D06).
    # Withholding the link entirely is the point: a link whose mandatory box is
    # blank looks identical to a working one until purchasing rejects the row.
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
    # Stated explicitly because the opposite is the natural assumption once the
    # form appears already filled in (FM-D05). A URL cannot carry files, and
    # opening it never submits anything -- an operator who believes otherwise
    # closes the tab and the request never reaches purchasing.
    st.caption(
        "The link fills the form but does not submit it or attach the two files."
    )

    # Collapsed by default and deliberately labelled as troubleshooting. Showing
    # the copy list next to a working link was FM-C09: operators re-entered
    # fields the link had already filled, which is slower and introduces the
    # transcription errors the prefill route exists to remove.
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
            # Context ID in the key, so the fallback's browser-stored copy
            # progress is scoped to this exact PO (FM-C02). Reusing a constant
            # here would carry green checkmarks onto the next request.
            key=f"{context.context_id}-manual-fallback",
            link_label="Open Smartsheet in a new tab ↗",
        )
