from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import date
from decimal import Decimal
from io import BytesIO

import fitz
import pytest
from openpyxl import load_workbook
from PIL import Image, ImageDraw

from app.expense_report import (
    ALLOCATION_JOB,
    ALLOCATION_OVERHEAD,
    ALLOCATION_WORK_ORDER,
    EXPENSE_SECTION_ENTERTAINMENT,
    EXPENSE_SECTION_MISC,
    ExpenseAllocation,
    ExpenseItem,
    ExpenseReportDetails,
    build_expense_package,
    build_expense_workbook,
    expense_report_signature,
    expense_report_warnings,
    parse_expense_amount,
    receipt_attachment_pages,
    validate_expense_report,
)
from app.job_numbers import RRH_JOB_NUMBERS


def _receipt_bytes(text: str = "TOTAL $31.25") -> bytes:
    image = Image.new("RGB", (800, 1100), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((20, 20, 780, 1080), outline="black", width=3)
    drawing.multiline_text((70, 80), text, fill="black", spacing=18)
    payload = BytesIO()
    image.save(payload, format="JPEG", quality=90)
    return payload.getvalue()


def _details(**changes) -> ExpenseReportDetails:
    values = {
        "account": "Rochester Regional Health",
        "employee_name": "Evan Roden",
        "employee_number": "00133509",
        "employee_home_bu": "02037",
        "report_date": date(2026, 8, 11),
        "approver_name": "David Siegal",
        "approver_email": "david.siegal@enfrasolutions.com",
        "mail_destination": "home",
        "satellite_office": "",
    }
    values.update(changes)
    return ExpenseReportDetails(**values)


def _job_allocation() -> ExpenseAllocation:
    return ExpenseAllocation(
        kind=ALLOCATION_JOB,
        job_number=RRH_JOB_NUMBERS[0],
        account_cost_type="05490",
        cost_code_or_wo_type="01ASTART",
    )


def _item(
    receipt_id: str = "receipt-a",
    *,
    section: str = EXPENSE_SECTION_MISC,
    amount: str = "31.25",
    allocation: ExpenseAllocation | None = None,
    contact_name: str = "",
) -> ExpenseItem:
    return ExpenseItem(
        receipt_id=receipt_id,
        filename=f"{receipt_id}.jpg",
        file_bytes=_receipt_bytes(),
        transaction_date=date(2026, 8, 10),
        description="Business travel parking",
        amount=amount,
        section=section,
        allocation=allocation or _job_allocation(),
        merchant_name="Test Merchant",
        contact_name=contact_name,
    )


def test_workbook_preserves_template_codes_formulas_and_receipt_order():
    overhead = ExpenseAllocation(
        kind=ALLOCATION_OVERHEAD,
        company_number="0200",
        department_number="0700",
        ou_number="09000",
        gl_account_number="07801",
    )
    items = [
        _item("parking"),
        _item(
            "customer-meal",
            section=EXPENSE_SECTION_ENTERTAINMENT,
            amount="48.75",
            allocation=overhead,
            contact_name="Customer Contact",
        ),
    ]

    payload = build_expense_workbook(_details(), items)
    workbook = load_workbook(BytesIO(payload), data_only=False)
    form = workbook["EXPENSE REIMBURSEMENT"]
    receipts = workbook["RECEIPTS"]

    assert workbook.sheetnames == ["EXPENSE REIMBURSEMENT", "RECEIPTS"]
    assert form["C5"].value == "Evan Roden"
    assert form["G5"].value == "00133509"
    assert form["K5"].value == "02037"
    assert form["P5"].value.date() == date(2026, 8, 11)
    assert form["B62"].value == "x"

    assert form["B24"].value.date() == date(2026, 8, 10)
    assert form["C24"].value == "Business travel parking"
    assert form["H24"].value == 31.25
    assert form["I24"].value == "695400022"
    assert form["J24"].value == "05490"
    assert form["K24"].value == "01ASTART"
    assert form["J24"].number_format == "@"

    assert form["C45"].value == "Business travel parking"
    assert form["F45"].value == "Customer Contact"
    assert form["N45"].value == "0200"
    assert form["O45"].value == "0700"
    assert form["P45"].value == "09000"
    assert form["Q45"].value == "07801"
    assert form["H39"].value == "=SUM(H24:H38)"
    assert form["H59"].value == "=SUM(H45:H58)"
    assert form["Q60"].value == "=H18+H39+H59"

    assert len(receipts._images) == 2
    assert receipts["A1"].value == "Receipt 1 of 2"
    assert receipts["A59"].value == "Receipt 2 of 2"
    assert str(receipts.print_area) == "'RECEIPTS'!$A$1:$L$116"


def test_multiple_coding_strings_are_grouped_and_receipts_follow_form_order():
    overhead = ExpenseAllocation(
        kind=ALLOCATION_OVERHEAD,
        company_number="2000",
        department_number="700",
        ou_number="9000",
        gl_account_number="7801",
    )
    overhead_item = replace(
        _item("overhead", allocation=overhead),
        description="Overhead item",
    )
    job_item = replace(_item("job"), description="Job item")

    payload = build_expense_workbook(_details(), [overhead_item, job_item])
    workbook = load_workbook(BytesIO(payload), data_only=False)
    form = workbook["EXPENSE REIMBURSEMENT"]
    receipts = workbook["RECEIPTS"]

    assert form["C24"].value == "Job item"
    assert form["C25"].value == "Overhead item"
    assert "job.jpg" in receipts["A2"].value
    assert "overhead.jpg" in receipts["A60"].value


def test_report_validation_keeps_unknown_required_values_blocking():
    work_order = ExpenseAllocation(kind=ALLOCATION_WORK_ORDER)
    item = _item(
        section=EXPENSE_SECTION_ENTERTAINMENT,
        amount="19.99",
        allocation=work_order,
    )

    problems = validate_expense_report(
        _details(approver_email="not-an-email"),
        [item],
    )

    assert "enter a valid contract administrator email" in problems
    assert "Receipt 1: enter the entertainment contact name" in problems
    assert "Receipt 1: enter the service center number" in problems
    assert "Receipt 1: enter the account / cost type" in problems
    assert "Receipt 1: enter the work-order type" in problems
    assert "Receipt 1: enter the work-order number" in problems
    assert "the total reimbursement must exceed $20.00" in problems


def test_duplicate_receipt_is_blocked_even_when_other_fields_are_valid():
    first = _item("same")
    second = _item("same", amount="22.00")

    problems = validate_expense_report(_details(), [first, second])

    assert "Receipt 2: remove the duplicate receipt" in problems


def test_amount_parser_does_not_turn_arbitrary_text_into_money():
    assert parse_expense_amount("$1,234.50 USD") == Decimal("1234.50")
    assert parse_expense_amount("amount 12.00") is None
    assert parse_expense_amount("1,23.00") is None
    assert parse_expense_amount("0.00") is None


def test_soft_duplicate_and_date_checks_warn_without_blocking():
    first = _item("one")
    second = _item("two", amount="31.25")
    warnings = expense_report_warnings(
        _details(report_date=date(2026, 8, 9)),
        [first, second],
    )

    assert "Receipt 1 is dated after the report date" in warnings
    assert "Receipt 2 is dated after the report date" in warnings
    assert any("same merchant, date, and amount" in warning for warning in warnings)


def test_signature_is_stable_for_the_same_receipt_bytes():
    item = _item("large")
    signature = expense_report_signature(_details(), [item])

    assert len(signature) == 64
    assert signature == expense_report_signature(_details(), [item])


def test_receipt_image_is_rotated_bounded_and_not_upscaled():
    source = Image.new("RGB", (2400, 3200), "white")
    payload = BytesIO()
    source.save(payload, format="JPEG", quality=90)

    pages = receipt_attachment_pages(payload.getvalue(), "phone-photo.jpg")
    normalized = Image.open(BytesIO(pages[0]))

    assert len(pages) == 1
    assert max(normalized.size) <= 1600
    assert normalized.size == (1200, 1600)


@pytest.mark.skipif(
    not (shutil.which("libreoffice") or shutil.which("soffice")),
    reason="LibreOffice is not installed in this test environment",
)
def test_combined_pdf_places_form_before_each_receipt():
    package = build_expense_package(
        _details(),
        [_item("one"), _item("two", amount="22.00")],
    )

    assert package.pdf_error == ""
    assert package.pdf_bytes is not None
    with fitz.open(stream=package.pdf_bytes, filetype="pdf") as document:
        assert document.page_count == 3
        assert "REIMBURSEMENT OF EXPENSES" in document[0].get_text()
        assert "Receipt 1 of 2" in document[1].get_text()
        assert "Receipt 2 of 2" in document[2].get_text()
