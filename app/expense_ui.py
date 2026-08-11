"""Streamlit workflow for employee reimbursement reports."""

from __future__ import annotations

import hashlib
import html
from datetime import date
from pathlib import Path

import streamlit as st

from app import contracts
from app.eml_builder import DAVID_EMAIL, build_eml, build_mailto_url, build_plain_body
from app.expense_report import (
    ALLOCATION_JOB,
    ALLOCATION_KINDS,
    ALLOCATION_OVERHEAD,
    ALLOCATION_WORK_ORDER,
    EXPENSE_SECTION_ENTERTAINMENT,
    EXPENSE_SECTION_MISC,
    ExpenseAllocation,
    ExpenseItem,
    ExpensePackage,
    ExpenseReportDetails,
    allocation_problems,
    build_expense_package,
    email_attachments_for_package,
    expense_report_signature,
    expense_report_total,
    expense_report_warnings,
    parse_expense_amount,
    receipt_preview_bytes,
    validate_expense_report,
)
from app.job_numbers import job_numbers_for_contract
from app.memory import (
    record_expense_profile,
    remembered_device_account_manager,
    remembered_expense_profile,
)
from app.receipt_analyzer import ReceiptAnalysis, analyze_receipt


EXPENSE_WORKFLOW = "Expense reimbursement"
PURCHASE_WORKFLOW = "Purchase order"

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
_MAX_RECEIPT_BYTES = 15 * 1024 * 1024
_MAX_REPORT_UPLOAD_BYTES = 60 * 1024 * 1024
_JOB_PLACEHOLDER = "— Select the job number —"
_ALLOCATION_LABELS = {
    ALLOCATION_JOB: "Job expense",
    ALLOCATION_WORK_ORDER: "Work-order expense",
    ALLOCATION_OVERHEAD: "Overhead / other expense",
}
_SECTION_LABELS = {
    EXPENSE_SECTION_MISC: "Miscellaneous",
    EXPENSE_SECTION_ENTERTAINMENT: "Entertainment",
}
_MAIL_LABELS = {
    "home": "Mail check to home address",
    "satellite": "Mail check to a satellite office",
}
_RRH_ADMIN_NAME = "David Siegal"


def render_expense_workflow(browser_token: str) -> None:
    """Render the complete receipt-to-email-draft workflow."""
    restore_expense_draft_state()
    st.markdown(
        """
        <div class="hero">
            <p class="brand-kicker">EXPENSE REPORT WORKFLOW</p>
            <h1>Expense Report <span class="zing">Process Control</span></h1>
            <p class="hero-subtitle">
                Upload each receipt once, review what the tool reads, then create
                the completed Excel form, combined receipt packet, and email draft.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num">1</div>
            <p class="step-title">Upload all receipts</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
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
        if st.session_state.pop("expense_restored_without_uploader", False):
            upload_sources = [*mirrored_uploads, *current_uploads]
        else:
            upload_sources = current_uploads
        st.session_state["expense_receipt_files"] = upload_sources
    else:
        upload_sources = mirrored_uploads
        if upload_sources:
            st.session_state["expense_restored_without_uploader"] = True
            st.info(
                "Your in-progress receipts were restored. Use Clear receipts and "
                "start over when you intend to remove the entire draft."
            )
    if not upload_sources:
        _clear_removed_receipts(set())
        st.info("Add the receipts above to begin the reimbursement report.")
        return

    unique_uploads, duplicate_names = _unique_receipts(upload_sources)
    active_ids = {receipt_id for receipt_id, _, _ in unique_uploads}
    _clear_removed_receipts(active_ids)
    if duplicate_names:
        st.warning(
            "Duplicate receipt files were ignored: "
            + ", ".join(duplicate_names)
            + "."
        )
    if st.button(
        "Clear receipts and start over",
        key="expense_clear_report",
        help="Removes this in-progress expense report from the current browser session.",
    ):
        _reset_expense_report()
        st.rerun()
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

    st.caption(
        f"{len(unique_uploads)} unique receipt"
        f"{'s' if len(unique_uploads) != 1 else ''} ready for review. "
        "Original uploads remain unchanged; compact copies are used only in the workbook."
    )

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num">2</div>
            <p class="step-title">Confirm report details and default coding</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    accounts = tuple(contracts.contract_names())
    account = st.selectbox(
        "Account / contract *",
        accounts,
        key="expense_account",
        help="This filters the verified job-number choices and remembers the correct administrator.",
    )
    profile = _seed_profile(browser_token, account)
    account_token = hashlib.sha256(account.encode("utf-8")).hexdigest()[:10]

    detail_columns = st.columns(2)
    with detail_columns[0]:
        employee_name = st.text_input(
            "Employee name *",
            key=f"expense_employee_name_{account_token}",
        ).strip()
        employee_number = st.text_input(
            "Employee number *",
            key=f"expense_employee_number_{account_token}",
        ).strip()
        employee_home_bu = st.text_input(
            "Employee home BU *",
            key=f"expense_employee_home_bu_{account_token}",
            help=(
                "Enter the JDE home business-unit value. The completed example "
                "used a home address here and may not be a reliable precedent."
            ),
        ).strip()
    with detail_columns[1]:
        report_date = st.date_input(
            "Report date *",
            key=f"expense_report_date_{account_token}",
            format="MM/DD/YYYY",
        )
        approver_name = st.text_input(
            "Contract administrator / approver name *",
            key=f"expense_approver_name_{account_token}",
        ).strip()
        approver_email = st.text_input(
            "Contract administrator / approver email *",
            key=f"expense_approver_email_{account_token}",
        ).strip()

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

    st.markdown("#### Default receipt coding")
    st.caption(
        "Set the coding once. Every receipt uses it unless you turn on a "
        "receipt-specific override below."
    )
    default_allocation = _render_allocation_fields(
        prefix=f"expense_default_{account_token}",
        account=account,
        seed=_allocation_from_profile(profile),
    )
    default_problems = allocation_problems(default_allocation)
    if default_problems:
        st.caption(
            "Complete the default coding below each receipt that uses it. "
            "These fields are required, not optional."
        )

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
    )

    st.markdown(
        """
        <div class="step-header">
            <div class="step-num">3</div>
            <p class="step-title">Review each receipt</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Every required value stays visible on the receipt it belongs to. "
        "The tool's guesses are editable and accounting codes are never inferred from the image."
    )
    items: list[ExpenseItem] = []
    for index, (receipt_id, filename, file_bytes) in enumerate(unique_uploads, 1):
        item = _render_receipt(
            index=index,
            receipt_id=receipt_id,
            filename=filename,
            file_bytes=file_bytes,
            analysis=analyses[receipt_id],
            account=account,
            default_allocation=default_allocation,
        )
        items.append(item)

    total = expense_report_total(items)
    summary_columns = st.columns(2)
    summary_columns[0].metric("Receipts", len(items))
    summary_columns[1].metric("Total reimbursement", f"${total:,.2f}")

    review_warnings = expense_report_warnings(details, items)
    if review_warnings:
        st.warning(
            "Review before sending: "
            + "; ".join(warning.rstrip(". ") for warning in review_warnings)
            + "."
        )

    problems = validate_expense_report(details, items)
    if problems:
        st.warning(
            "Before generating: "
            + "; ".join(problem.rstrip(". ") for problem in problems)
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
        "The Excel file contains the completed official form followed by a "
        "printable RECEIPTS worksheet. The PDF packet places the form first and "
        "each receipt after it. Nothing is emailed automatically."
    )

    signature = expense_report_signature(details, items)
    generated_signature = str(st.session_state.get("expense_generated_signature", ""))
    if generated_signature and generated_signature != signature:
        st.info("A report detail changed. Generate again to refresh the files and email draft.")

    if st.button(
        "Generate expense report and email draft",
        type="primary",
        width="stretch",
        disabled=bool(problems),
        key="generate_expense_package",
    ):
        with st.spinner("Creating the Excel report, receipt packet, and email draft…"):
            try:
                package = build_expense_package(details, items)
                eml_bytes = _build_expense_eml(details, package)
            except Exception as exc:
                st.session_state["expense_generation_error"] = str(exc)[:500]
                st.session_state.pop("expense_generated_package", None)
                st.session_state.pop("expense_generated_eml", None)
                st.session_state.pop("expense_generated_signature", None)
            else:
                st.session_state["expense_generated_package"] = package
                st.session_state["expense_generated_eml"] = eml_bytes
                st.session_state["expense_generated_signature"] = signature
                st.session_state.pop("expense_generation_error", None)
                _remember_profile(
                    browser_token=browser_token,
                    details=details,
                    allocation=default_allocation,
                )

    generation_error = str(st.session_state.get("expense_generation_error", "") or "")
    if generation_error:
        st.error(f"The expense package could not be generated: {generation_error}")

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
    analysis_key = f"expense_receipt_analysis_{receipt_id}"
    error_key = f"expense_receipt_error_{receipt_id}"
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
    default_allocation: ExpenseAllocation,
) -> ExpenseItem:
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
    override_key = f"expense_override_{token}"

    title_amount = str(st.session_state.get(amount_key, "") or "").strip()
    title_merchant = str(st.session_state.get(merchant_key, "") or "").strip()
    title = f"Receipt {index} · {title_merchant or Path(filename).name}"
    if title_amount:
        title += f" · ${title_amount.lstrip('$')}"
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
                st.session_state[preview_key] = b""
                st.caption(f"Preview unavailable: {str(exc)[:160]}")
        preview = st.session_state.get(preview_key, b"")
        if preview:
            st.image(preview, caption=f"Receipt {index}", width="stretch")
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
        if analysis.currency and analysis.currency != "USD":
            st.error(
                f"Receipt currency appears to be {analysis.currency}. Enter the approved U.S.-dollar reimbursement amount."
            )

    with fields_column:
        merchant = st.text_input(
            "Merchant",
            key=merchant_key,
            help="Used as a receipt label; the Description / business purpose is what appears on the form.",
        ).strip()
        date_kwargs = {"key": date_key, "format": "MM/DD/YYYY"}
        if date_key not in st.session_state:
            date_kwargs["value"] = None
        transaction_date = st.date_input("Transaction date *", **date_kwargs)
        description = st.text_input(
            "Description / business purpose *",
            key=description_key,
            help="Edit the receipt-based draft to state the actual business purpose without including accounting codes.",
        ).strip()
        amount = st.text_input(
            "Reimbursable amount *",
            key=amount_key,
            help="Use the final amount paid, including charged tip and tax. For foreign currency, enter the approved USD amount.",
        ).strip()
        section = st.selectbox(
            "Expense section *",
            tuple(_SECTION_LABELS),
            format_func=lambda value: _SECTION_LABELS[value],
            key=section_key,
            help=(
                "Entertainment requires a business purpose and contact name. "
                "Ordinary travel, parking, supplies, and employee meals normally remain Miscellaneous."
            ),
        )
        contact_name = ""
        if section == EXPENSE_SECTION_ENTERTAINMENT:
            contact_name = st.text_input(
                "Entertainment contact name *",
                key=contact_key,
            ).strip()

        use_override = st.toggle(
            "Use different coding for this receipt",
            key=override_key,
            help="Leave off to use the report-level default coding above.",
        )
        if use_override:
            allocation = _render_allocation_fields(
                prefix=f"expense_receipt_allocation_{token}",
                account=account,
                seed=default_allocation,
            )
        else:
            allocation = default_allocation
            st.caption(f"Coding: {_allocation_summary(default_allocation)}")

    item = ExpenseItem(
        receipt_id=receipt_id,
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
    receipt_problems = _receipt_visible_problems(index, item)
    if receipt_problems:
        st.warning("Needed for this receipt: " + "; ".join(receipt_problems) + ".")
    return item


def _render_allocation_fields(
    *,
    prefix: str,
    account: str,
    seed: ExpenseAllocation,
) -> ExpenseAllocation:
    _seed_allocation(prefix, seed)
    kind = st.selectbox(
        "Allocation type *",
        ALLOCATION_KINDS,
        format_func=lambda value: _ALLOCATION_LABELS[value],
        key=f"{prefix}_kind",
    )
    values = {
        "kind": kind,
        "job_number": str(st.session_state.get(f"{prefix}_job_number", "") or ""),
        "service_center": str(st.session_state.get(f"{prefix}_service_center", "") or ""),
        "account_cost_type": str(st.session_state.get(f"{prefix}_account_cost_type", "") or ""),
        "cost_code_or_wo_type": str(st.session_state.get(f"{prefix}_cost_code", "") or ""),
        "work_order_number": str(st.session_state.get(f"{prefix}_work_order", "") or ""),
        "company_number": str(st.session_state.get(f"{prefix}_company", "") or ""),
        "department_number": str(st.session_state.get(f"{prefix}_department", "") or ""),
        "ou_number": str(st.session_state.get(f"{prefix}_ou", "") or ""),
        "gl_account_number": str(st.session_state.get(f"{prefix}_gl_account", "") or ""),
    }
    if kind == ALLOCATION_JOB:
        options = tuple(job_numbers_for_contract(account))
        selectable = (_JOB_PLACEHOLDER, *options)
        if st.session_state.get(f"{prefix}_job_number") not in selectable:
            st.session_state[f"{prefix}_job_number"] = _JOB_PLACEHOLDER
        selected = st.selectbox(
            "Job number *",
            selectable,
            key=f"{prefix}_job_number",
            help=(
                "The descriptive choice is converted to the JDE job identifier in "
                "the Excel form. Rochester Unity sites use RRH choices; choices "
                "beginning Unity refer to Arkansas."
            ),
        )
        values["job_number"] = "" if selected == _JOB_PLACEHOLDER else selected
        values["account_cost_type"] = st.text_input(
            "Account / cost type *",
            key=f"{prefix}_account_cost_type",
        ).strip()
        values["cost_code_or_wo_type"] = st.text_input(
            "Cost code *",
            key=f"{prefix}_cost_code",
        ).strip()
    elif kind == ALLOCATION_WORK_ORDER:
        values["service_center"] = st.text_input(
            "Service center number *",
            key=f"{prefix}_service_center",
        ).strip()
        values["account_cost_type"] = st.text_input(
            "Account / cost type *",
            key=f"{prefix}_account_cost_type",
        ).strip()
        values["cost_code_or_wo_type"] = st.text_input(
            "Work-order type *",
            key=f"{prefix}_cost_code",
        ).strip()
        values["work_order_number"] = st.text_input(
            "Work-order number *",
            key=f"{prefix}_work_order",
        ).strip()
    else:
        overhead_columns = st.columns(2)
        with overhead_columns[0]:
            values["company_number"] = st.text_input(
                "Company number *", key=f"{prefix}_company"
            ).strip()
            values["ou_number"] = st.text_input(
                "OU number *", key=f"{prefix}_ou"
            ).strip()
        with overhead_columns[1]:
            values["department_number"] = st.text_input(
                "Department number *", key=f"{prefix}_department"
            ).strip()
            values["gl_account_number"] = st.text_input(
                "GL account number *", key=f"{prefix}_gl_account"
            ).strip()
    return ExpenseAllocation(**values)


def _seed_profile(browser_token: str, account: str) -> dict[str, str]:
    profile = remembered_expense_profile(browser_token, account)
    account_token = hashlib.sha256(account.encode("utf-8")).hexdigest()[:10]
    seed_key = f"expense_profile_seeded_{account_token}"
    if not st.session_state.get(seed_key):
        employee_name = profile.get("employee_name") or remembered_device_account_manager(
            browser_token, account
        )
        defaults = {
            f"expense_employee_name_{account_token}": employee_name,
            f"expense_employee_number_{account_token}": profile.get("employee_number", ""),
            f"expense_employee_home_bu_{account_token}": profile.get("employee_home_bu", ""),
            f"expense_report_date_{account_token}": date.today(),
            f"expense_approver_name_{account_token}": (
                profile.get("approver_name")
                or (_RRH_ADMIN_NAME if contracts.is_rrh(account) else "")
            ),
            f"expense_approver_email_{account_token}": (
                profile.get("approver_email")
                or (DAVID_EMAIL if contracts.is_rrh(account) else "")
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
        st.session_state[seed_key] = True
    return profile


def _seed_receipt_fields(token: str, analysis: ReceiptAnalysis) -> None:
    defaults = {
        f"expense_merchant_{token}": "",
        f"expense_description_{token}": "",
        f"expense_amount_{token}": "",
        f"expense_section_{token}": EXPENSE_SECTION_MISC,
        f"expense_contact_{token}": "",
        f"expense_override_{token}": False,
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


def _seed_allocation(prefix: str, seed: ExpenseAllocation) -> None:
    defaults = {
        f"{prefix}_kind": seed.kind if seed.kind in ALLOCATION_KINDS else ALLOCATION_JOB,
        f"{prefix}_job_number": seed.job_number or _JOB_PLACEHOLDER,
        f"{prefix}_service_center": seed.service_center,
        f"{prefix}_account_cost_type": seed.account_cost_type,
        f"{prefix}_cost_code": seed.cost_code_or_wo_type,
        f"{prefix}_work_order": seed.work_order_number,
        f"{prefix}_company": seed.company_number,
        f"{prefix}_department": seed.department_number,
        f"{prefix}_ou": seed.ou_number,
        f"{prefix}_gl_account": seed.gl_account_number,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _allocation_from_profile(profile: dict[str, str]) -> ExpenseAllocation:
    return ExpenseAllocation(
        kind=profile.get("allocation_kind", ALLOCATION_JOB),
        job_number=profile.get("job_number", ""),
        service_center=profile.get("service_center", ""),
        account_cost_type=profile.get("account_cost_type", ""),
        cost_code_or_wo_type=profile.get("cost_code_or_wo_type", ""),
        work_order_number=profile.get("work_order_number", ""),
        company_number=profile.get("company_number", ""),
        department_number=profile.get("department_number", ""),
        ou_number=profile.get("ou_number", ""),
        gl_account_number=profile.get("gl_account_number", ""),
    )


def _remember_profile(
    *,
    browser_token: str,
    details: ExpenseReportDetails,
    allocation: ExpenseAllocation,
) -> None:
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


def _build_expense_eml(details: ExpenseReportDetails, package: ExpensePackage) -> bytes:
    subject = f"{details.employee_name} expense report - {details.report_date:%Y-%m-%d}"
    bullets = [
        ("Employee", details.employee_name),
        ("Account", details.account),
        (
            "Report date",
            f"{details.report_date:%B} {details.report_date.day}, {details.report_date:%Y}",
        ),
        ("Receipts", str(package.receipt_count)),
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
    st.success(
        "The expense report is ready. Review the files before sending them for approval."
    )
    download_columns = st.columns(2 if package.pdf_bytes else 1)
    with download_columns[0]:
        st.download_button(
            "Download completed Excel report",
            data=package.workbook_bytes,
            file_name=f"{package.basename}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
    if package.pdf_bytes:
        with download_columns[1]:
            st.download_button(
                "Download combined PDF packet",
                data=package.pdf_bytes,
                file_name=f"{package.basename}.pdf",
                mime="application/pdf",
                width="stretch",
            )
    elif package.pdf_error:
        st.warning(package.pdf_error)

    if eml_bytes:
        st.download_button(
            "Download Outlook email draft with attachments",
            data=eml_bytes,
            file_name=f"{package.basename}_Approval_Email.eml",
            mime="message/rfc822",
            width="stretch",
        )

    subject = f"{details.employee_name} expense report - {details.report_date:%Y-%m-%d}"
    body = build_plain_body(
        [
            ("Employee", details.employee_name),
            ("Account", details.account),
            ("Total reimbursement", f"${package.total:,.2f}"),
        ],
        greeting=(
            f"Good afternoon, {details.approver_name.split()[0]}. Please review and approve the attached expense report."
            if details.approver_name.split()
            else "Good afternoon. Please review and approve the attached expense report."
        ),
    )
    st.link_button(
        "Open a new email without attachments ↗",
        build_mailto_url(to=details.approver_email, subject=subject, body=body),
        width="stretch",
    )
    attached_names = [name for name, _ in email_attachments_for_package(package)]
    st.info(
        "Windows Outlook: open the downloaded .eml draft; it already contains "
        + " and ".join(attached_names)
        + ". On iPhone/iPad or Outlook web, download the generated files, use the "
        "new-email button, and attach them manually. The report's signature line "
        "is intentionally blank and should be completed only by the employee."
    )


def _unique_receipts(uploads) -> tuple[list[tuple[str, str, bytes]], list[str]]:
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


def _clear_removed_receipts(active_ids: set[str]) -> None:
    prior = set(st.session_state.get("expense_active_receipt_ids", set()) or set())
    removed = prior - active_ids
    for receipt_id in removed:
        token = receipt_id[:12]
        for key in list(st.session_state):
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
        "retry_receipt",
    )
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
    """Restore mirrored expense values before their widgets are instantiated."""
    snapshot = st.session_state.get("expense_draft_snapshot", {})
    if not isinstance(snapshot, dict):
        return
    for key, value in snapshot.items():
        st.session_state.setdefault(key, value)


def _reset_expense_report() -> None:
    """Clear only expense-workflow state and rotate the uploader widget."""
    next_nonce = int(st.session_state.get("expense_uploader_nonce", 0) or 0) + 1
    for key in list(st.session_state):
        if key.startswith("expense_"):
            st.session_state.pop(key, None)
    st.session_state["expense_uploader_nonce"] = next_nonce


def _receipt_visible_problems(index: int, item: ExpenseItem) -> list[str]:
    problems: list[str] = []
    if item.transaction_date is None:
        problems.append("transaction date")
    if not item.description:
        problems.append("description / business purpose")
    if parse_expense_amount(item.amount) is None:
        problems.append("reimbursable amount")
    if item.section == EXPENSE_SECTION_ENTERTAINMENT and not item.contact_name:
        problems.append("entertainment contact name")
    problems.extend(
        problem.split(": ", 1)[-1]
        for problem in allocation_problems(item.allocation, prefix=f"Receipt {index}")
    )
    return list(dict.fromkeys(problems))


def _allocation_summary(allocation: ExpenseAllocation) -> str:
    if allocation.kind == ALLOCATION_JOB:
        return " · ".join(
            value
            for value in (
                _ALLOCATION_LABELS[allocation.kind],
                allocation.job_number or "job number needed",
                allocation.account_cost_type or "account needed",
                allocation.cost_code_or_wo_type or "cost code needed",
            )
            if value
        )
    if allocation.kind == ALLOCATION_WORK_ORDER:
        return " · ".join(
            value
            for value in (
                _ALLOCATION_LABELS[allocation.kind],
                allocation.service_center or "service center needed",
                allocation.work_order_number or "work order needed",
            )
            if value
        )
    return " · ".join(
        value
        for value in (
            _ALLOCATION_LABELS[allocation.kind],
            allocation.company_number or "company needed",
            allocation.gl_account_number or "GL account needed",
        )
        if value
    )
