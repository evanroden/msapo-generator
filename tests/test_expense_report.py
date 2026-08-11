from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import date
from decimal import Decimal
from email import policy
from email.parser import BytesParser
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
    ExpensePackage,
    ExpenseReportDetails,
    MileageItem,
    build_expense_package,
    build_expense_workbook,
    email_attachments_for_package,
    employee_signature_png,
    expense_report_signature,
    expense_report_warnings,
    irs_business_mileage_rate,
    parse_expense_amount,
    parse_mileage,
    receipt_attachment_pages,
    total_reimbursement,
    validate_expense_report,
)
from app.job_numbers import RRH_JOB_NUMBERS
from app.expense_ui import _build_expense_eml


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
        "employee_home_bu": "RRH",
        "report_date": date(2026, 8, 11),
        "approver_name": "David Siegal",
        "approver_email": "david.siegal@enfrasolutions.com",
        "mail_destination": "home",
        "satellite_office": "",
        "employee_signature_confirmed": True,
    }
    values.update(changes)
    return ExpenseReportDetails(**values)


def _job_allocation(
    *,
    job: str = RRH_JOB_NUMBERS[0],
    cost_type: str = "5490",
    cost_code: str = "01AMA",
) -> ExpenseAllocation:
    return ExpenseAllocation(
        kind=ALLOCATION_JOB,
        job_number=job,
        account_cost_type=cost_type,
        cost_code_or_wo_type=cost_code,
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


def _mileage(
    entry_id: str = "mileage-1",
    *,
    travel_date: date = date(2026, 8, 10),
    miles: str = "10",
    allocation: ExpenseAllocation | None = None,
) -> MileageItem:
    return MileageItem(
        entry_id=entry_id,
        transaction_date=travel_date,
        purpose="RRH site visit",
        destination="United Memorial Medical Center",
        miles=miles,
        allocation=allocation or _job_allocation(),
    )


def test_workbook_matches_approved_rrh_job_only_layout_and_receipt_order():
    startup = _job_allocation(job=RRH_JOB_NUMBERS[1], cost_code="02AMA")
    items = [
        _item("parking"),
        _item(
            "customer-meal",
            section=EXPENSE_SECTION_ENTERTAINMENT,
            amount="48.75",
            allocation=startup,
            contact_name="Customer Contact",
        ),
    ]

    payload = build_expense_workbook(_details(), items)
    workbook = load_workbook(BytesIO(payload), data_only=False)
    form = workbook["EXPENSE REIMBURSEMENT"]
    receipts = workbook["RECEIPTS"]

    assert workbook.sheetnames == ["EXPENSE REIMBURSEMENT", "RECEIPTS"]
    assert form["B2"].value == "REIMBURSEMENT OF EXPENSES - 01.01.2026"
    assert form["B6"].value == "GAS MILEAGE @ $0.76 PER MILE"
    assert form["C5"].value == "Evan Roden"
    assert form["G5"].value == "00133509"
    assert form["K5"].value == "RRH"
    assert form["P5"].value.date() == date(2026, 8, 11)
    assert form["B62"].value == "x"
    assert form["C68"].value == "Evan Roden"
    assert form["D66"].value == "Date: 8/11/26"
    assert len(form._images) == 1

    assert form["B24"].value.date() == date(2026, 8, 10)
    assert form["C24"].value == "Business travel parking"
    assert form["H24"].value == 31.25
    assert form["I24"].value == "695400022"
    assert form["J24"].value == "5490"
    assert form["K24"].value == "01AMA"
    assert form["J24"].number_format == "@"

    assert form["C45"].value == "Business travel parking"
    assert form["F45"].value == "Customer Contact"
    assert form["I45"].value == "695400023"
    assert form["J45"].value == "5490"
    assert form["K45"].value == "02AMA"
    for row in (24, 45):
        assert form.cell(row, 12).value is None
        assert all(form.cell(row, column).value is None for column in range(14, 18))
    assert form["H18"].value == "=SUM(H10:H17)"
    assert form["H39"].value == "=SUM(H24:H38)"
    assert form["H59"].value == "=SUM(H45:H58)"
    assert form["Q60"].value == "=H18+H39+H59"

    assert len(receipts._images) == 2
    assert receipts["A1"].value == "Receipt 1 of 2"
    assert receipts["A59"].value == "Receipt 2 of 2"


def test_multiple_job_codes_are_grouped_and_receipts_follow_form_order():
    later_group = _item(
        "startup",
        allocation=_job_allocation(job=RRH_JOB_NUMBERS[1]),
    )
    first_group = replace(_item("operations"), description="O&M item")

    payload = build_expense_workbook(_details(), [later_group, first_group])
    workbook = load_workbook(BytesIO(payload), data_only=False)
    form = workbook["EXPENSE REIMBURSEMENT"]
    receipts = workbook["RECEIPTS"]

    assert form["C24"].value == "O&M item"
    assert form["I24"].value == "695400022"
    assert form["I25"].value == "695400023"
    assert "operations.jpg" in receipts["A2"].value
    assert "startup.jpg" in receipts["A60"].value


def test_validation_blocks_signature_and_non_job_routes():
    work_order = ExpenseAllocation(kind=ALLOCATION_WORK_ORDER)
    item = _item(
        section=EXPENSE_SECTION_ENTERTAINMENT,
        amount="19.99",
        allocation=work_order,
    )

    problems = validate_expense_report(
        _details(
            approver_email="not-an-email",
            employee_signature_confirmed=False,
        ),
        [item],
    )

    assert "enter a valid contract administrator email" in problems
    assert "confirm the generated employee signature" in problems
    assert "Receipt 1: enter the entertainment contact name" in problems
    assert (
        "Receipt 1: use job coding; work orders and Other Expenses are not used"
        in problems
    )
    assert "the total reimbursement must exceed $20.00" in problems
    overhead = replace(item, allocation=ExpenseAllocation(kind=ALLOCATION_OVERHEAD))
    assert any(
        "Other Expenses are not used" in problem
        for problem in validate_expense_report(_details(), [overhead])
    )


def test_validation_rejects_a_job_number_from_another_account():
    item = _item(
        allocation=_job_allocation(job="TULANE-695000028-ES JOB CCJ"),
    )

    problems = validate_expense_report(_details(), [item])

    assert "Receipt 1: choose a job number for the selected account" in problems


def test_duplicate_receipt_is_blocked_even_when_other_fields_are_valid():
    problems = validate_expense_report(
        _details(),
        [_item("same"), _item("same", amount="22.00")],
    )
    assert "Receipt 2: remove the duplicate receipt" in problems


def test_amount_mileage_parsers_and_irs_rate_boundaries():
    assert parse_expense_amount("$1,234.50 USD") == Decimal("1234.50")
    assert parse_expense_amount("amount 12.00") is None
    assert parse_mileage("1,234.50") == Decimal("1234.50")
    assert parse_mileage("ten") is None
    assert irs_business_mileage_rate(date(2025, 12, 31)) == Decimal("0.70")
    assert irs_business_mileage_rate(date(2026, 6, 30)) == Decimal("0.725")
    assert irs_business_mileage_rate(date(2026, 7, 1)) == Decimal("0.76")
    assert irs_business_mileage_rate(date(2027, 1, 1)) is None


def test_mileage_rows_use_travel_date_rate_and_leave_prohibited_columns_blank():
    mileage = [
        _mileage("first-half", travel_date=date(2026, 6, 30), miles="100"),
        _mileage("second-half", travel_date=date(2026, 7, 1), miles="100"),
    ]

    payload = build_expense_workbook(
        _details(report_date=date(2026, 7, 2)),
        [],
        mileage_items=mileage,
    )
    workbook = load_workbook(BytesIO(payload), data_only=False)
    form = workbook["EXPENSE REIMBURSEMENT"]

    assert workbook.sheetnames == ["EXPENSE REIMBURSEMENT"]
    assert form["B6"].value == "GAS MILEAGE @ APPLICABLE IRS RATE"
    assert form["G10"].value == 100
    assert form["H10"].value == "=ROUND(G10*0.725,2)"
    assert form["H11"].value == "=ROUND(G11*0.76,2)"
    assert form["I10"].value == "695400022"
    assert form["J10"].value == "5490"
    assert form["K10"].value == "01AMA"
    for row in (10, 11):
        assert form.cell(row, 12).value is None
        assert all(form.cell(row, column).value is None for column in range(14, 18))
    assert total_reimbursement([], mileage) == Decimal("148.50")


def test_unknown_future_mileage_rate_blocks_instead_of_guessing():
    problems = validate_expense_report(
        _details(report_date=date(2027, 1, 3)),
        [],
        [_mileage(travel_date=date(2027, 1, 2))],
    )
    assert any("IRS business-mileage rate" in problem for problem in problems)


def test_soft_duplicate_and_date_checks_warn_without_blocking():
    warnings = expense_report_warnings(
        _details(report_date=date(2026, 8, 9)),
        [_item("one"), _item("two", amount="31.25")],
        [_mileage(travel_date=date(2026, 8, 10))],
    )
    assert "Receipt 1 is dated after the report date" in warnings
    assert any("same merchant, date, and amount" in warning for warning in warnings)
    assert "Mileage 1 is dated after the report date" in warnings


def test_content_signature_changes_with_mileage_and_signature_confirmation():
    item = _item("large")
    mileage = _mileage()
    signature = expense_report_signature(_details(), [item], [mileage])

    assert len(signature) == 64
    assert signature == expense_report_signature(_details(), [item], [mileage])
    assert signature != expense_report_signature(
        _details(), [item], [replace(mileage, miles="11")]
    )
    assert signature != expense_report_signature(
        _details(employee_signature_confirmed=False), [item], [mileage]
    )


def test_generated_signature_is_a_bounded_transparent_png():
    payload = employee_signature_png("Dane Bertolet")
    image = Image.open(BytesIO(payload))
    assert image.format == "PNG"
    assert image.mode == "RGBA"
    assert image.width <= 1100
    assert image.height <= 190


def test_receipt_image_is_rotated_bounded_and_not_upscaled():
    source = Image.new("RGB", (2400, 3200), "white")
    payload = BytesIO()
    source.save(payload, format="JPEG", quality=90)

    pages = receipt_attachment_pages(payload.getvalue(), "phone-photo.jpg")
    normalized = Image.open(BytesIO(pages[0]))

    assert len(pages) == 1
    assert max(normalized.size) <= 1600
    assert normalized.size == (1200, 1600)


def test_email_uses_pdf_only_and_excel_remains_in_package():
    package = ExpensePackage(
        basename="expense",
        workbook_bytes=b"editable-xlsx",
        pdf_bytes=b"%PDF-submission",
        total=Decimal("50"),
        receipt_count=1,
    )
    assert email_attachments_for_package(package) == [
        ("expense.pdf", b"%PDF-submission")
    ]
    assert package.workbook_bytes == b"editable-xlsx"

    message = BytesParser(policy=policy.default).parsebytes(
        _build_expense_eml(_details(), package)
    )
    assert message["To"] == "david.siegal@enfrasolutions.com"
    assert message["X-Unsent"] == "1"
    assert [part.get_filename() for part in message.iter_attachments()] == [
        "expense.pdf"
    ]


@pytest.mark.skipif(
    not (shutil.which("libreoffice") or shutil.which("soffice")),
    reason="LibreOffice is not installed in this test environment",
)
def test_combined_pdf_places_signed_form_before_each_receipt():
    package = build_expense_package(
        _details(),
        [_item("one"), _item("two", amount="22.00")],
    )

    assert package.pdf_error == ""
    assert package.pdf_bytes is not None
    with fitz.open(stream=package.pdf_bytes, filetype="pdf") as document:
        assert document.page_count == 3
        assert "REIMBURSEMENT OF EXPENSES" in document[0].get_text()
        assert "Evan Roden" in document[0].get_text()
        assert "Receipt 1 of 2" in document[1].get_text()
        assert "Receipt 2 of 2" in document[2].get_text()
