"""Employee-reimbursement workbook and submission-packet generation.

The official JDE workbook remains the source document.  This module fills only
its shaded input cells, adds a receipt worksheet after the form, and can ask
LibreOffice/Gotenberg to render the complete workbook as one PDF packet.  It
does not send email or approve an expense report.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from copy import copy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import requests
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.worksheet.pagebreak import Break
from PIL import Image, ImageOps, ImageSequence

from app.config import GOTENBERG_URL, PDF_BACKEND
from app.job_numbers import JOB_NUMBER_OPTIONS, job_number_identifier


BASE_DIR = Path(__file__).resolve().parent.parent
EXPENSE_TEMPLATE_PATH = (
    BASE_DIR
    / "templates"
    / "Employee_Reimbursement_Expense_Report_JDE_10012025.xlsx"
)

EXPENSE_SECTION_MISC = "miscellaneous"
EXPENSE_SECTION_ENTERTAINMENT = "entertainment"
EXPENSE_SECTIONS = (EXPENSE_SECTION_MISC, EXPENSE_SECTION_ENTERTAINMENT)

ALLOCATION_JOB = "job"
ALLOCATION_WORK_ORDER = "work_order"
ALLOCATION_OVERHEAD = "overhead"
ALLOCATION_KINDS = (ALLOCATION_JOB, ALLOCATION_WORK_ORDER, ALLOCATION_OVERHEAD)

MISCELLANEOUS_ROWS = tuple(range(24, 39))
ENTERTAINMENT_ROWS = tuple(range(45, 59))
MAX_MISCELLANEOUS_ITEMS = len(MISCELLANEOUS_ROWS)
MAX_ENTERTAINMENT_ITEMS = len(ENTERTAINMENT_ROWS)
MINIMUM_REIMBURSEMENT = Decimal("20.00")

_MAX_RECEIPT_PAGES_PER_FILE = 10
_MAX_RECEIPT_PIXELS = 40_000_000
_ATTACHMENT_MAX_SIZE = (1200, 1600)
_RECEIPT_PAGE_ROWS = 58
_EMAIL_SAFE_RAW_ATTACHMENT_BYTES = 18 * 1024 * 1024
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class ExpenseReportError(ValueError):
    """Raised when an expense package cannot be generated safely."""


@dataclass(frozen=True)
class ExpenseAllocation:
    """One JDE allocation route and its route-specific coding fields."""

    kind: str
    job_number: str = ""
    service_center: str = ""
    account_cost_type: str = ""
    cost_code_or_wo_type: str = ""
    work_order_number: str = ""
    company_number: str = ""
    department_number: str = ""
    ou_number: str = ""
    gl_account_number: str = ""


@dataclass(frozen=True)
class ExpenseItem:
    """Reviewed data for one uploaded receipt."""

    receipt_id: str
    filename: str
    file_bytes: bytes
    transaction_date: date | None
    description: str
    amount: Decimal | str | None
    section: str
    allocation: ExpenseAllocation
    merchant_name: str = ""
    contact_name: str = ""


@dataclass(frozen=True)
class ExpenseReportDetails:
    """Employee, routing, and approval information for one report."""

    account: str
    employee_name: str
    employee_number: str
    employee_home_bu: str
    report_date: date
    approver_name: str
    approver_email: str
    mail_destination: str = "home"
    satellite_office: str = ""


@dataclass(frozen=True)
class ExpensePackage:
    """Generated workbook plus an optional rendered PDF packet."""

    basename: str
    workbook_bytes: bytes
    pdf_bytes: bytes | None
    total: Decimal
    receipt_count: int
    pdf_error: str = ""


def parse_expense_amount(value: object) -> Decimal | None:
    """Return a positive two-decimal amount, or ``None`` for invalid input."""
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        amount = Decimal(str(value))
    else:
        text = str(value or "").strip()
        if not text:
            return None
        text = re.sub(r"\bUSD\b", "", text, flags=re.IGNORECASE).strip()
        if text.startswith("$"):
            text = text[1:].strip()
        if text.startswith("(") and text.endswith(")"):
            text = f"-{text[1:-1]}"
        if not re.fullmatch(
            r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?",
            text,
        ):
            return None
        try:
            amount = Decimal(text.replace(",", ""))
        except InvalidOperation:
            return None
    if not amount.is_finite() or amount <= 0 or amount > Decimal("9999999.99"):
        return None
    return amount.quantize(Decimal("0.01"))


def allocation_problems(allocation: ExpenseAllocation, *, prefix: str = "") -> list[str]:
    """Validate only the coding fields relevant to the selected allocation."""
    label = f"{prefix}: " if prefix else ""
    problems: list[str] = []
    if allocation.kind not in ALLOCATION_KINDS:
        return [f"{label}choose a valid allocation type"]

    if allocation.kind == ALLOCATION_JOB:
        if allocation.job_number not in JOB_NUMBER_OPTIONS:
            problems.append(f"{label}choose the job number")
        if not allocation.account_cost_type.strip():
            problems.append(f"{label}enter the account / cost type")
        if not allocation.cost_code_or_wo_type.strip():
            problems.append(f"{label}enter the cost code")
    elif allocation.kind == ALLOCATION_WORK_ORDER:
        if not allocation.service_center.strip():
            problems.append(f"{label}enter the service center number")
        if not allocation.account_cost_type.strip():
            problems.append(f"{label}enter the account / cost type")
        if not allocation.cost_code_or_wo_type.strip():
            problems.append(f"{label}enter the work-order type")
        if not allocation.work_order_number.strip():
            problems.append(f"{label}enter the work-order number")
    else:
        for value, field in (
            (allocation.company_number, "company number"),
            (allocation.department_number, "department number"),
            (allocation.ou_number, "OU number"),
            (allocation.gl_account_number, "GL account number"),
        ):
            if not value.strip():
                problems.append(f"{label}enter the {field}")
    return problems


def validate_expense_report(
    details: ExpenseReportDetails,
    items: list[ExpenseItem],
) -> list[str]:
    """Return actionable blocking problems in interaction order."""
    problems: list[str] = []
    for value, field in (
        (details.account, "choose the account / contract"),
        (details.employee_name, "enter the employee name"),
        (details.employee_number, "enter the employee number"),
        (details.employee_home_bu, "enter the employee home BU"),
        (details.approver_name, "enter the contract administrator's name"),
        (details.approver_email, "enter the contract administrator's email"),
    ):
        if not str(value or "").strip():
            problems.append(field)
    if not _looks_like_email(details.approver_email):
        problems.append("enter a valid contract administrator email")
    if details.mail_destination not in {"home", "satellite"}:
        problems.append("choose where the reimbursement check should be mailed")
    if details.mail_destination == "satellite" and not details.satellite_office.strip():
        problems.append("enter the satellite office")

    if not items:
        problems.append("include at least one receipt")
        return _deduplicate(problems)

    seen_receipts: set[str] = set()
    misc_count = 0
    entertainment_count = 0
    total = Decimal("0")
    for index, item in enumerate(items, 1):
        prefix = f"Receipt {index}"
        if not item.receipt_id or item.receipt_id in seen_receipts:
            problems.append(f"{prefix}: remove the duplicate receipt")
        seen_receipts.add(item.receipt_id)
        if item.transaction_date is None:
            problems.append(f"{prefix}: enter the transaction date")
        if not item.description.strip():
            problems.append(f"{prefix}: enter the description or business purpose")
        amount = parse_expense_amount(item.amount)
        if amount is None:
            problems.append(f"{prefix}: enter a valid reimbursable amount")
        else:
            total += amount
        if item.section == EXPENSE_SECTION_MISC:
            misc_count += 1
        elif item.section == EXPENSE_SECTION_ENTERTAINMENT:
            entertainment_count += 1
            if not item.contact_name.strip():
                problems.append(f"{prefix}: enter the entertainment contact name")
        else:
            problems.append(f"{prefix}: choose Miscellaneous or Entertainment")
        problems.extend(allocation_problems(item.allocation, prefix=prefix))
        if not item.file_bytes:
            problems.append(f"{prefix}: upload the receipt image or PDF again")

    if misc_count > MAX_MISCELLANEOUS_ITEMS:
        problems.append(
            f"split the report: the official form allows {MAX_MISCELLANEOUS_ITEMS} "
            "Miscellaneous receipts"
        )
    if entertainment_count > MAX_ENTERTAINMENT_ITEMS:
        problems.append(
            f"split the report: the official form allows {MAX_ENTERTAINMENT_ITEMS} "
            "Entertainment receipts"
        )
    if total <= MINIMUM_REIMBURSEMENT:
        problems.append("the total reimbursement must exceed $20.00")
    return _deduplicate(problems)


def expense_report_total(items: list[ExpenseItem]) -> Decimal:
    """Return the reviewed total; invalid values contribute zero."""
    return sum(
        (parse_expense_amount(item.amount) or Decimal("0") for item in items),
        Decimal("0"),
    )


def expense_report_warnings(
    details: ExpenseReportDetails,
    items: list[ExpenseItem],
) -> list[str]:
    """Return non-blocking checks that require human confirmation."""
    warnings: list[str] = []
    possible_duplicates: dict[tuple[date, Decimal, str], list[int]] = {}
    for index, item in enumerate(items, 1):
        if item.transaction_date:
            if item.transaction_date > details.report_date:
                warnings.append(
                    f"Receipt {index} is dated after the report date"
                )
            elif (details.report_date - item.transaction_date).days > 366:
                warnings.append(
                    f"Receipt {index} is more than one year older than the report date"
                )
        amount = parse_expense_amount(item.amount)
        merchant = re.sub(
            r"[^a-z0-9]+", "", item.merchant_name.casefold()
        )
        if item.transaction_date and amount is not None and merchant:
            key = (item.transaction_date, amount, merchant)
            possible_duplicates.setdefault(key, []).append(index)
    for indices in possible_duplicates.values():
        if len(indices) > 1:
            labels = ", ".join(str(index) for index in indices)
            warnings.append(
                f"Receipts {labels} have the same merchant, date, and amount; "
                "confirm they are separate purchases"
            )
    return _deduplicate(warnings)


def expense_report_signature(
    details: ExpenseReportDetails,
    items: list[ExpenseItem],
) -> str:
    """Stable signature used to suppress stale downloads after an edit."""
    digest = hashlib.sha256()
    digest.update(repr(details).encode("utf-8"))
    for item in items:
        digest.update(
            repr(
                (
                    item.receipt_id,
                    item.filename,
                    item.transaction_date,
                    item.description,
                    item.amount,
                    item.section,
                    item.allocation,
                    item.merchant_name,
                    item.contact_name,
                )
            ).encode("utf-8")
        )
        digest.update(hashlib.sha256(item.file_bytes).digest())
    return digest.hexdigest()


def build_expense_workbook(
    details: ExpenseReportDetails,
    items: list[ExpenseItem],
    *,
    template_path: Path = EXPENSE_TEMPLATE_PATH,
) -> bytes:
    """Fill the official workbook and append printable receipt images."""
    problems = validate_expense_report(details, items)
    if problems:
        raise ExpenseReportError("; ".join(problems))
    if not template_path.is_file():
        raise ExpenseReportError(
            "The official employee-reimbursement workbook template is missing."
        )

    workbook = load_workbook(template_path)
    if "EXPENSE REIMBURSEMENT" not in workbook.sheetnames:
        raise ExpenseReportError("The reimbursement template has an unexpected layout.")
    form = workbook["EXPENSE REIMBURSEMENT"]
    _verify_template_anchors(form)
    _fill_report_header(form, details)

    ordered_items = _items_grouped_for_form(items)
    miscellaneous = [
        item for item in ordered_items if item.section == EXPENSE_SECTION_MISC
    ]
    entertainment = [
        item for item in ordered_items
        if item.section == EXPENSE_SECTION_ENTERTAINMENT
    ]
    for row, item in zip(MISCELLANEOUS_ROWS, miscellaneous):
        _fill_expense_row(form, row, item, entertainment=False)
    for row, item in zip(ENTERTAINMENT_ROWS, entertainment):
        _fill_expense_row(form, row, item, entertainment=True)

    # Keep formulas intact for an editable workbook and force Excel/LibreOffice
    # to refresh their cached values when the file opens or renders.
    form["H39"] = "=SUM(H24:H38)"
    form["H59"] = "=SUM(H45:H58)"
    form["Q60"] = "=H18+H39+H59"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"

    if "RECEIPTS" in workbook.sheetnames:
        workbook.remove(workbook["RECEIPTS"])
    receipt_sheet = workbook.create_sheet("RECEIPTS")
    image_buffers: list[BytesIO] = []
    # Receipt pages follow the same grouped order as the form rows, so the
    # packet remains easy to audit when a report uses multiple coding strings.
    _build_receipt_sheet(receipt_sheet, ordered_items, image_buffers)

    payload = BytesIO()
    workbook.save(payload)
    return payload.getvalue()


def build_expense_package(
    details: ExpenseReportDetails,
    items: list[ExpenseItem],
    *,
    include_pdf: bool = True,
) -> ExpensePackage:
    """Generate the workbook and, when available, its combined PDF packet."""
    workbook_bytes = build_expense_workbook(details, items)
    pdf_bytes = None
    pdf_error = ""
    if include_pdf:
        try:
            pdf_bytes = convert_expense_workbook_to_pdf(workbook_bytes)
        except ExpenseReportError as exc:
            # The official workbook is still a complete submission artifact.
            # A renderer outage must not force the operator to re-enter data.
            pdf_error = str(exc)
    basename = expense_report_basename(details)
    return ExpensePackage(
        basename=basename,
        workbook_bytes=workbook_bytes,
        pdf_bytes=pdf_bytes,
        total=expense_report_total(items),
        receipt_count=len(items),
        pdf_error=pdf_error,
    )


def convert_expense_workbook_to_pdf(workbook_bytes: bytes) -> bytes:
    """Render both workbook sheets as one PDF, using the configured backend."""
    backend = str(PDF_BACKEND or "libreoffice").strip().lower()
    if backend == "gotenberg":
        endpoint = urljoin(GOTENBERG_URL.rstrip("/") + "/", "forms/libreoffice/convert")
        response = requests.post(
            endpoint,
            files={
                "files": (
                    "expense_report.xlsx",
                    workbook_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            timeout=120,
        )
        if response.status_code != 200 or not response.content.startswith(b"%PDF"):
            raise ExpenseReportError(
                f"The PDF service could not render the expense report (HTTP "
                f"{response.status_code})."
            )
        return response.content
    if backend != "libreoffice":
        raise ExpenseReportError(
            f"Expense-report PDF generation does not support PDF_BACKEND={backend!r}."
        )

    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise ExpenseReportError(
            "LibreOffice is unavailable, so the Excel report was created but the "
            "combined PDF could not be rendered."
        )
    with tempfile.TemporaryDirectory(prefix="expense-report-") as temp_name:
        temp = Path(temp_name)
        source = temp / "expense_report.xlsx"
        source.write_bytes(workbook_bytes)
        profile_uri = (temp / "libreoffice-profile").resolve().as_uri()
        result = subprocess.run(
            [
                executable,
                "--headless",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                "pdf:calc_pdf_Export",
                "--outdir",
                str(temp),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        rendered = temp / "expense_report.pdf"
        if not rendered.is_file():
            detail = (result.stderr or result.stdout or "unknown error").strip()[:300]
            raise ExpenseReportError(
                f"LibreOffice could not render the combined PDF: {detail}"
            )
        payload = rendered.read_bytes()
        if not payload.startswith(b"%PDF"):
            raise ExpenseReportError("LibreOffice returned an invalid PDF file.")
        return payload


def expense_report_basename(details: ExpenseReportDetails) -> str:
    """Return a filesystem-safe, useful attachment base name."""
    employee = _SAFE_FILENAME_RE.sub("_", details.employee_name.strip()).strip("_ .")
    employee = employee or "Employee"
    return f"{details.report_date:%Y.%m.%d}_Expense_Report_{employee}"[:120]


def email_attachments_for_package(package: ExpensePackage) -> list[tuple[str, bytes]]:
    """Choose draft-email attachments without exceeding common mail limits."""
    workbook = (f"{package.basename}.xlsx", package.workbook_bytes)
    if not package.pdf_bytes:
        return [workbook]
    pdf = (f"{package.basename}.pdf", package.pdf_bytes)
    if len(package.workbook_bytes) + len(package.pdf_bytes) <= _EMAIL_SAFE_RAW_ATTACHMENT_BYTES:
        return [workbook, pdf]
    # The workbook is the official editable form and already contains every
    # receipt, so it remains the single source of truth for a large package.
    return [workbook]


def receipt_preview_bytes(file_bytes: bytes, filename: str) -> bytes:
    """Return a bounded JPEG preview of the first receipt page/frame."""
    pages = receipt_attachment_pages(file_bytes, filename, max_pages=1)
    if not pages:
        raise ExpenseReportError("The receipt did not contain a readable page.")
    return pages[0]


def receipt_attachment_pages(
    file_bytes: bytes,
    filename: str,
    *,
    max_pages: int = _MAX_RECEIPT_PAGES_PER_FILE,
) -> list[bytes]:
    """Normalize all receipt pages/frames to compact, print-readable JPEGs."""
    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf":
        import fitz

        pages: list[bytes] = []
        try:
            with fitz.open(stream=file_bytes, filetype="pdf") as document:
                if document.page_count > max_pages:
                    raise ExpenseReportError(
                        f"{filename} has {document.page_count} pages; the limit is {max_pages}."
                    )
                for page in document:
                    pixmap = page.get_pixmap(dpi=150, alpha=False)
                    image = Image.open(BytesIO(pixmap.tobytes("png")))
                    pages.append(_compact_receipt_image(image))
        except ExpenseReportError:
            raise
        except Exception as exc:
            raise ExpenseReportError(f"{filename} is not a readable PDF receipt.") from exc
        if not pages:
            raise ExpenseReportError(f"{filename} does not contain a receipt page.")
        return pages

    if suffix in {".heic", ".heif", ".hif"}:
        from pillow_heif import register_heif_opener

        register_heif_opener(thumbnails=False)
    try:
        pages = []
        with Image.open(BytesIO(file_bytes)) as image:
            frame_count = int(getattr(image, "n_frames", 1))
            if frame_count > max_pages:
                raise ExpenseReportError(
                    f"{filename} has {frame_count} frames; the limit is {max_pages}."
                )
            for frame in ImageSequence.Iterator(image):
                pages.append(_compact_receipt_image(frame.copy()))
        if not pages:
            raise ExpenseReportError(f"{filename} does not contain a receipt image.")
        return pages
    except ExpenseReportError:
        raise
    except Exception as exc:
        raise ExpenseReportError(f"{filename} is not a readable receipt image.") from exc


def _compact_receipt_image(source: Image.Image) -> bytes:
    image = ImageOps.exif_transpose(source)
    if image.width * image.height > _MAX_RECEIPT_PIXELS:
        raise ExpenseReportError(
            f"Receipt image is too large ({image.width}×{image.height})."
        )
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        background = Image.new("RGB", image.size, "white")
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        background.paste(image.convert("RGB"), mask=alpha)
        image = background
    else:
        image = image.convert("RGB")
    image = ImageOps.contain(image, _ATTACHMENT_MAX_SIZE)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=78, optimize=True, progressive=True)
    return buffer.getvalue()


def _verify_template_anchors(sheet) -> None:
    anchors = {
        "B2": "REIMBURSEMENT OF EXPENSES",
        "B20": "MISCELLANEOUS",
        "B41": "ENTERTAINMENT",
        "J60": "TOTAL REIMBURSEMENT",
    }
    for cell, expected in anchors.items():
        if expected not in str(sheet[cell].value or ""):
            raise ExpenseReportError(
                f"The reimbursement template changed near cell {cell}; no data was written."
            )


def _fill_report_header(sheet, details: ExpenseReportDetails) -> None:
    sheet["C5"] = details.employee_name.strip()
    sheet["G5"] = details.employee_number.strip()
    sheet["K5"] = details.employee_home_bu.strip()
    sheet["P5"] = details.report_date
    sheet["P5"].number_format = "mm-dd-yy"
    sheet["B62"] = "x" if details.mail_destination == "home" else ""
    sheet["B64"] = "x" if details.mail_destination == "satellite" else ""
    if details.mail_destination == "satellite":
        sheet["F64"] = details.satellite_office.strip()
    # The workbook intentionally leaves the signature line blank. Filling a
    # print-name cell is not equivalent to certifying or signing the report.


def _items_grouped_for_form(items: list[ExpenseItem]) -> list[ExpenseItem]:
    """Group rows by section and coding, preserving upload order within a group."""
    section_order = {
        EXPENSE_SECTION_MISC: 0,
        EXPENSE_SECTION_ENTERTAINMENT: 1,
    }

    def key(item: ExpenseItem) -> tuple[object, ...]:
        allocation = item.allocation
        return (
            section_order.get(item.section, 9),
            allocation.kind,
            allocation.job_number,
            allocation.service_center,
            allocation.account_cost_type,
            allocation.cost_code_or_wo_type,
            allocation.work_order_number,
            allocation.company_number,
            allocation.department_number,
            allocation.ou_number,
            allocation.gl_account_number,
        )

    return sorted(items, key=key)


def _fill_expense_row(sheet, row: int, item: ExpenseItem, *, entertainment: bool) -> None:
    amount = parse_expense_amount(item.amount)
    assert item.transaction_date is not None and amount is not None
    sheet.cell(row=row, column=2, value=item.transaction_date).number_format = "mm-dd-yy"
    sheet.cell(row=row, column=3, value=item.description.strip())
    if entertainment:
        sheet.cell(row=row, column=6, value=item.contact_name.strip())
    sheet.cell(row=row, column=8, value=float(amount)).number_format = '"$"#,##0.00'
    _fill_allocation(sheet, row, item.allocation)


def _fill_allocation(sheet, row: int, allocation: ExpenseAllocation) -> None:
    if allocation.kind == ALLOCATION_JOB:
        job_identifier = job_number_identifier(allocation.job_number)
        if not job_identifier:
            raise ExpenseReportError("The selected job number has no usable identifier.")
        _write_code(sheet, row, 9, job_identifier)
        _write_code(sheet, row, 10, allocation.account_cost_type)
        _write_code(sheet, row, 11, allocation.cost_code_or_wo_type)
    elif allocation.kind == ALLOCATION_WORK_ORDER:
        _write_code(sheet, row, 9, allocation.service_center)
        _write_code(sheet, row, 10, allocation.account_cost_type)
        _write_code(sheet, row, 11, allocation.cost_code_or_wo_type)
        _write_code(sheet, row, 12, allocation.work_order_number)
    else:
        _write_code(sheet, row, 14, allocation.company_number)
        _write_code(sheet, row, 15, allocation.department_number)
        _write_code(sheet, row, 16, allocation.ou_number)
        _write_code(sheet, row, 17, allocation.gl_account_number)


def _write_code(sheet, row: int, column: int, value: str) -> None:
    cell = sheet.cell(row=row, column=column, value=str(value or "").strip())
    cell.number_format = "@"


def _build_receipt_sheet(sheet, items: list[ExpenseItem], buffers: list[BytesIO]) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_LETTER
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins.left = 0.35
    sheet.page_margins.right = 0.35
    sheet.page_margins.top = 0.4
    sheet.page_margins.bottom = 0.4
    for column in range(1, 13):
        sheet.column_dimensions[chr(64 + column)].width = 8.2

    block_index = 0
    for receipt_number, item in enumerate(items, 1):
        pages = receipt_attachment_pages(item.file_bytes, item.filename)
        for page_number, image_bytes in enumerate(pages, 1):
            start = block_index * _RECEIPT_PAGE_ROWS + 1
            end = start + _RECEIPT_PAGE_ROWS - 1
            sheet.merge_cells(start_row=start, start_column=1, end_row=start, end_column=12)
            sheet.cell(start, 1).value = (
                f"Receipt {receipt_number} of {len(items)}"
                + (f" · page {page_number} of {len(pages)}" if len(pages) > 1 else "")
            )
            header_font = copy(sheet.cell(start, 1).font)
            header_font.bold = True
            header_font.size = 14
            header_font.color = "092B24"
            sheet.cell(start, 1).font = header_font
            sheet.merge_cells(
                start_row=start + 1,
                start_column=1,
                end_row=start + 1,
                end_column=12,
            )
            amount = parse_expense_amount(item.amount)
            detail = " · ".join(
                part
                for part in (
                    item.transaction_date.strftime("%m/%d/%Y") if item.transaction_date else "",
                    item.merchant_name.strip(),
                    f"${amount:,.2f}" if amount is not None else "",
                    Path(item.filename).name,
                )
                if part
            )
            sheet.cell(start + 1, 1).value = detail
            detail_font = copy(sheet.cell(start + 1, 1).font)
            detail_font.size = 9
            detail_font.color = "557F7F"
            sheet.cell(start + 1, 1).font = detail_font

            buffer = BytesIO(image_bytes)
            buffers.append(buffer)
            excel_image = ExcelImage(buffer)
            available_width = 690
            available_height = 760
            scale = min(
                available_width / excel_image.width,
                available_height / excel_image.height,
                1,
            )
            excel_image.width = int(excel_image.width * scale)
            excel_image.height = int(excel_image.height * scale)
            sheet.add_image(excel_image, f"A{start + 3}")
            if block_index:
                sheet.row_breaks.append(Break(id=start - 1))
            for row in range(start, end + 1):
                sheet.row_dimensions[row].height = 14
            sheet.row_dimensions[start].height = 24
            sheet.row_dimensions[start + 1].height = 18
            block_index += 1

    last_row = max(1, block_index * _RECEIPT_PAGE_ROWS)
    sheet.print_area = f"A1:L{last_row}"
    sheet.oddFooter.center.text = "Receipt attachments"
    sheet.oddFooter.right.text = "Page &P of &N"


def _looks_like_email(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text)
        and len(text) <= 254
    )


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
