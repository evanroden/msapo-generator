"""Streamlit workflow for employee reimbursement reports.

Receipts and mileage in; three artifacts out -- the completed official JDE
workbook, a combined PDF (form first, receipt pages after it), and an approval
email draft that already carries that PDF. The tool never sends anything: the
employee reviews the draft and sends it.

``app.web_ui.main`` is the only production caller. It imports
``render_expense_workflow`` and ``preserve_expense_draft_state`` from here, and
the import direction is one-way -- which is why the highlight helper shared with
the purchase-order page lives in ``app.ui_highlight`` instead of in ``web_ui``.

Three tests read this file's SOURCE TEXT, so an edit here can break the suite
with no behavioural change at all:

* ``tests/test_expense_draft_state.py`` regex-scans the whole module for every
  literal ``expense_*`` key the workflow removes from session state, and parses
  the exclusion tuple out of ``preserve_expense_draft_state``. Writing such a
  key inside a COMMENT registers as a real one and fails the test.
* ``tests/test_web_ui_app.py`` asserts on the source of
  ``render_expense_workflow`` (no blue information callouts; the approver
  typeahead arguments), ``_render_generated_package`` (same callout rule) and
  ``_render_ios_mail_share`` (the share must go through the declared
  first-party component, never a generic HTML embed).
* ``tests/test_expense_disclosure.py`` drives the real app and asserts that the
  step-2 collapse is placement-only.

Much of what looks odd here is a recorded reversal. Read before changing it:
docs/COMMIT_NOTES_2026-08-11_EXPENSE_EMAIL_ATTACHMENT_HANDOFF.md (the email
handoff invariants), docs/COMMIT_NOTES_2026-08-12_CORRECTNESS_AND_FAILURE_MODE_HARDENING.md
sections 4.1, 4.3 and 7.1 (the draft mirror, and why rebuilding it is wrong),
and docs/COMMIT_NOTES_2026-08-13_EXPENSE_DISCLOSURE_AND_NEEDS_YOU_HIGHLIGHT.md
(progressive disclosure and the needs-a-value highlight).
"""

from __future__ import annotations

import base64
import hashlib
import html
import mimetypes
import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from app import contracts
from app.config import RRH_APPROVER_EMAIL, RRH_APPROVER_NAME
from app.eml_builder import (
    build_eml,
    build_mailto_url,
    build_plain_body,
)
from app.expense_report import (
    ALLOCATION_JOB,
    EXPENSE_SECTION_ENTERTAINMENT,
    EXPENSE_SECTION_MISC,
    MAX_MILEAGE_ITEMS,
    MAX_MISCELLANEOUS_ITEMS,
    ExpenseAllocation,
    ExpenseItem,
    ExpenseReportError,
    ExpensePackage,
    ExpenseReportDetails,
    MileageItem,
    allocation_problems,
    build_expense_package,
    email_attachment_size_warning,
    email_attachments_for_package,
    employee_signature_png,
    expense_report_signature,
    expense_report_warnings,
    irs_business_mileage_rate,
    parse_expense_amount,
    parse_mileage,
    receipt_preview_bytes,
    total_reimbursement,
    validate_expense_report,
)
from app.job_numbers import job_numbers_for_contract
from app.memory import (
    expense_approvers,
    record_expense_profile,
    record_expense_approver,
    remembered_device_account_manager,
    remembered_expense_employee_number,
    remembered_expense_profile,
)
from app.receipt_analyzer import ReceiptAnalysis, analyze_receipt
from app.ui_highlight import highlight_needed_fields


# These two strings ARE the workflow identity: they are the segmented-control
# option labels, the values stored in session_state["workflow_mode"], and the
# values web_ui.main compares against before routing. Changing either one
# strands every already-open browser session on a mode that no longer matches
# a branch -- which is the state that used to render the half-empty hybrid page
# (see the 2026-08-12 hardening notes, section 4.2).
EXPENSE_WORKFLOW = "Expense reimbursement"
PURCHASE_WORKFLOW = "Purchase order"

# Uploader whitelist. HEIC/HEIF/HIF are here because that is what an iPhone
# produces by default and this workflow is used from phones; app.ocr normalizes
# them before the vision call. Removing an entry does not merely hide a format
# -- Streamlit rejects the file at the browser with a generic message, so the
# operator sees "not allowed" with no explanation of what to convert it to.
_RECEIPT_TYPES = [
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "tif",
    "tiff",
    "bmp",
    "heic",
    "heif",
    "hif",
]
# Per-file cap, enforced by the browser through st.file_uploader's
# max_upload_size (Streamlit >= 1.61, which requirements.txt pins for exactly
# this reason). That argument is in WHOLE MEGABYTES, hence the floor division
# at the call site -- a value chosen here that is not a whole number of MB is
# silently truncated downward, so keep this a clean multiple of 1024*1024.
_MAX_RECEIPT_BYTES = 15 * 1024 * 1024
# Aggregate cap across all receipts in one report. This one has no browser-side
# enforcement and must be checked by hand after de-duplication; the number is
# repeated verbatim in the operator-facing error below, so change both.
_MAX_REPORT_UPLOAD_BYTES = 60 * 1024 * 1024
# A sentinel option rather than selectbox(index=None). The job selectbox is
# re-seeded from session_state every rerun, and a None default cannot be
# distinguished from "the seed has not been written yet"; a sentinel string can
# be compared, restored through the draft mirror, and mapped back to "" at the
# one place that builds the ExpenseAllocation. allocation_problems() rejects ""
# because it is not in JOB_NUMBER_OPTIONS, so the placeholder blocks generation
# instead of quietly exporting a blank job number.
_JOB_PLACEHOLDER = "— Select the job number —"
_SECTION_LABELS = {
    EXPENSE_SECTION_MISC: "Miscellaneous",
    EXPENSE_SECTION_ENTERTAINMENT: "Entertainment",
}
_MAIL_LABELS = {
    "home": "Mail check to home address",
    "satellite": "Mail check to a satellite office",
}
# RRH coding defaults, taken from the approved Dane RRH report rather than
# invented. _RRH_DEFAULT_JOB must remain a member of
# job_numbers_for_contract("Rochester Regional Health") -- if it drifts out of
# that catalog the seeded value fails the membership guard in
# _render_job_allocation_fields, silently falls back to the placeholder, and
# every RRH receipt starts uncoded again.
_RRH_DEFAULT_JOB = "RRH-695400022-O&M"
# Account / Cost Type is the two-digit service year plus this suffix: year 1 is
# 01AMA, year 2 is 02AMA. The zero padding is load-bearing (JDE rejects "1AMA").
_RRH_ACCOUNT_COST_TYPE_SUFFIX = "AMA"
_RRH_DEFAULT_COST_CODE = "5490"
# These labels are both the selectbox options and the value persisted under
# "expense_email_destination". Each one names its attachment state on purpose:
# the 2026-08-11 handoff makes it an invariant that no route may be labelled as
# carrying the PDF unless it actually does. Renaming any of them also orphans
# the stored destination of every open session -- handled by the membership
# guard in _render_generated_package, which resets to the platform default.
_EMAIL_OUTLOOK_APP = "Outlook for Windows (PDF attached)"
_EMAIL_OUTLOOK_WEB = "Outlook on the web (PDF attached)"
_EMAIL_DEFAULT_APP = "Mail on iPhone / iPad (PDF attached)"
_EMAIL_DESTINATIONS = (
    _EMAIL_OUTLOOK_APP,
    _EMAIL_OUTLOOK_WEB,
    _EMAIL_DEFAULT_APP,
)
_IOS_MAIL_SHARE_FRONTEND = (
    Path(__file__).resolve().parent / "components" / "expense_ios_mail_share"
)
# Declared ONCE, at import time, and served from a filesystem path so Streamlit
# hosts it on the application's own origin. Both properties are load-bearing:
#
# * navigator.share()'s permissions-policy allowlist defaults to `self`, so the
#   generic inline-HTML embed helper -- which renders into a srcdoc iframe whose
#   origin is opaque ("null") -- is not a usable Web Share context on WebKit.
#   A desktop mock still "works" there, which is how this was shipped broken
#   once. tests/test_web_ui_app.py pins the declared-component route.
# * declare_component() with the same name twice raises, so this must stay at
#   module scope. Moving it inside the render function fails on the second
#   rerun, not the first.
_IOS_MAIL_SHARE_COMPONENT = components.declare_component(
    "expense_ios_mail_share",
    path=_IOS_MAIL_SHARE_FRONTEND,
)


def render_expense_workflow(browser_token: str) -> None:
    """Render the complete receipt-to-email-draft workflow.

    Called once per rerun by ``app.web_ui.main`` when the workflow selector is
    on ``EXPENSE_WORKFLOW``. ``browser_token`` is the opaque device cookie and
    may legitimately be ``""`` -- device memory is a convenience and every
    lookup that uses it degrades to "nothing remembered", never to an error.

    Guarantees: it renders every step, and it never sends mail, writes to
    Smartsheet, or posts to JDE. It returns early only for an over-budget
    receipt set, after leaving the clear-and-start-over control on screen.

    Assumes it is the first thing to touch ``expense_*`` session keys this run:
    ``restore_expense_draft_state()`` has to re-inject the mirrored values
    BEFORE any widget below is instantiated, because a post-render write to a
    widget key is discarded (and, for the approver selectbox, also fires its
    on_change and clears the paired email). That ordering is the single most
    load-bearing line in this function.
    """
    restore_expense_draft_state()
    # One approver-memory context per browser session, not per generated
    # report. record_expense_approver() counts one use per context, so this is
    # what stops a dozen Streamlit reruns of the same report from inflating an
    # approver's use_count into a false "confirmed" ranking.
    report_memory_context = str(
        st.session_state.setdefault("expense_report_memory_context", uuid.uuid4().hex)
    )
    st.markdown(
        """
        <div class="hero">
            <p class="brand-kicker">EXPENSE REPORT WORKFLOW</p>
            <h1>Expense Report <span class="zing">Process Control</span></h1>
            <p class="hero-subtitle">
                Add receipts and mileage, review the prefilled fields, then create
                the completed Excel form, combined PDF, and approval email draft.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num">1</div>
            <p class="step-title">Upload receipts</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    # The nonce is part of the uploader's widget KEY. Streamlit offers no way to
    # remove a file from a file_uploader programmatically, so "remove this
    # receipt" and "clear the report" both bump the nonce, which retires the old
    # widget and mounts an empty one. Reading it here (rather than deriving it
    # from the file list) keeps the key stable across ordinary reruns; a key
    # that changed every run would drop the operator's selection silently.
    uploader_nonce = int(st.session_state.get("expense_uploader_nonce", 0) or 0)
    uploads = st.file_uploader(
        "Upload one image or PDF per receipt",
        type=_RECEIPT_TYPES,
        accept_multiple_files=True,
        max_upload_size=_MAX_RECEIPT_BYTES // (1024 * 1024),
        key=f"expense_receipt_uploader_{uploader_nonce}",
        help=(
            "Select multiple files at once. Screenshots, phone photos, HEIC, and "
            "PDF receipts are supported. One file may contain multiple receipt pages."
        ),
    )
    mirrored_uploads = list(
        st.session_state.get("expense_receipt_files", []) or []
    )
    if uploads:
        current_uploads = [
            (upload.name, upload.getvalue(), upload.type or "application/octet-stream")
            for upload in uploads
        ]
        # Run de-duplication over THIS batch alone purely to collect names to
        # warn about. _merge_receipt_sources below drops duplicates silently, so
        # without this call selecting the same file twice in one dialog would do
        # nothing at all with no explanation. (Known gap: a file that duplicates
        # one already in the mirror is still dropped without a warning -- its
        # preview is already on screen, which is the only feedback.)
        _, duplicate_names = _unique_receipts(current_uploads)
        # File-uploader values cannot be restored programmatically after that
        # widget is hidden by a workflow switch. Merge its current additions
        # into the bounded byte mirror so the restored files do not disappear
        # on the next ordinary rerun.
        upload_sources = _merge_receipt_sources(
            mirrored_uploads,
            current_uploads,
        )
        st.session_state["expense_receipt_files"] = upload_sources
        st.session_state.pop("expense_restored_without_uploader", None)
    else:
        upload_sources = mirrored_uploads
        duplicate_names = []
        if upload_sources:
            st.session_state["expense_restored_without_uploader"] = True
            st.caption(
                "Your in-progress receipts were restored. Add more files above, "
                "remove one beside its preview, or clear the entire report."
            )
    unique_uploads, stored_duplicate_names = _unique_receipts(upload_sources or [])
    duplicate_names.extend(stored_duplicate_names)
    # Receipt identity is the SHA-256 of the bytes, not the filename. Two phone
    # photos named IMG_0001.jpg from different receipts are distinct; the same
    # receipt re-uploaded under a new name is not. Every per-receipt session key
    # below is derived from this id, so re-uploading an identical file
    # deliberately restores its already-reviewed fields instead of asking again.
    active_ids = {receipt_id for receipt_id, _, _ in unique_uploads}
    _clear_removed_receipts(active_ids)
    if duplicate_names:
        st.warning(
            "Duplicate receipt files were ignored: "
            + ", ".join(duplicate_names)
            + "."
        )
    if upload_sources:
        if st.button(
            "Clear expense report and start over",
            key="expense_clear_report",
            help="Removes this in-progress expense report from the current browser session.",
        ):
            _reset_expense_report()
            st.rerun()
    # Ordering matters: the clear-and-start-over button is rendered ABOVE this
    # guard so an over-budget receipt set is still recoverable. Moving the size
    # check earlier returns before that button exists, and the operator is
    # stranded on a page whose only control is a file uploader that will refuse
    # everything -- with the offending bytes already parked in the mirror.
    total_upload_bytes = sum(len(data) for _, _, data in unique_uploads)
    if total_upload_bytes > _MAX_REPORT_UPLOAD_BYTES:
        st.error(
            "These receipts total more than 60 MB. Remove or resize the largest "
            "files before continuing."
        )
        return

    analyses: dict[str, ReceiptAnalysis] = {}
    for index, (receipt_id, filename, file_bytes) in enumerate(unique_uploads, 1):
        analyses[receipt_id] = _receipt_analysis(
            receipt_id,
            filename,
            file_bytes,
            index=index,
        )

    if unique_uploads:
        st.caption(
            f"{len(unique_uploads)} unique receipt"
            f"{'s' if len(unique_uploads) != 1 else ''} ready for review. "
            "Original uploads remain unchanged; compact copies are used only in the workbook."
        )
    else:
        st.caption(
            "No receipt is required for mileage-only reimbursement. You can add "
            "business mileage below or upload receipts now."
        )

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num">2</div>
            <p class="step-title">Confirm report details</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    # No placeholder and no index=None: this control silently defaults to the
    # first contract. That is why it stays OUTSIDE the collapsible details panel
    # below (see the 2026-08-13 disclosure notes, section 2.3) -- hiding a
    # scoping control that defaults without saying so is the unknown-facility
    # hazard already fixed on the purchase-order side.
    accounts = tuple(contracts.contract_names())
    account = st.selectbox(
        "Account / contract *",
        accounts,
        key="expense_account",
        help=(
            "This filters the verified job-number choices and remembers the "
            "correct administrator."
        ),
    )
    # Must run after the account selectbox (it needs the chosen account) and
    # before any detail widget below is instantiated, for the same
    # post-render-write reason given in this function's docstring.
    _seed_profile(browser_token, account)
    # Every step-2 widget key is namespaced by this digest so switching accounts
    # gives a fresh, independently remembered set of details rather than
    # carrying one facility's approver into another's report. _seed_profile
    # recomputes the SAME expression internally; the two must stay identical or
    # the seeds land on keys no widget reads and the fields render blank with no
    # error. tests/test_expense_disclosure.py hardcodes this derivation too.
    account_token = hashlib.sha256(account.encode("utf-8")).hexdigest()[:10]

    # Progressive disclosure, matching the purchase-order flow. Every field
    # below is still rendered exactly once and stays fully editable -- nothing
    # is removed and nothing becomes read-only. Only PLACEMENT changes: once the
    # account's confirmed history has supplied every detail, the block collapses
    # behind one line instead of presenting ten controls the operator does not
    # need to touch.
    #
    # Placement is decided from session_state BEFORE rendering, because a
    # widget's value does not exist until it renders. The account selector above
    # stays visible deliberately: it has no placeholder and silently defaults to
    # the first contract, so hiding it would repeat the unknown-facility hazard
    # already fixed on the purchase-order side.
    def _detail_unset(state_key: str) -> bool:
        return not str(st.session_state.get(state_key, "") or "").strip()

    _outstanding_details = sum(
        (
            _detail_unset(f"expense_employee_name_{account_token}"),
            _detail_unset(f"expense_employee_number_{account_token}"),
            _detail_unset(f"expense_approver_name_{account_token}"),
            _detail_unset(f"expense_approver_email_{account_token}"),
            (
                st.session_state.get(f"expense_mail_destination_{account_token}")
                == "satellite"
                and _detail_unset(f"expense_satellite_office_{account_token}")
            ),
        )
    )
    # Highlight the specific fields still needing a value. The expense block is
    # not split into resolved/unresolved containers the way the purchase-order
    # page is, so the keys are named directly. Recomputed every rerun, so a
    # field stops being highlighted on the run after it is filled.
    _needs_value_keys = [
        key
        for key, missing in (
            (f"expense_employee_name_{account_token}",
             _detail_unset(f"expense_employee_name_{account_token}")),
            (f"expense_employee_number_{account_token}",
             _detail_unset(f"expense_employee_number_{account_token}")),
            (f"expense_approver_name_{account_token}",
             _detail_unset(f"expense_approver_name_{account_token}")),
            (f"expense_approver_email_{account_token}",
             _detail_unset(f"expense_approver_email_{account_token}")),
            (f"expense_satellite_office_{account_token}",
             st.session_state.get(f"expense_mail_destination_{account_token}")
             == "satellite"
             and _detail_unset(f"expense_satellite_office_{account_token}")),
        )
        if missing
    ]
    # Safe to emit raw because account_token is hex: Streamlit rewrites anything
    # outside [A-Za-z0-9_-] to a hyphen when it builds the st-key- class, so a
    # key built from the account NAME instead would produce a selector matching
    # nothing -- no error, no highlight, nothing to notice in a green test run.
    # ui_highlight normalises defensively, but keep the token hex anyway.
    if _needs_value_keys:
        highlight_needed_fields(_needs_value_keys)

    if _outstanding_details:
        _details_panel = st.container()
    else:
        _details_panel = st.expander(
            "Report details \u2014 filled from this account's confirmed history",
            expanded=False,
        )

    with _details_panel:
        if not _outstanding_details:
            st.caption(
                "Every detail below stays editable. Open this panel to change "
                "anything the tool filled for you."
            )
        detail_columns = st.columns(2)
        with detail_columns[0]:
            employee_name_key = f"expense_employee_name_{account_token}"
            employee_number_key = f"expense_employee_number_{account_token}"
            employee_number_recall_key = (
                f"expense_employee_number_recalled_for_{account_token}"
            )
            employee_name = st.text_input(
                "Employee name *",
                key=employee_name_key,
                on_change=_recall_employee_number_for_name,
                args=(
                    browser_token,
                    account,
                    employee_name_key,
                    employee_number_key,
                    employee_number_recall_key,
                ),
            ).strip()
            employee_number = st.text_input(
                "Employee number *",
                key=employee_number_key,
                help=(
                    "After a confirmed report, this is recalled for the same employee "
                    "name on this browser and account. It remains editable."
                ),
                on_change=_clear_employee_number_recall,
                args=(employee_number_recall_key,),
            ).strip()
            if st.session_state.get(employee_number_recall_key) == _employee_name_key(
                employee_name
            ):
                st.caption(
                    "Employee number recalled from this employee's last confirmed report."
                )
            employee_home_bu = _employee_home_business_unit(account)
            home_bu_display_key = f"expense_employee_home_bu_display_{account_token}"
            # Derived, not entered: the value is recomputed and written back on
            # every rerun so the disabled field cannot go stale after an account
            # change. A disabled widget still needs a session value -- rendering
            # it without one shows an empty box and the operator has no way to
            # correct it, because the field is (correctly) not editable.
            st.session_state[home_bu_display_key] = employee_home_bu
            st.text_input(
                "Employee Home Business Unit",
                disabled=True,
                key=home_bu_display_key,
                help="Filled automatically from the selected ENFRA account.",
            )
        with detail_columns[1]:
            report_date = st.date_input(
                "Report date *",
                key=f"expense_report_date_{account_token}",
                format="MM/DD/YYYY",
            )
            approver_name_key = f"expense_approver_name_{account_token}"
            approver_email_key = f"expense_approver_email_{account_token}"
            approver_recall_key = f"expense_approver_recalled_{account_token}"
            remembered_approvers = tuple(expense_approvers(account))
            current_approver = str(
                st.session_state.get(approver_name_key, "") or ""
            ).strip()
            current_approver_email = str(
                st.session_state.get(approver_email_key, "") or ""
            ).strip()
            fallback_key = f"expense_approver_fallback_{account_token}"
            fallback = st.session_state.get(fallback_key)
            if not (
                isinstance(fallback, tuple)
                and len(fallback) == 2
                and all(isinstance(value, str) for value in fallback)
            ):
                fallback = None
            if fallback is None and current_approver and current_approver_email:
                fallback = (current_approver, current_approver_email)
                st.session_state[fallback_key] = fallback
            # The CURRENT value is prepended, not merely offered. This selectbox
            # uses index=None with accept_new_options=True, so a name the
            # operator typed -- or the RRH default seeded from config, which has
            # never been "confirmed" and so is absent from expense_approvers()
            # -- exists only in session_state. Building the option list from the
            # remembered pairs alone drops that value out of options on the very
            # next rerun and the field empties itself.
            approver_names, approver_identities, current_option = _approver_options(
                current_approver,
                current_approver_email,
                remembered_approvers,
                fallback,
            )
            if current_approver and current_option != current_approver:
                st.session_state[approver_name_key] = current_option
            selected_approver_option = str(st.selectbox(
                "Contract administrator / approver name *",
                approver_names,
                index=None,
                key=approver_name_key,
                placeholder="Type or select an approver",
                accept_new_options=True,
                filter_mode="fuzzy",
                help=(
                    "Start typing to search approvers confirmed for this account, "
                    "or enter a new name. Selecting a remembered name fills the email."
                ),
                on_change=_recall_approver_email,
                args=(
                    approver_name_key,
                    approver_email_key,
                    approver_recall_key,
                    approver_identities,
                ),
            ) or "").strip()
            selected_identity = approver_identities.get(selected_approver_option)
            approver_name = (
                selected_identity[0]
                if selected_identity is not None
                else selected_approver_option
            )
            approver_email = st.text_input(
                "Contract administrator / approver email *",
                key=approver_email_key,
                on_change=_clear_approver_recall,
                args=(approver_recall_key,),
            ).strip()
            if st.session_state.get(approver_recall_key) == _approver_identity_key(
                approver_name, approver_email
            ):
                st.caption("Approver email recalled from this account's confirmed history.")

        mail_destination = st.radio(
            "Where should the reimbursement check be mailed? *",
            tuple(_MAIL_LABELS),
            format_func=lambda value: _MAIL_LABELS[value],
            horizontal=True,
            key=f"expense_mail_destination_{account_token}",
        )
        satellite_office = ""
        if mail_destination == "satellite":
            satellite_office = st.text_input(
                "Satellite office *",
                key=f"expense_satellite_office_{account_token}",
            ).strip()

        # Non-RRH accounts never see this control, so the default has to be a
        # real value rather than 0 or None: _default_job_allocation formats it
        # as "%02dAMA" for RRH only, but the variable is read unconditionally
        # below and a None here becomes a TypeError on a non-RRH account.
        service_year = 1
        if contracts.is_rrh(account):
            service_year = int(
                st.selectbox(
                    "RRH service year *",
                    tuple(range(1, 10)),
                    key=f"expense_service_year_{account_token}",
                    help=(
                        "The service year sets the editable Account / Cost Type default: "
                        "year 1 = 01AMA, year 2 = 02AMA, and so on."
                    ),
                )
            )
            st.caption(
                f"Receipt coding starts with 695400022 · {service_year:02d}AMA · 5490. "
                "Each receipt can be changed independently."
            )
    # Computed outside the panel because it feeds BOTH the receipt lines and the
    # mileage rows, which render further down regardless of whether the details
    # block collapsed. It is a seed, not a value: _seed_job_allocation only
    # applies it where the operator has not overridden the field.
    allocation_seed = _default_job_allocation(account, service_year)

    # employee_signature_confirmed is deliberately False here and replaced below
    # via dataclasses.replace once the checkbox has rendered. The details object
    # is needed earlier (for warnings and the signature preview name), and
    # ExpenseReportDetails is frozen, so this is a two-phase build rather than a
    # mutation. Do not "simplify" by moving construction after the checkbox --
    # employee_name is what decides whether the checkbox renders at all.
    details = ExpenseReportDetails(
        account=account,
        employee_name=employee_name,
        employee_number=employee_number,
        employee_home_bu=employee_home_bu,
        report_date=report_date,
        approver_name=approver_name,
        approver_email=approver_email,
        mail_destination=mail_destination,
        satellite_office=satellite_office,
        employee_signature_confirmed=False,
    )

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num">3</div>
            <p class="step-title">Review expenses and coding</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Every required value stays with the receipt or mileage entry it belongs "
        "to. Job number, Account / Cost Type, and Cost Code are prefilled but editable."
    )
    items: list[ExpenseItem] = []
    for index, (receipt_id, filename, file_bytes) in enumerate(unique_uploads, 1):
        receipt_items = _render_receipt(
            index=index,
            receipt_id=receipt_id,
            filename=filename,
            file_bytes=file_bytes,
            analysis=analyses[receipt_id],
            account=account,
            allocation_seed=allocation_seed,
        )
        items.extend(receipt_items)

    mileage_items = _render_mileage_entries(
        account=account,
        account_token=account_token,
        report_date=report_date,
        allocation_seed=allocation_seed,
    )

    total = total_reimbursement(items, mileage_items)
    summary_columns = st.columns(3)
    summary_columns[0].metric("Receipts", len(unique_uploads))
    summary_columns[1].metric("Mileage entries", len(mileage_items))
    summary_columns[2].metric("Total reimbursement", f"${total:,.2f}")

    review_warnings = expense_report_warnings(details, items, mileage_items)
    if review_warnings:
        st.warning(
            "Review before sending: "
            + "; ".join(warning.rstrip(". ") for warning in review_warnings)
            + "."
        )

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num yellow">4</div>
            <p class="step-title">Generate the report and approval email</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "The Excel file contains the completed official form and, when receipts "
        "are present, a printable RECEIPTS worksheet. The PDF places the form "
        "first and each receipt after it. Windows Outlook receives that PDF in "
        "the draft; web and iPad mail routes provide a prefilled email and an "
        "attachment reminder. Nothing is sent automatically."
    )

    signature_confirmed = False
    if employee_name:
        try:
            signature_preview = employee_signature_png(employee_name)
        except ExpenseReportError as exc:
            st.error(str(exc))
        else:
            confirmation_key = f"expense_signature_confirmed_{account_token}"
            confirmed_name_key = f"expense_signature_confirmed_name_{account_token}"
            # The employee attests to a signature image that is embedded at C66
            # of the form the approver receives. If the name changes after the
            # box was ticked, the tick must NOT carry over: it would otherwise
            # attest to a signature the operator never saw. The keys are
            # account-scoped and both survive a workflow switch through the
            # draft mirror, so this comparison stays meaningful across it.
            if (
                st.session_state.get(confirmation_key)
                and st.session_state.get(confirmed_name_key)
                and st.session_state.get(confirmed_name_key) != employee_name
            ):
                st.session_state[confirmation_key] = False
            signature_columns = st.columns([1, 2])
            with signature_columns[0]:
                st.image(signature_preview, width=320)
                st.caption(f"Printed name: {employee_name}")
            with signature_columns[1]:
                signature_confirmed = st.checkbox(
                    "I confirm this generated signature represents me and will "
                    "review it again before sending the Outlook draft.",
                    key=confirmation_key,
                )
                if signature_confirmed:
                    st.session_state[confirmed_name_key] = employee_name
    details = replace(
        details,
        employee_signature_confirmed=signature_confirmed,
    )
    problems = validate_expense_report(details, items, mileage_items)
    if problems:
        st.warning(
            "Before generating: "
            + "; ".join(problem.rstrip(". ") for problem in problems)
            + "."
        )

    # Content fingerprint over every reviewed input INCLUDING the receipt bytes.
    # It is what stops a stale package from being downloaded after an edit: the
    # render gate at the bottom of this function compares it again, so an edited
    # report cannot hand the approver a PDF built from the previous values.
    # Weakening it to hash only the "important" fields silently reopens that.
    signature = expense_report_signature(details, items, mileage_items)
    generated_signature = str(st.session_state.get("expense_generated_signature", ""))
    if generated_signature and generated_signature != signature:
        st.warning(
            "A report detail changed. Generate again to refresh the files and email draft."
        )

    if st.button(
        "Generate expense report and email draft",
        type="primary",
        width="stretch",
        disabled=bool(problems),
        key="generate_expense_package",
    ):
        with st.spinner("Creating the Excel report, receipt packet, and email draft…"):
            # This handler covers WORKBOOK failure only, and discarding the
            # package is correct here because none was produced. A PDF renderer
            # outage is NOT handled here: build_expense_package catches it
            # internally and returns a package with pdf_bytes=None plus
            # pdf_error, which drives the Excel-only fallback below. Hoisting
            # the PDF conversion out to this level is the plausible-looking
            # wrong change -- it is exactly what used to happen, and it made the
            # Excel-only fallback unreachable by construction, throwing away
            # every receipt line, allocation and mileage row the operator had
            # entered. See the 2026-08-12 hardening notes, section 4.1.
            try:
                package = build_expense_package(
                    details,
                    items,
                    mileage_items=mileage_items,
                )
            except Exception as exc:
                st.session_state["expense_generation_error"] = str(exc)[:500]
                st.session_state.pop("expense_generated_package", None)
                st.session_state.pop("expense_generated_eml", None)
                st.session_state.pop("expense_generated_signature", None)
            else:
                # A failed .eml build must not cost the operator the package:
                # the error is recorded separately and the report is still
                # stored, so the iPhone/iPad share route (which never touches
                # this code) and both file downloads keep working. Raising or
                # discarding here would turn an Outlook-only problem into total
                # re-entry of the whole report.
                eml_bytes = b""
                email_error = ""
                if package.pdf_bytes:
                    try:
                        eml_bytes = _build_expense_eml(details, package)
                    except Exception as exc:
                        email_error = str(exc)[:500]
                st.session_state["expense_generated_package"] = package
                st.session_state["expense_generated_eml"] = eml_bytes
                st.session_state["expense_generated_signature"] = signature
                if email_error:
                    st.session_state["expense_email_error"] = email_error
                else:
                    st.session_state.pop("expense_email_error", None)
                st.session_state.pop("expense_generation_error", None)
                # Memory is written only on a SUCCESSFUL generation. A half-typed
                # approver or a mis-selected job number never reaches the store,
                # so the next report's prefill can only ever be a combination
                # the operator actually carried through to a finished package.
                _remember_profile(
                    browser_token=browser_token,
                    details=details,
                    approver_context_id=report_memory_context,
                    # First receipt line, else first mileage row, else the seed.
                    # Receipts win because a split receipt's first line is the
                    # one the operator most likely re-coded by hand; the seed is
                    # the last resort so the stored coding is never empty.
                    allocation=(
                        items[0].allocation
                        if items
                        else mileage_items[0].allocation
                        if mileage_items
                        else allocation_seed
                    ),
                )

    generation_error = str(st.session_state.get("expense_generation_error", "") or "")
    if generation_error:
        st.error(f"The expense package could not be generated: {generation_error}")
    email_error = str(st.session_state.get("expense_email_error", "") or "")
    if email_error:
        st.error(
            "The attached-PDF Outlook draft could not be created: "
            f"{email_error} The iPhone/iPad share option can still pass the "
            "generated PDF directly to Mail or Outlook."
        )

    # Both halves of this gate are required. The isinstance check survives a
    # session restored across a deploy holding some other object under that key;
    # the fingerprint comparison is what suppresses a package built from values
    # the operator has since edited. Dropping either one lets a download button
    # appear that hands the approver the wrong document, with no visible symptom
    # -- the file name and the page look identical either way.
    package = st.session_state.get("expense_generated_package")
    if (
        isinstance(package, ExpensePackage)
        and st.session_state.get("expense_generated_signature") == signature
    ):
        _render_generated_package(
            details=details,
            package=package,
            eml_bytes=st.session_state.get("expense_generated_eml", b""),
        )


def _receipt_analysis(
    receipt_id: str,
    filename: str,
    file_bytes: bytes,
    *,
    index: int,
) -> ReceiptAnalysis:
    """Read one receipt once, caching by content hash.

    Returns a populated ``ReceiptAnalysis`` on success and an EMPTY one on any
    failure -- never raises, never blocks. The fields beside the receipt stay
    required either way, so a receipt the model cannot read is still completable
    by hand; the caller surfaces the stored error separately.
    """
    analysis_key = f"expense_receipt_analysis_{receipt_id}"
    error_key = f"expense_receipt_error_{receipt_id}"
    # Both keys are checked because a FAILURE must be sticky too. Without the
    # error-key half, every rerun -- a keystroke in any field on the page --
    # would re-run the vision call for a receipt that already failed, spending
    # money and a multi-second spinner per keypress. The retry button clears
    # both keys, which is the only supported way back to a fresh read.
    if analysis_key not in st.session_state and error_key not in st.session_state:
        with st.spinner(f"Reading receipt {index} of the upload…"):
            try:
                st.session_state[analysis_key] = analyze_receipt(file_bytes, filename)
            except Exception as exc:
                st.session_state[error_key] = str(exc)[:400]
    result = st.session_state.get(analysis_key)
    return result if isinstance(result, ReceiptAnalysis) else ReceiptAnalysis()


def _render_receipt(
    *,
    index: int,
    receipt_id: str,
    filename: str,
    file_bytes: bytes,
    analysis: ReceiptAnalysis,
    account: str,
    allocation_seed: ExpenseAllocation,
) -> list[ExpenseItem]:
    """Render one receipt card and return its reimbursement lines.

    Returns one ``ExpenseItem`` normally, or ``line_count`` items when the
    operator has split the receipt. Every returned item shares
    ``source_receipt_id`` and carries the same ``file_bytes``, which is what
    lets the workbook attach the image exactly once; ``receipt_id`` is suffixed
    per line so the lines stay individually addressable.

    Returns items even when they are incomplete -- validation is the caller's
    job, and a partially filled line must still round-trip through the widgets.
    """
    # 12 hex characters of the content hash. Short enough to keep widget keys
    # readable, long enough that two receipts in one report will not collide.
    # It is a PREFIX of receipt_id on purpose: _clear_removed_receipts matches
    # on either form, so both the token-keyed fields and the receipt_id-keyed
    # analysis/preview entries are removed by the same pass.
    token = receipt_id[:12]
    _seed_receipt_fields(token, analysis)
    error_key = f"expense_receipt_error_{receipt_id}"
    automatic_error = str(st.session_state.get(error_key, "") or "")

    merchant_key = f"expense_merchant_{token}"
    date_key = f"expense_date_{token}"
    description_key = f"expense_description_{token}"
    amount_key = f"expense_amount_{token}"
    section_key = f"expense_section_{token}"
    contact_key = f"expense_contact_{token}"
    selected_item_indices, calculated_item_amount = _sync_detected_item_amount(
        token,
        analysis,
        amount_key,
    )

    title_amount = str(st.session_state.get(amount_key, "") or "").strip()
    title_merchant = str(st.session_state.get(merchant_key, "") or "").strip()
    title = f"Receipt {index} · {title_merchant or Path(filename).name}"
    if title_amount:
        title += f" · ${title_amount.lstrip('$')}"
    # html.escape on BOTH interpolations is mandatory, not stylistic: the title
    # carries the merchant name read off the receipt by the model, and filename
    # is chosen by whoever took the photo. This block is emitted with
    # unsafe_allow_html, so an unescaped apostrophe or angle bracket in a
    # merchant name would break the card's markup at best.
    st.markdown(
        f'<div class="request-summary"><strong>{html.escape(title)}</strong>'
        f'<span class="request-summary-detail">{html.escape(filename)}</span></div>',
        unsafe_allow_html=True,
    )

    preview_column, fields_column = st.columns([1, 2])
    with preview_column:
        preview_key = f"expense_preview_{receipt_id}"
        if preview_key not in st.session_state:
            try:
                st.session_state[preview_key] = receipt_preview_bytes(file_bytes, filename)
            except Exception as exc:
                # Cache the EMPTY result, not just the success. A receipt this
                # renderer cannot handle (an exotic PDF, a corrupt HEIC) would
                # otherwise re-raise and re-render on every keystroke on the
                # page. A missing thumbnail is cosmetic; the original bytes are
                # still what goes into the workbook and the PDF packet.
                st.session_state[preview_key] = b""
                st.caption(f"Preview unavailable: {str(exc)[:160]}")
        preview = st.session_state.get(preview_key, b"")
        if preview:
            st.image(preview, caption=f"Receipt {index}", width="stretch")
        if st.button(
            "Remove this receipt",
            key=f"expense_remove_receipt_{token}",
            width="stretch",
        ):
            _remove_receipt_from_draft(receipt_id)
            st.rerun()
        if automatic_error:
            st.warning(
                "The tool could not read this receipt automatically. The fields "
                "beside it are still required and can be completed manually."
            )
            if st.button("Try reading this receipt again", key=f"retry_receipt_{token}"):
                st.session_state.pop(error_key, None)
                st.session_state.pop(f"expense_receipt_analysis_{receipt_id}", None)
                st.rerun()
        elif analysis.confidence in {"low", "medium"}:
            st.warning(f"Automatic reading confidence: {analysis.confidence}. Verify every value.")
        if analysis.review_notes:
            for note in analysis.review_notes:
                st.caption(f"Review: {note}")
        if analysis.tax_amount:
            st.caption(f"Tax printed on receipt: ${analysis.tax_amount}")
        # A foreign-currency receipt is an ERROR, not a warning: the number
        # printed on it is not the reimbursable amount, and every downstream
        # total treats the entered value as dollars. Nothing converts rates
        # here, deliberately -- the approved USD figure is the employee's to
        # supply. Softening this to a caption reintroduces a silent, wrong total.
        if analysis.currency and analysis.currency != "USD":
            st.error(
                f"Receipt currency appears to be {analysis.currency}. Enter the "
                "approved U.S.-dollar reimbursement amount."
            )

    items: list[ExpenseItem] = []
    with fields_column:
        merchant = st.text_input(
            "Merchant",
            key=merchant_key,
            help=(
                "Used as a receipt label; the Description / business purpose is "
                "what appears on the form."
            ),
        ).strip()
        # value=None is passed ONLY on the first render, and only when nothing
        # has been seeded. st.date_input defaults to TODAY when value is
        # omitted, which would silently stamp every unread receipt with the
        # current date and make a required field look answered. Passing value=
        # alongside an existing session value is a Streamlit warning and loses
        # the operator's edit, hence the conditional rather than an unconditional
        # value=st.session_state.get(...).
        date_kwargs = {"key": date_key, "format": "MM/DD/YYYY"}
        if date_key not in st.session_state:
            date_kwargs["value"] = None
        transaction_date = st.date_input("Transaction date *", **date_kwargs)
        _render_detected_receipt_items(
            token=token,
            analysis=analysis,
            selected_indices=selected_item_indices,
            calculated_amount=calculated_item_amount,
            amount_key=amount_key,
        )
        split_receipt = st.toggle(
            "Split this receipt into multiple reimbursement lines",
            key=f"expense_split_{token}",
            help=(
                "Use this when one receipt contains reimbursable items with "
                "different business purposes, sections, or job coding. The "
                "receipt image will still be attached only once."
            ),
        )
        line_count = 1
        if split_receipt:
            line_count = int(
                st.number_input(
                    "Number of reimbursement lines",
                    min_value=2,
                    max_value=MAX_MISCELLANEOUS_ITEMS,
                    value=2,
                    step=1,
                    key=f"expense_split_count_{token}",
                    help=(
                        "Create one line for each distinct reimbursable purpose "
                        "or coding combination. Nonbusiness items need no line."
                    ),
                )
            )
            st.caption(
                "Enter only the applicable amount on each line. Replace the "
                "first line's full-receipt prefill and do not enter nonbusiness items."
            )

        # Line 1 reuses the bare token so the un-split receipt and the first line
        # of a split receipt are THE SAME widget keys. That is what makes the
        # split toggle non-destructive in both directions: turning it on keeps
        # the amount and description already entered, and turning it off keeps
        # line 1 rather than resetting to the automatic prefill. It also means
        # the detected-item sync below writes to line 1, which is intended.
        for line_index in range(1, line_count + 1):
            line_token = token if line_index == 1 else f"{token}_line_{line_index}"
            if line_index > 1:
                _seed_additional_receipt_line_fields(line_token)
            line_description_key = f"expense_description_{line_token}"
            line_amount_key = f"expense_amount_{line_token}"
            line_section_key = f"expense_section_{line_token}"
            line_contact_key = f"expense_contact_{line_token}"
            if line_count > 1:
                st.markdown(f"**Reimbursement line {line_index}**")
            description = st.text_input(
                "Description / business purpose *",
                key=line_description_key,
                help=(
                    "State the actual business purpose without accounting codes. "
                    "For a split receipt, describe only this reimbursement line."
                ),
            ).strip()
            amount = st.text_input(
                "Reimbursable amount *",
                key=line_amount_key,
                help=(
                    "Enter only the business-reimbursable portion for this line. "
                    "Detected item selections update the first line automatically. "
                    "You can still edit it for tax, tip, fees, currency conversion, "
                    "or a receipt-reading correction."
                ),
            ).strip()
            section = st.selectbox(
                "Expense section *",
                tuple(_SECTION_LABELS),
                format_func=lambda value: _SECTION_LABELS[value],
                key=line_section_key,
                help=(
                    "Entertainment requires a business purpose and contact name. "
                    "Ordinary travel, parking, supplies, and employee meals "
                    "normally remain Miscellaneous."
                ),
            )
            contact_name = ""
            if section == EXPENSE_SECTION_ENTERTAINMENT:
                contact_name = st.text_input(
                    "Entertainment contact name *",
                    key=line_contact_key,
                ).strip()

            st.markdown("**JDE coding for this reimbursement line**")
            allocation = _render_job_allocation_fields(
                prefix=f"expense_receipt_allocation_{line_token}",
                account=account,
                seed=allocation_seed,
            )
            items.append(
                ExpenseItem(
                    receipt_id=f"{receipt_id}:{line_index}",
                    source_receipt_id=receipt_id,
                    filename=filename,
                    file_bytes=file_bytes,
                    transaction_date=transaction_date,
                    description=description,
                    amount=amount,
                    section=section,
                    allocation=allocation,
                    merchant_name=merchant,
                    contact_name=contact_name,
                )
            )

    for line_index, item in enumerate(items, 1):
        receipt_problems = _receipt_visible_problems(index, item)
        if receipt_problems:
            line_label = (
                f"Receipt {index}, line {line_index}"
                if len(items) > 1
                else f"Receipt {index}"
            )
            st.warning(
                f"Needed for {line_label}: "
                + "; ".join(receipt_problems)
                + "."
            )

    # Split lines only. A single line legitimately exceeds the tool-read total
    # (tip written in by hand, a total the reader mis-scanned), so warning there
    # would train the operator to ignore the message. Strictly greater-than:
    # splitting a receipt into lines that sum to exactly the total is the normal
    # case and must stay silent.
    analyzed_total = parse_expense_amount(analysis.total_amount)
    reviewed_total = sum(
        (parse_expense_amount(item.amount) or 0 for item in items),
        0,
    )
    if len(items) > 1 and analyzed_total is not None and reviewed_total > analyzed_total:
        st.warning(
            f"The split lines total ${reviewed_total:,.2f}, which exceeds the "
            f"tool-read receipt total of ${analyzed_total:,.2f}. Verify the "
            "receipt and line amounts before generating."
        )
    return items


def _detected_item_entries(
    token: str,
    analysis: ReceiptAnalysis,
) -> list[tuple[int, str]]:
    """Return stable checkbox keys for the current detected item list.

    The key embeds a digest of position, description and amount, so re-reading
    the same receipt reproduces exactly the same keys and the operator's
    unchecked personal items survive a rerun. If a retry produces a DIFFERENT
    item list, the keys change and every item starts checked again -- which is
    the safe direction: a stale unchecked box against a re-read receipt would
    quietly drop a reimbursable line with the box appearing to say otherwise.

    The index is inside the digest so two identical rows on one receipt (two
    coffees at the same price) get distinct keys instead of sharing one
    checkbox.
    """
    entries: list[tuple[int, str]] = []
    for index, item in enumerate(analysis.line_items):
        digest = hashlib.sha256(
            f"{index}\0{item.description}\0{item.amount}".encode("utf-8")
        ).hexdigest()[:12]
        entries.append((index, f"expense_item_selected_{token}_{digest}"))
    return entries


def _selected_receipt_item_amount(
    analysis: ReceiptAnalysis,
    selected_indices: set[int],
) -> str:
    """Allocate the final charged total across the selected purchased items.

    When the receipt has tax, tip, discounts, or fees outside its item lines,
    proportional allocation makes all-selected equal the final charged total
    while a partial selection receives a fair share of those adjustments.

    Returns "" when nothing is selected or the result rounds to zero, which the
    caller treats as "no automatic amount" rather than as $0.00.

    ROUNDING IS ONE-SIDED ON PURPOSE. Each call quantizes independently with
    ROUND_HALF_UP, so selecting subsets one at a time can total a cent more than
    the charged total; the caller only ever writes ONE line's amount from this,
    and the split-line total check downstream catches a genuine overclaim. Do
    not "fix" it with a largest-remainder pass -- that needs the whole selection
    set at once and this function is called per-render for a single amount.

    Assumes item amounts and the charged total come from the same receipt read.
    An item list with no parseable amounts yields "" rather than dividing by
    zero: item_total > 0 guards the proportional branch, and a receipt whose
    total is missing falls back to the plain sum of selected items.
    """
    indexed_amounts = [
        (index, amount)
        for index, item in enumerate(analysis.line_items)
        if (amount := parse_expense_amount(item.amount)) is not None
    ]
    selected_amount = sum(
        (amount for index, amount in indexed_amounts if index in selected_indices),
        Decimal("0"),
    )
    if selected_amount <= 0:
        return ""
    item_total = sum((amount for _, amount in indexed_amounts), Decimal("0"))
    charged_total = parse_expense_amount(analysis.total_amount)
    calculated = selected_amount
    if charged_total is not None and item_total > 0:
        calculated = charged_total * selected_amount / item_total
    calculated = calculated.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{calculated:.2f}" if calculated > 0 else ""


def _sync_detected_item_amount(
    token: str,
    analysis: ReceiptAnalysis,
    amount_key: str,
) -> tuple[set[int], str]:
    """Update the editable amount only when detected-item selection changes.

    Returns the selected indices and the calculated amount so the renderer can
    describe the state without recomputing it. Writes ``amount_key`` at most
    once per rerun and MUST be called before that widget is instantiated.

    A single-item (or unitemized) receipt returns immediately with an empty
    selection: the item checkboxes are not rendered in that case, so treating
    the sole item as "selected" would let this overwrite an amount the operator
    typed with the model's total on every rerun.
    """
    if len(analysis.line_items) < 2:
        return set(), ""
    entries = _detected_item_entries(token, analysis)
    selected = {
        index
        for index, checkbox_key in entries
        if bool(st.session_state.get(checkbox_key, True))
    }
    calculated = _selected_receipt_item_amount(analysis, selected)
    fingerprint = hashlib.sha256(
        repr(
            (
                analysis.total_amount,
                tuple(
                    (item.description, item.amount)
                    for item in analysis.line_items
                ),
                tuple(sorted(selected)),
            )
        ).encode("utf-8")
    ).hexdigest()
    # The fingerprint is what separates "the operator changed the selection"
    # from "this is just another rerun". Without it the calculated value would
    # be written back on every rerun and a hand-typed correction -- for tax,
    # tip, a currency conversion, or a misread line -- could never survive a
    # keystroke anywhere else on the page. The fingerprint covers the analysis
    # as well as the selection so a re-read receipt also counts as a change.
    fingerprint_key = f"expense_item_selection_fingerprint_{token}"
    prior_fingerprint = st.session_state.get(fingerprint_key)
    current_amount = str(st.session_state.get(amount_key, "") or "").strip()
    if prior_fingerprint is None:
        # First sight of this receipt. _seed_receipt_fields has already put the
        # model's whole-receipt total in the field; replacing it with the
        # all-items-selected figure is the same number for a clean receipt and
        # the corrected one when the reader also found non-item charges. Any
        # OTHER pre-existing value is the operator's (restored from the draft
        # mirror after a workflow switch) and is left alone.
        if not current_amount or current_amount == analysis.total_amount:
            st.session_state[amount_key] = calculated
    elif prior_fingerprint != fingerprint:
        # A deliberate item-selection change supersedes the prior automatic or
        # manual amount; the resulting field remains editable afterward.
        st.session_state[amount_key] = calculated
    st.session_state[fingerprint_key] = fingerprint
    return selected, calculated


def _render_detected_receipt_items(
    *,
    token: str,
    analysis: ReceiptAnalysis,
    selected_indices: set[int],
    calculated_amount: str,
    amount_key: str,
) -> None:
    """Render item-level reimbursement choices for an itemized receipt.

    Renders nothing for a receipt with fewer than two detected items. The
    threshold must match ``_sync_detected_item_amount``'s exactly: rendering
    checkboxes the sync function ignores would give the operator a control that
    silently does nothing, and syncing without rendering would move the amount
    with no visible cause.
    """
    if len(analysis.line_items) < 2:
        return
    st.markdown("**Select the reimbursable receipt items**")
    st.caption(
        "All detected purchased items start selected. Uncheck personal or other "
        "nonreimbursable items; the reimbursable amount below recalculates."
    )
    for index, checkbox_key in _detected_item_entries(token, analysis):
        item = analysis.line_items[index]
        st.checkbox(
            f"{index + 1}. {item.description} — ${item.amount}",
            value=True,
            key=checkbox_key,
        )

    if not selected_indices:
        st.warning(
            "No detected receipt items are selected. Select a reimbursable item, "
            "or enter a corrected description and amount manually if the reader "
            "missed the applicable purchase. Otherwise remove this receipt."
        )
        return
    selected_count = len(selected_indices)
    current_amount = str(st.session_state.get(amount_key, "") or "").strip()
    allocation_note = (
        " Receipt-level tax, tip, discounts, and fees are allocated "
        "proportionally from the final charged total."
        if parse_expense_amount(analysis.total_amount) is not None
        else ""
    )
    if current_amount and current_amount != calculated_amount:
        st.caption(
            f"Selected {selected_count} of {len(analysis.line_items)} items; "
            f"calculated amount ${calculated_amount}. Your edited amount is "
            f"preserved until the selection changes.{allocation_note}"
        )
    else:
        st.caption(
            f"Selected {selected_count} of {len(analysis.line_items)} items; "
            f"reimbursable amount ${calculated_amount}.{allocation_note}"
        )


def _render_job_allocation_fields(
    *,
    prefix: str,
    account: str,
    seed: ExpenseAllocation,
) -> ExpenseAllocation:
    """Render the three JDE coding fields for one line and return them.

    ``prefix`` namespaces the widget keys and must be unique per reimbursement
    line and per mileage row -- two lines sharing a prefix share one set of
    controls and silently receive identical coding.

    Returns an ``ExpenseAllocation`` with ``job_number=""`` while the sentinel
    option is showing, which ``allocation_problems`` rejects. It never returns a
    guessed job number.
    """
    _seed_job_allocation(prefix, seed)
    options = tuple(job_numbers_for_contract(account))
    selectable = (_JOB_PLACEHOLDER, *options)
    # Membership guard, not defensive noise. The job catalog is filtered by
    # ACCOUNT while these keys are namespaced by receipt, so switching the
    # account leaves a stored job number that no longer appears in the options
    # tuple -- and st.selectbox with a session value outside its options is an
    # error, taking the whole page down mid-report. Falling back to the sentinel
    # forces a re-pick, which is the correct outcome: a job number from the
    # previous facility must not silently ride along on the new account.
    if st.session_state.get(f"{prefix}_job_number") not in selectable:
        st.session_state[f"{prefix}_job_number"] = _JOB_PLACEHOLDER

    coding_columns = st.columns(3)
    with coding_columns[0]:
        selected = st.selectbox(
            "Job number *",
            selectable,
            key=f"{prefix}_job_number",
            help=(
                "RRH normally uses 695400022 (O&M) or 695400023 (Startup). "
                "The selected description is exported as its numeric identifier."
            ),
        )
    with coding_columns[1]:
        account_cost_type = st.text_input(
            "Account / cost type *",
            key=f"{prefix}_account_cost_type",
        ).strip()
    with coding_columns[2]:
        cost_code = st.text_input(
            "Cost code *",
            key=f"{prefix}_cost_code",
        ).strip()
    return ExpenseAllocation(
        kind=ALLOCATION_JOB,
        job_number="" if selected == _JOB_PLACEHOLDER else selected,
        account_cost_type=account_cost_type,
        cost_code_or_wo_type=cost_code,
    )


def _render_mileage_entries(
    *,
    account: str,
    account_token: str,
    report_date: date,
    allocation_seed: ExpenseAllocation,
) -> list[MileageItem]:
    """Render the optional mileage block and return its rows.

    Returns ``[]`` when the toggle is off -- mileage is genuinely optional and a
    receipts-only report is the common case. Rows are returned even when
    incomplete; the caller validates. Keys are namespaced by ``account_token``
    and row index, so changing the account starts a clean mileage block rather
    than re-coding the previous facility's trips.
    """
    st.markdown("#### Mileage")
    include_mileage = st.toggle(
        "Include reimbursable business mileage",
        key=f"expense_include_mileage_{account_token}",
    )
    if not include_mileage:
        return []
    entry_count = int(
        st.number_input(
            "Number of mileage entries",
            min_value=1,
            max_value=MAX_MILEAGE_ITEMS,
            value=1,
            step=1,
            key=f"expense_mileage_count_{account_token}",
        )
    )
    entries: list[MileageItem] = []
    for index in range(1, entry_count + 1):
        prefix = f"expense_mileage_{account_token}_{index}"
        # Track-the-default protocol. The travel date follows the report date
        # while the operator has not touched it, and stops following the instant
        # they set it to anything else. The shadow key records what was last
        # offered as a default, which is the only way to distinguish "still the
        # default" from "the operator deliberately typed today's date". Without
        # it, either the row freezes on the first report date (wrong for a
        # corrected report date) or it overwrites a real travel date on every
        # rerun -- and the second failure is invisible until the form is read.
        prior_default = st.session_state.get(f"{prefix}_default_date")
        if (
            f"{prefix}_date" not in st.session_state
            or st.session_state.get(f"{prefix}_date") == prior_default
        ):
            st.session_state[f"{prefix}_date"] = report_date
        st.session_state[f"{prefix}_default_date"] = report_date

        st.markdown(
            f'<div class="request-summary"><strong>Mileage {index}</strong></div>',
            unsafe_allow_html=True,
        )
        date_column, miles_column = st.columns(2)
        with date_column:
            travel_date = st.date_input(
                "Travel date *",
                key=f"{prefix}_date",
                format="MM/DD/YYYY",
            )
        with miles_column:
            miles = st.number_input(
                "Business miles *",
                min_value=0.0,
                max_value=100000.0,
                step=0.1,
                format="%.2f",
                key=f"{prefix}_miles",
            )
        purpose_column, destination_column = st.columns(2)
        with purpose_column:
            purpose = st.text_input(
                "Mileage business purpose *",
                key=f"{prefix}_purpose",
            ).strip()
        with destination_column:
            destination = st.text_input(
                "Destination *",
                key=f"{prefix}_destination",
            ).strip()

        # Rates are selected by TRAVEL date, not report date -- the IRS changed
        # the business rate mid-year in 2026, so a June trip claimed in August
        # must still pay the June rate. A date outside every configured band
        # (including one past the last configured year end) yields None, and
        # this refuses rather than guessing: an invented rate on a reimbursement
        # form is a payroll error nobody would catch downstream.
        rate = irs_business_mileage_rate(travel_date)
        if rate is None:
            st.error(
                f"The IRS business-mileage rate for {travel_date:%Y-%m-%d} "
                "has not been configured yet."
            )
        else:
            reimbursement = (parse_mileage(miles) or 0) * rate
            st.caption(
                f"IRS business rate: ${rate} per mile · "
                f"Calculated reimbursement: ${reimbursement:,.2f}"
            )
        allocation = _render_job_allocation_fields(
            prefix=f"{prefix}_allocation",
            account=account,
            seed=allocation_seed,
        )
        entry = MileageItem(
            entry_id=f"{account_token}-{index}",
            transaction_date=travel_date,
            purpose=purpose,
            destination=destination,
            miles=miles,
            allocation=allocation,
        )
        visible = _mileage_visible_problems(index, entry)
        if visible:
            st.warning("Needed for this mileage entry: " + "; ".join(visible) + ".")
        entries.append(entry)
    return entries


def _default_job_allocation(account: str, service_year: int) -> ExpenseAllocation:
    """Return the starting JDE coding for one account, never a guess.

    RRH gets the full verified triple. Every other account gets a job number
    only when the catalog leaves exactly ONE possibility -- with two or more,
    picking the first would be a coin flip that renders as a confidently
    pre-filled field, and the operator has no cue that it was invented. Blank
    means blank on purpose: allocation_problems blocks generation until it is
    answered.
    """
    if contracts.is_rrh(account):
        return ExpenseAllocation(
            kind=ALLOCATION_JOB,
            job_number=_RRH_DEFAULT_JOB,
            account_cost_type=(
                f"{service_year:02d}{_RRH_ACCOUNT_COST_TYPE_SUFFIX}"
            ),
            cost_code_or_wo_type=_RRH_DEFAULT_COST_CODE,
        )
    options = tuple(job_numbers_for_contract(account))
    return ExpenseAllocation(
        kind=ALLOCATION_JOB,
        job_number=options[0] if len(options) == 1 else "",
    )


def _employee_home_business_unit(account: str) -> str:
    # The approved Dane RRH report is authoritative: RRH employees use home
    # business unit 695 even though the user-facing account name is RRH.
    return "695" if contracts.is_rrh(account) else account.strip()


def _employee_name_key(name: object) -> str:
    """Normalize a person's name for equality only -- never for display.

    Collapses runs of whitespace and casefolds, so "  dane  EXAMPLE " and "Dane
    Example" are the same person. Used to pair a remembered employee number or
    approver email with the name currently in the field; comparing raw strings
    there means a stray trailing space silently loses the recall.
    """
    return " ".join(str(name or "").split()).casefold()


def _recall_employee_number_for_name(
    browser_token: str,
    account: str,
    employee_name_key: str,
    employee_number_key: str,
    recall_marker_key: str,
) -> None:
    """Replace a stale number when the employee identity changes.

    Runs as the employee-name widget's ``on_change``, i.e. BEFORE the next
    render, which is the only point where writing the employee-number widget
    key is legal. Moving this logic inline into the render pass would be a
    post-render write and would be discarded.
    """
    employee_name = str(st.session_state.get(employee_name_key, "") or "")
    remembered = remembered_expense_employee_number(
        browser_token,
        account,
        employee_name,
    )
    # A number belongs to one employee. Leaving the prior employee's value in
    # place when the name changes is a more dangerous default than a blank.
    st.session_state[employee_number_key] = remembered
    if remembered:
        st.session_state[recall_marker_key] = _employee_name_key(employee_name)
    else:
        st.session_state.pop(recall_marker_key, None)


def _clear_employee_number_recall(recall_marker_key: str) -> None:
    """Stop labeling a number as recalled after the operator edits it."""
    st.session_state.pop(recall_marker_key, None)


def _approver_identity_key(name: str, email: str) -> str:
    return f"{_employee_name_key(name)}\0{str(email or '').strip().casefold()}"


def _approver_options(
    current_value: str,
    current_email: str,
    remembered: tuple[tuple[str, str], ...],
    fallback: tuple[str, str] | None,
) -> tuple[tuple[str, ...], dict[str, tuple[str, str]], str]:
    """Build unambiguous options while retaining typed and seeded identities."""
    identities: list[tuple[str, str]] = []
    seen_identities: set[str] = set()
    for raw_name, raw_email in (*remembered, *((fallback,) if fallback else ())):
        name = " ".join(str(raw_name or "").split())
        email = str(raw_email or "").strip().lower()
        identity_key = _approver_identity_key(name, email)
        if name and email and identity_key not in seen_identities:
            seen_identities.add(identity_key)
            identities.append((name, email))

    name_counts: dict[str, int] = {}
    for name, _email in identities:
        key = _employee_name_key(name)
        name_counts[key] = name_counts.get(key, 0) + 1

    by_option: dict[str, tuple[str, str]] = {}
    option_for_identity: dict[str, str] = {}
    for name, email in identities:
        option = (
            f"{name} — {email}"
            if name_counts[_employee_name_key(name)] > 1
            else name
        )
        by_option[option] = (name, email)
        option_for_identity[_approver_identity_key(name, email)] = option

    cleaned_current = " ".join(str(current_value or "").split())
    if cleaned_current in by_option:
        current_option = cleaned_current
    else:
        current_option = option_for_identity.get(
            _approver_identity_key(cleaned_current, current_email),
            cleaned_current,
        )
        if cleaned_current and current_option == cleaned_current:
            by_option[current_option] = (
                cleaned_current,
                str(current_email or "").strip().lower(),
            )

    options: list[str] = []
    for option in (current_option, *by_option):
        if option and option not in options:
            options.append(option)
    return tuple(options), by_option, current_option


def _recall_approver_email(
    approver_name_key: str,
    approver_email_key: str,
    recall_marker_key: str,
    identities: dict[str, tuple[str, str]],
) -> None:
    """Fill the paired email or clear a stale one when the name changes.

    Name and email are ONE identity. Sending a report to the previous
    approver's address under a newly chosen name is the failure this prevents,
    so an unrecognised name blanks the email rather than leaving it.

    Seeded identities are included alongside confirmed history, so re-selecting
    the configured RRH approver restores its paired email as well.
    """
    selected = str(st.session_state.get(approver_name_key, "") or "")
    identity = identities.get(selected)
    if identity is not None:
        name, email = identity
        st.session_state[approver_email_key] = email
        st.session_state[recall_marker_key] = _approver_identity_key(name, email)
        return
    st.session_state[approver_email_key] = ""
    st.session_state.pop(recall_marker_key, None)


def _clear_approver_recall(recall_marker_key: str) -> None:
    """Stop labeling an approver email as recalled after a manual edit."""
    st.session_state.pop(recall_marker_key, None)


def _seed_profile(browser_token: str, account: str) -> dict[str, str]:
    """Seed this account's step-2 fields from device memory, once per account.

    Assumes it is called before any of those widgets renders. Returns the raw
    remembered profile; the return value is currently unused by the caller and
    is kept because it is the only accessor that already holds it.

    Every write goes through ``setdefault``, so a value the operator has already
    typed -- or one restored from the draft mirror after a workflow switch -- is
    never overwritten. Memory is a convenience: an unavailable store yields an
    empty profile and the fields simply render blank.
    """
    profile = remembered_expense_profile(browser_token, account)
    # Must match the derivation in render_expense_workflow exactly; see the
    # comment there. Duplicated rather than passed in so this function can be
    # called with an account alone.
    account_token = hashlib.sha256(account.encode("utf-8")).hexdigest()[:10]
    # Guarded by a marker, not by "are the fields empty". Re-seeding whenever a
    # field looks empty would make a field the operator deliberately CLEARED
    # refill itself on the next rerun -- unclearable, with no error.
    seed_key = f"expense_profile_seeded_{account_token}"
    if not st.session_state.get(seed_key):
        employee_name = profile.get("employee_name") or remembered_device_account_manager(
            browser_token, account
        )
        defaults = {
            f"expense_employee_name_{account_token}": employee_name,
            f"expense_employee_number_{account_token}": profile.get("employee_number", ""),
            # NOTE: the container runs in UTC, so late-evening US filing can
            # seed tomorrow's date. It is an editable default, and every date
            # comparison downstream is a warning rather than a block.
            f"expense_report_date_{account_token}": date.today(),
            f"expense_approver_name_{account_token}": (
                profile.get("approver_name")
                or (RRH_APPROVER_NAME if contracts.is_rrh(account) else "")
            ),
            f"expense_approver_email_{account_token}": (
                profile.get("approver_email")
                or (RRH_APPROVER_EMAIL if contracts.is_rrh(account) else "")
            ),
            f"expense_mail_destination_{account_token}": (
                profile.get("mail_destination")
                if profile.get("mail_destination") in _MAIL_LABELS
                else "home"
            ),
            f"expense_satellite_office_{account_token}": profile.get(
                "satellite_office", ""
            ),
        }
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)
        if employee_name and profile.get("employee_number"):
            st.session_state.setdefault(
                f"expense_employee_number_recalled_for_{account_token}",
                _employee_name_key(employee_name),
            )
        st.session_state[seed_key] = True
    return profile


def _seed_receipt_fields(token: str, analysis: ReceiptAnalysis) -> None:
    """Seed one receipt's fields: blanks first, then the model's reading.

    Two passes on purpose. The blank pass gives every widget a defined starting
    value so the fields render even for a receipt that could not be read. The
    AI pass then fills only keys that are still empty and only from non-empty
    values, and marks itself done, so a re-read (or an ordinary rerun) can never
    overwrite something the operator typed.

    Note the transaction date is seeded ONLY in the AI pass -- there is no blank
    default for it, because a date widget with no session value is what lets the
    caller pass ``value=None`` and leave the field visibly unanswered.
    """
    defaults = {
        f"expense_merchant_{token}": "",
        f"expense_description_{token}": "",
        f"expense_amount_{token}": "",
        f"expense_section_{token}": EXPENSE_SECTION_MISC,
        f"expense_contact_{token}": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    seeded_key = f"expense_ai_seeded_{token}"
    if not st.session_state.get(seeded_key) and any(
        (
            analysis.merchant_name,
            analysis.transaction_date,
            analysis.total_amount,
            analysis.suggested_description,
        )
    ):
        ai_values = {
            f"expense_merchant_{token}": analysis.merchant_name,
            f"expense_date_{token}": analysis.transaction_date,
            f"expense_description_{token}": analysis.suggested_description,
            f"expense_amount_{token}": analysis.total_amount,
            f"expense_section_{token}": analysis.expense_section_guess,
        }
        for key, value in ai_values.items():
            if value not in {None, ""} and st.session_state.get(key) in {None, ""}:
                st.session_state[key] = value
        st.session_state[seeded_key] = True


def _seed_additional_receipt_line_fields(line_token: str) -> None:
    """Seed a split line without copying the receipt-wide AI total.

    Lines 2..n start EMPTY. Copying the receipt total onto each line would give
    a plausible-looking prefill that double-claims the receipt if the operator
    accepts it -- the reason line 1 carries the prefill and the caption tells
    the operator to replace it.
    """
    defaults = {
        f"expense_description_{line_token}": "",
        f"expense_amount_{line_token}": "",
        f"expense_section_{line_token}": EXPENSE_SECTION_MISC,
        f"expense_contact_{line_token}": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _seed_job_allocation(prefix: str, seed: ExpenseAllocation) -> None:
    """Refresh changing defaults without overwriting a manual receipt edit.

    Same track-the-default protocol as the mileage travel date: a shadow
    ``_prior_default_*`` key records what was last offered, so a field still
    holding the previous default follows a new one (switching RRH service year
    from 1 to 2 moves every untouched Account / Cost Type to 02AMA) while a
    field the operator typed over stays put.

    Plain ``setdefault`` is the tempting simplification and is WRONG here: the
    service year and the account can both change after these keys exist, and
    setdefault would freeze every receipt on the first account's coding with no
    indication that the displayed value no longer matches the selected year.
    """
    defaults = {
        "job_number": seed.job_number or _JOB_PLACEHOLDER,
        "account_cost_type": seed.account_cost_type,
        "cost_code": seed.cost_code_or_wo_type,
    }
    for suffix, value in defaults.items():
        key = f"{prefix}_{suffix}"
        prior_key = f"{prefix}_prior_default_{suffix}"
        prior_default = st.session_state.get(prior_key)
        if key not in st.session_state or st.session_state.get(key) == prior_default:
            st.session_state[key] = value
        st.session_state[prior_key] = value


def _remember_profile(
    *,
    browser_token: str,
    details: ExpenseReportDetails,
    approver_context_id: str,
    allocation: ExpenseAllocation,
) -> None:
    """Record the confirmed profile and approver after a successful generation.

    The profile is scoped to (device, account) and the approver to the account,
    so one facility's administrator can never be offered on another's report.
    Both stores swallow their own failures -- memory is a convenience and must
    never take down a report the operator has already generated.
    """
    record_expense_profile(
        device_token=browser_token,
        account=details.account,
        values={
            "employee_name": details.employee_name,
            "employee_number": details.employee_number,
            "employee_home_bu": details.employee_home_bu,
            "approver_name": details.approver_name,
            "approver_email": details.approver_email,
            "mail_destination": details.mail_destination,
            "satellite_office": details.satellite_office,
            "allocation_kind": allocation.kind,
            "job_number": allocation.job_number,
            "service_center": allocation.service_center,
            "account_cost_type": allocation.account_cost_type,
            "cost_code_or_wo_type": allocation.cost_code_or_wo_type,
            "work_order_number": allocation.work_order_number,
            "company_number": allocation.company_number,
            "department_number": allocation.department_number,
            "ou_number": allocation.ou_number,
            "gl_account_number": allocation.gl_account_number,
        },
    )
    record_expense_approver(
        account=details.account,
        approver_name=details.approver_name,
        approver_email=details.approver_email,
        context_id=approver_context_id,
    )


def _build_expense_eml(details: ExpenseReportDetails, package: ExpensePackage) -> bytes:
    """Build the unsent Outlook draft carrying the combined PDF.

    Raises ``ExpenseReportError`` when there is no PDF: an .eml that promises an
    attachment and carries none is worse than no draft at all, and the caller
    turns the exception into a visible message while keeping the package.

    ``email_attachments_for_package`` returns the PDF ONLY. Do not add
    ``workbook_bytes`` -- the editable Excel is deliberately not part of the
    submission (2026-08-11 handoff, invariants 1 and 2).

    The subject and greeting here are duplicated in
    ``_expense_email_subject_and_body`` for the iOS route. They must stay
    identical: the destination is allowed to change the delivery mechanism, not
    the business content the approver reads.
    """
    if not package.pdf_bytes:
        raise ExpenseReportError(
            "The PDF is unavailable, so an approval email draft was not created."
        )
    subject = f"{details.employee_name} expense report - {details.report_date:%Y-%m-%d}"
    bullets = [
        ("Employee", details.employee_name),
        ("Account", details.account),
        (
            "Report date",
            f"{details.report_date:%B} {details.report_date.day}, {details.report_date:%Y}",
        ),
        ("Receipts", str(package.receipt_count)),
        ("Mileage entries", str(package.mileage_count)),
        ("Total reimbursement", f"${package.total:,.2f}"),
    ]
    first_name = details.approver_name.split()[0] if details.approver_name.split() else ""
    greeting = (
        f"Good afternoon, {first_name}. Please review and approve the attached expense report."
        if first_name
        else "Good afternoon. Please review and approve the attached expense report."
    )
    return build_eml(
        to=details.approver_email,
        subject=subject,
        bullets=bullets,
        attachments=email_attachments_for_package(package),
        greeting=greeting,
    )


def _render_generated_package(
    *,
    details: ExpenseReportDetails,
    package: ExpensePackage,
    eml_bytes: bytes,
) -> None:
    """Render the completed package: one primary email action, then extras.

    Exactly ONE primary completion action is on screen at a time -- the Outlook
    draft download or the iOS share component, never both. The Excel workbook,
    the raw PDF and the attachment-free mailto link stay inside the collapsed
    expander so they never compete with it.

    Assumes the caller has already checked that this package matches the current
    content fingerprint. Degrades to Excel-only when the PDF is missing, which
    is why the early-return branch below still renders a download.
    """
    st.success(
        "The expense report is ready. Review the files before sending them for approval."
    )
    # PDF-less degradation. The renderer is the one dependency that fails for
    # environmental reasons (LibreOffice timeout on a receipt-heavy workbook, an
    # unreachable Gotenberg), and when it does the operator must still leave
    # with the completed workbook rather than re-entering the whole report. No
    # email route is offered here on purpose -- every one of them claims to
    # carry the PDF.
    if not package.pdf_bytes:
        if package.pdf_error:
            st.warning(package.pdf_error)
        with st.expander("Other file and email options", expanded=False):
            st.download_button(
                "Download completed Excel report",
                data=package.workbook_bytes,
                file_name=f"{package.basename}.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                width="stretch",
            )
        return

    size_warning = email_attachment_size_warning(package)
    if size_warning:
        st.warning(size_warning)

    subject, body = _expense_email_subject_and_body(details, package)
    preferred_destination = _preferred_email_destination(
        _request_user_agent(),
        _request_platform_hint(),
    )
    # Detection picks the DEFAULT only; the selector stays visible so a
    # misdetected browser is one click from the right route. The membership test
    # also repairs a session holding a destination label from an older release
    # -- a session value outside the options tuple is a selectbox error, which
    # would take the page down at the last step of a finished report.
    destination_key = "expense_email_destination"
    if st.session_state.get(destination_key) not in _EMAIL_DESTINATIONS:
        st.session_state[destination_key] = preferred_destination
    destination = st.selectbox(
        "Open approval email in",
        _EMAIL_DESTINATIONS,
        key=destination_key,
        help=(
            "Both Outlook choices use the attachment-bearing email draft. On "
            "iPhone/iPad, the browser share sheet passes the PDF and message "
            "directly to Mail or Outlook."
        ),
    )

    if destination in {_EMAIL_OUTLOOK_APP, _EMAIL_OUTLOOK_WEB}:
        if eml_bytes:
            destination_name = (
                "Outlook on the web"
                if destination == _EMAIL_OUTLOOK_WEB
                else "Outlook"
            )
            st.download_button(
                f"Open approval email in {destination_name}",
                data=eml_bytes,
                file_name=f"{package.basename}_Approval_Email.eml",
                mime="message/rfc822",
                type="primary",
                # on_click="ignore" suppresses the rerun a download button
                # normally triggers. Without it the script re-executes the
                # moment the operator takes the draft, the generated-package
                # block re-renders, and the button they just pressed jumps or
                # disappears under the cursor on slower devices.
                on_click="ignore",
                width="stretch",
            )
            if destination == _EMAIL_OUTLOOK_WEB:
                st.caption(
                    "The combined PDF is already attached. If the draft does not "
                    "open automatically, drag the downloaded .eml onto Outlook "
                    "on the web's reading pane, then review and send."
                )
            else:
                st.caption(
                    "The combined PDF is already attached. If the browser saves "
                    "the draft, open that .eml file once to continue in Outlook."
                )
        else:
            st.warning(
                "The Outlook draft is unavailable. Generate the report again, or "
                "use the iPhone/iPad share option if you are on that device."
            )
    else:
        _render_ios_mail_share(
            to=details.approver_email,
            subject=subject,
            body=body,
            attachments=email_attachments_for_package(package),
        )

    with st.expander("Other file and email options", expanded=False):
        download_columns = st.columns(2)
        with download_columns[0]:
            st.download_button(
                "Download completed Excel report",
                data=package.workbook_bytes,
                file_name=f"{package.basename}.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                width="stretch",
            )
        with download_columns[1]:
            st.download_button(
                "Download combined PDF packet",
                data=package.pdf_bytes,
                file_name=f"{package.basename}.pdf",
                mime="application/pdf",
                width="stretch",
            )
        st.caption(
            "Excel is optional and is not attached to the approval email. If you "
            "edit it, export the edited workbook to PDF and send that PDF instead."
        )
        st.link_button(
            "Open a new email without attachments ↗",
            build_mailto_url(
                to=details.approver_email,
                subject=subject,
                body=body,
            ),
            width="stretch",
        )


def _render_ios_mail_share(
    *,
    to: str,
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]],
) -> None:
    """Pass the completed PDF to an iOS/iPadOS mail app through Web Share.

    The component owns the whole action, including its own disabled state when
    ``navigator.canShare({files})`` is false. No Streamlit download or link
    button may be rendered beside it -- a second primary control here is the
    "two main buttons" report in the handoff notes, and it is pinned by
    tests/test_web_ui_app.py.

    Web Share cannot populate a recipient, so the frontend copies the approver
    address to the clipboard (or displays it) in the same user gesture. Nothing
    may be awaited before ``navigator.share()``: the transient user activation
    expires and the sheet silently refuses to open.
    """
    _IOS_MAIL_SHARE_COMPONENT(
        **_ios_mail_share_payload(
            to=to, subject=subject, body=body, attachments=attachments
        ),
        # A starting iframe height, refined by the frontend's
        # streamlit:setFrameHeight message. It must stay large enough to show
        # the 48px button plus its status line: a height of 0 renders a
        # perfectly valid but INVISIBLE iframe with no error anywhere -- the
        # same shape of bug that once disabled every device-memory feature in
        # this application for the life of a deployment.
        height=112,
        key="expense_ios_mail_share",
        # Keeps the iframe in the tab order, so the share button is reachable
        # from an external keyboard on an iPad.
        tab_index=0,
    )


def _ios_mail_share_payload(
    *,
    to: str,
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]],
) -> dict[str, object]:
    """Serialize an attachment-bearing iOS share request for the component.

    Values cross as STRUCTURED component arguments, never as interpolated HTML;
    the frontend rebuilds each file with atob + Blob + File and writes text with
    textContent. That boundary is what keeps a merchant name read off a receipt
    from becoming executable markup.

    Base64 inflates the PDF by about a third in transient browser memory. Do not
    also stash the payload in a DOM attribute, a log line, or another session
    key -- iPadOS is the constrained target here.
    """
    return {
        "to": to,
        "subject": subject,
        "body": body,
        "files": [
            {
                "name": name,
                "mime": (
                    mimetypes.guess_type(name)[0]
                    or "application/octet-stream"
                ),
                "b64": base64.b64encode(data).decode("ascii"),
            }
            for name, data in attachments
        ],
    }


def _expense_email_subject_and_body(
    details: ExpenseReportDetails,
    package: ExpensePackage,
) -> tuple[str, str]:
    """Return the shared subject/body used by web and local compose links.

    Used by the iOS share sheet and by the attachment-free mailto fallback, so
    both non-Outlook routes read identically.

    The subject and greeting are duplicated from ``_build_expense_eml`` and MUST
    match it; the bodies deliberately differ (this one is short because a share
    sheet and a mailto URL both truncate, while the .eml carries the full bullet
    list). Consolidating the two into one helper is the obvious refactor and is
    safe only if it preserves that asymmetry.
    """
    subject = f"{details.employee_name} expense report - {details.report_date:%Y-%m-%d}"
    first_name = details.approver_name.split()[0] if details.approver_name.split() else ""
    greeting = (
        f"Good afternoon, {first_name}. Please review and approve the attached expense report."
        if first_name
        else "Good afternoon. Please review and approve the attached expense report."
    )
    body = build_plain_body(
        [
            ("Employee", details.employee_name),
            ("Account", details.account),
            ("Total reimbursement", f"${package.total:,.2f}"),
        ],
        greeting=greeting,
    )
    return subject, body


def _preferred_email_destination(user_agent: str, platform_hint: str = "") -> str:
    """Choose the least-friction email route without hiding alternatives.

    Only picks a DEFAULT. Every destination stays selectable, so a wrong guess
    costs one click and never blocks the report. Pure function of the two
    header strings; ``tests/test_web_ui_app.py`` pins the three identities.
    """
    identity = f"{platform_hint} {user_agent}".casefold()
    if (
        "iphone" in identity
        or "ipad" in identity
        # iPadOS in "Request Desktop Website" mode -- the default since iPadOS
        # 13 -- reports itself as Macintosh and keeps only the Mobile token.
        # Without this clause every iPad defaults to the Outlook .eml route,
        # which on iPadOS lands in Files instead of opening a draft.
        or ("macintosh" in identity and "mobile" in identity)
        or "ios" in identity
    ):
        return _EMAIL_DEFAULT_APP
    # Same value as the fallback below, kept as an explicit branch so the
    # Windows intent is readable and a future non-Outlook default cannot be
    # introduced by editing only the fallback.
    if "windows" in identity:
        return _EMAIL_OUTLOOK_APP
    # The attached-PDF draft is the safest default when browser identity is
    # unavailable (including Streamlit's test runner).
    return _EMAIL_OUTLOOK_APP


def _request_header(name: str) -> str:
    """Read one request header, or "" when there is no request context.

    Both lookups are needed: header-name casing is not guaranteed across
    Streamlit versions and proxies. The broad except covers running outside a
    script run (AppTest, a bare import) where ``st.context`` raises -- header
    sniffing only picks a default destination, so failing to "" is correct and
    must never propagate.
    """
    try:
        headers = st.context.headers
        return str(headers.get(name) or headers.get(name.casefold()) or "")
    except Exception:
        return ""


def _request_user_agent() -> str:
    return _request_header("User-Agent")


def _request_platform_hint() -> str:
    return _request_header("Sec-CH-UA-Platform")


def _unique_receipts(uploads) -> tuple[list[tuple[str, str, bytes]], list[str]]:
    """De-duplicate receipts by content hash, preserving first-seen order.

    Returns ``([(receipt_id, filename, payload)], [duplicate filenames])``.
    Order is the guarantee that matters: receipt numbering, widget keys and the
    order of pages in the combined PDF all follow this list, so re-sorting it
    would renumber a report the operator is halfway through reviewing.

    Accepts either mirrored ``(filename, payload, mime)`` tuples or Streamlit
    ``UploadedFile`` objects. Production only ever passes tuples today; the
    object branch is retained because the mirror is populated from uploader
    objects one step earlier and the two shapes have been swapped before.
    """
    unique: list[tuple[str, str, bytes]] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for upload in uploads:
        if isinstance(upload, tuple):
            filename, payload, _mime_type = upload
        else:
            filename, payload = upload.name, upload.getvalue()
        receipt_id = hashlib.sha256(payload).hexdigest()
        if receipt_id in seen:
            duplicates.append(filename)
            continue
        seen.add(receipt_id)
        unique.append((receipt_id, filename, payload))
    return unique, duplicates


def _merge_receipt_sources(*groups) -> list[tuple[str, bytes, str]]:
    """Merge uploader additions into the receipt mirror without byte growth.

    Earlier groups win, so the caller passes the existing mirror first and the
    uploader's current batch second: re-selecting a file already in the report
    keeps the stored copy and its reviewed fields rather than replacing it.

    Note the element order here is ``(filename, payload, mime)`` -- the MIRROR
    shape -- while ``_unique_receipts`` returns ``(receipt_id, filename,
    payload)``. The two are not interchangeable, and swapping them silently
    hashes a filename instead of the bytes.
    """
    merged: list[tuple[str, bytes, str]] = []
    seen: set[str] = set()
    for group in groups:
        for upload in group:
            if isinstance(upload, tuple):
                filename, payload, mime_type = upload
            else:
                filename = upload.name
                payload = upload.getvalue()
                mime_type = upload.type or "application/octet-stream"
            receipt_id = hashlib.sha256(payload).hexdigest()
            if receipt_id in seen:
                continue
            seen.add(receipt_id)
            merged.append((filename, payload, mime_type))
    return merged


def _remove_receipt_from_draft(receipt_id: str) -> None:
    """Remove one mirrored source and clear the uploader's stale file list.

    Bumping the uploader nonce is not optional bookkeeping: Streamlit's
    file_uploader has no API for dropping one file, so the widget would keep
    handing back the removed receipt on the next rerun and it would reappear.
    Rotating the key retires that widget entirely; the mirror is what carries
    the remaining receipts across.

    The generated package is dropped here as well. Its content fingerprint no
    longer matches, and leaving it would put a stale PDF -- one still containing
    the removed receipt -- behind a download button that looks current.
    """
    retained = []
    for filename, payload, mime_type in list(
        st.session_state.get("expense_receipt_files", []) or []
    ):
        if hashlib.sha256(payload).hexdigest() != receipt_id:
            retained.append((filename, payload, mime_type))
    st.session_state["expense_receipt_files"] = retained
    st.session_state["expense_uploader_nonce"] = int(
        st.session_state.get("expense_uploader_nonce", 0) or 0
    ) + 1
    st.session_state.pop("expense_generated_package", None)
    st.session_state.pop("expense_generated_eml", None)
    st.session_state.pop("expense_generated_signature", None)


def _clear_removed_receipts(active_ids: set[str]) -> None:
    """Garbage-collect the per-receipt state of receipts no longer present.

    Cleaning the DRAFT SNAPSHOT as well as the live session is the half that is
    easy to miss and load-bearing. ``restore_expense_draft_state`` re-injects
    the snapshot with ``setdefault`` on every rerun, so a receipt's merchant,
    amount and coding removed only from the live session would be resurrected
    on the very next run -- and, because the receipt is gone, they would attach
    themselves to whatever receipt later lands on the same key.

    The static guard in tests/test_expense_draft_state.py cannot help here: it
    only sees keys removed by a literal name, and these are computed. This
    function IS the compensating control for that blind spot.

    Iterates over ``list(...)`` of both mappings because both are mutated inside
    the loop.
    """
    prior = set(st.session_state.get("expense_active_receipt_ids", set()) or set())
    removed = prior - active_ids
    for receipt_id in removed:
        token = receipt_id[:12]
        for key in list(st.session_state):
            # Two key shapes per receipt: the analysis/preview entries carry the
            # full content hash, the field widgets carry its 12-character
            # prefix. Both have to match or half the receipt's state survives.
            #
            # Precedence note: `and` binds tighter than `or`, so the
            # expense_-prefix test applies to the token branch only. Harmless
            # today (a 64-hex content hash appears in no other key), but do not
            # read this as "both branches are prefix-guarded".
            if receipt_id in key or token in key and key.startswith("expense_"):
                st.session_state.pop(key, None)
        snapshot = dict(st.session_state.get("expense_draft_snapshot", {}) or {})
        for key in list(snapshot):
            if receipt_id in key or token in key and key.startswith("expense_"):
                snapshot.pop(key, None)
        if snapshot:
            st.session_state["expense_draft_snapshot"] = snapshot
        else:
            st.session_state.pop("expense_draft_snapshot", None)
    st.session_state["expense_active_receipt_ids"] = set(active_ids)
    if removed:
        st.session_state.pop("expense_generated_package", None)
        st.session_state.pop("expense_generated_eml", None)
        st.session_state.pop("expense_generated_signature", None)


def preserve_expense_draft_state() -> None:
    """Mirror primitive widget values before another workflow hides them.

    Streamlit deletes widget keys for widgets that do not render. The top-level
    workflow switch therefore needs a non-widget mirror just like the PO routing
    controls do. Uploaded bytes have their own bounded mirror and are excluded.
    """
    # The mirror must only ever hold values the OPERATOR entered. Transient UI
    # state that handler code pops (errors, "recalled from history" captions)
    # must never be mirrored: setdefault() in restore_expense_draft_state would
    # put it straight back, so a one-off failure message became permanent and
    # sat next to a subsequently-good package forever.
    #
    # The mirror is only ever ADDED to, never rebuilt from the live session.
    # Rebuilding was tried and is unsafe: there is no reliable "the expense
    # widgets rendered on the previous run" signal. workflow_mode is updated
    # before the rerun (so it is already "expense" on the run that switches in,
    # before any widget exists), and a completion marker still breaks when the
    # operator visits pages/2_Smartsheet_PO.py — that page renders no expense
    # widgets, so Streamlit collects them while the marker still reads true, and
    # the rebuild would wipe a half-finished report.
    #
    # Correctness therefore rests on the exclusion list below covering every
    # transient key, which is enforced statically by
    # tests/test_expense_draft_state.py::test_every_popped_expense_key_is_excluded.
    snapshot = dict(st.session_state.get("expense_draft_snapshot", {}) or {})
    excluded_fragments = (
        "receipt_uploader",
        "receipt_files",
        "receipt_analysis",
        "receipt_error",
        "preview_",
        "generated_",
        "draft_snapshot",
        "active_receipt_ids",
        "clear_report",
        "generate_expense_package",
        "remove_receipt",
        "retry_receipt",
        # Transient, handler-popped state — never operator input:
        "_error",
        "_recalled",
        "restored_without_uploader",
    )
    # STALE COMMENT WARNING -- the paragraph immediately below describes the
    # conditional-rebuild design that was implemented and then REVERTED (see the
    # 2026-08-12 hardening notes, section 7.1, and the second paragraph at the
    # top of this function). No rebuild happens here: the loop is purely
    # additive, and `_expense_workflow_rendered`, the signal that paragraph
    # assumes, exists nowhere in this module. Read it as history, not as a
    # description of the code, and do not "restore" the behaviour it describes.
    #
    # If the expense workflow rendered on the previous run then every one of its
    # widget keys is currently present, so the live session IS the truth and the
    # snapshot can be rebuilt from scratch. That drops any key popped since the
    # last mirror. When another workflow was showing we must NOT rebuild:
    # Streamlit has already deleted the un-rendered expense widgets, and the
    # stale snapshot is precisely what restores them.
    #
    # The isinstance filter is the second half of the bound on this mirror.
    # Receipt bytes, ReceiptAnalysis objects and the generated ExpensePackage
    # are all excluded by type as well as by name, so the snapshot can never
    # become a second full-size copy of the uploaded receipts. `date` is in the
    # tuple for the report/transaction/travel dates; `bool` is covered by `int`.
    for key, value in list(st.session_state.items()):
        if not key.startswith("expense_") or any(
            fragment in key for fragment in excluded_fragments
        ):
            continue
        if isinstance(value, (str, int, float, bool, date, type(None))):
            snapshot[key] = value
    if snapshot:
        st.session_state["expense_draft_snapshot"] = snapshot


def restore_expense_draft_state() -> None:
    """Restore mirrored expense values before their widgets are instantiated.

    ``setdefault``, never assignment: a live value always beats the mirror, so
    a stale snapshot entry can never overwrite something the operator has just
    typed. This is also why the mirror must exclude transient state -- anything
    in the snapshot is re-injected here on EVERY rerun and therefore cannot be
    dismissed (2026-08-12 hardening notes, section 4.3).

    Must be the first thing ``render_expense_workflow`` does. Called after any
    expense widget has rendered, the writes land on already-instantiated keys
    and are discarded with no error.
    """
    snapshot = st.session_state.get("expense_draft_snapshot", {})
    # Defends against a session restored across a deploy that stored something
    # other than a dict under this key; iterating that would raise on the first
    # line of the workflow and leave the page blank.
    if not isinstance(snapshot, dict):
        return
    for key, value in snapshot.items():
        st.session_state.setdefault(key, value)


def _reset_expense_report() -> None:
    """Clear only expense-workflow state and rotate the uploader widget.

    The ``expense_`` prefix is the entire scoping rule, which is why every key
    this workflow owns carries it: an in-progress purchase order, the device
    cookie and the workflow selector all live in the same session and must
    survive this. The draft snapshot is inside the prefix and is cleared too --
    leaving it behind would let the restore pass rebuild the report that was
    just discarded.
    """
    # Read the nonce BEFORE the purge, then re-seed it afterwards. The purge
    # removes the counter along with everything else, so recomputing it later
    # would restart at 1 and reuse a widget key this session has already used --
    # which resurrects the retired uploader's file list.
    next_nonce = int(st.session_state.get("expense_uploader_nonce", 0) or 0) + 1
    for key in list(st.session_state):
        if key.startswith("expense_"):
            st.session_state.pop(key, None)
    st.session_state["expense_uploader_nonce"] = next_nonce


def _receipt_visible_problems(index: int, item: ExpenseItem) -> list[str]:
    """Return this receipt line's outstanding fields, phrased for its own card.

    A subset of what ``validate_expense_report`` blocks on, rendered beside the
    receipt it belongs to so the operator does not have to map a message at the
    bottom of the page back to one of a dozen cards. It is a DISPLAY helper: the
    authoritative gate is still the validation call in the caller, and this list
    being empty never implies the report is generatable.
    """
    problems: list[str] = []
    if item.transaction_date is None:
        problems.append("transaction date")
    if not item.description:
        problems.append("description / business purpose")
    if parse_expense_amount(item.amount) is None:
        problems.append("reimbursable amount")
    if item.section == EXPENSE_SECTION_ENTERTAINMENT and not item.contact_name:
        problems.append("entertainment contact name")
    # allocation_problems prefixes each message with "Receipt N: ". The prefix
    # is passed anyway (rather than omitted) so the label is validated the same
    # way it is in the report-wide list, then stripped here because this warning
    # already sits under the card that names the receipt. dict.fromkeys
    # de-duplicates while preserving order -- a split receipt can raise the same
    # coding problem on several lines and repeating it reads like several
    # distinct faults.
    problems.extend(
        problem.split(": ", 1)[-1]
        for problem in allocation_problems(item.allocation, prefix=f"Receipt {index}")
    )
    return list(dict.fromkeys(problems))


def _mileage_visible_problems(index: int, item: MileageItem) -> list[str]:
    """Return this mileage row's outstanding fields, phrased for its own card.

    Same display-only contract as ``_receipt_visible_problems``. It also reports
    a missing IRS rate, because that one is an environment problem the operator
    cannot fix by typing -- surfacing it beside the row is what stops it being
    mistaken for a bad travel date.
    """
    problems: list[str] = []
    if item.transaction_date is None:
        problems.append("travel date")
    if not item.purpose:
        problems.append("business purpose")
    if not item.destination:
        problems.append("destination")
    if parse_mileage(item.miles) is None:
        problems.append("business miles")
    if item.transaction_date and irs_business_mileage_rate(item.transaction_date) is None:
        problems.append("configured IRS mileage rate")
    problems.extend(
        problem.split(": ", 1)[-1]
        for problem in allocation_problems(item.allocation, prefix=f"Mileage {index}")
    )
    return list(dict.fromkeys(problems))
