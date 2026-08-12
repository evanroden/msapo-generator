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
from collections.abc import Sequence
from copy import copy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from math import ceil
from pathlib import Path
from urllib.parse import urljoin

import requests
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.pagebreak import Break
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.config import GOTENBERG_URL, PDF_BACKEND
from app.job_numbers import (
    JOB_NUMBER_OPTIONS,
    job_number_identifier,
    job_numbers_for_contract,
)


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
# RRH reimbursement reports use job coding only. Keep the historical constants
# import-compatible, but reject those routes so Work Order and Other Expenses
# columns can never be populated by this workflow.
ALLOCATION_KINDS = (ALLOCATION_JOB,)

MILEAGE_ROWS = tuple(range(10, 18))
MISCELLANEOUS_ROWS = tuple(range(24, 39))
ENTERTAINMENT_ROWS = tuple(range(45, 59))
MAX_MILEAGE_ITEMS = len(MILEAGE_ROWS)
MAX_MISCELLANEOUS_ITEMS = len(MISCELLANEOUS_ROWS)
MAX_ENTERTAINMENT_ITEMS = len(ENTERTAINMENT_ROWS)
MINIMUM_REIMBURSEMENT = Decimal("20.00")

# Official IRS business-mileage rates. The IRS made a mid-year change in 2026,
# so rates are selected from the travel date rather than the report date.
_IRS_BUSINESS_MILEAGE_RATES: tuple[tuple[date, date, Decimal], ...] = (
    (date(2024, 1, 1), date(2024, 12, 31), Decimal("0.67")),
    (date(2025, 1, 1), date(2025, 12, 31), Decimal("0.70")),
    (date(2026, 1, 1), date(2026, 6, 30), Decimal("0.725")),
    (date(2026, 7, 1), date(2026, 12, 31), Decimal("0.76")),
)

_MAX_RECEIPT_PAGES_PER_FILE = 10
_MAX_RECEIPT_PIXELS = 40_000_000
_ATTACHMENT_MAX_SIZE = (1200, 1600)
_RECEIPT_PAGE_ROWS = 58
_EMAIL_SAFE_RAW_ATTACHMENT_BYTES = 18 * 1024 * 1024
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SIGNATURE_FONT_CANDIDATES = (
    Path("/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
)
# Signature layout. The font is fitted to this canvas at render time rather than
# fixed, so a long name shrinks instead of being clipped.
_SIGNATURE_CANVAS = (1600, 260)
_SIGNATURE_MARGIN = (24, 18)
_SIGNATURE_MAX_FONT_SIZE = 112
# Absolute floor. If a name still does not fit at this size the renderer raises
# rather than emitting a clipped signature — see employee_signature_png.
_SIGNATURE_MIN_FONT_SIZE = 12
_SIGNATURE_MAX_NAME_CHARS = 160


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
    """One reviewed reimbursement line from an uploaded receipt."""

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
    # Split receipts use one unique receipt_id per reimbursement line while
    # sharing source_receipt_id. The source image is attached only once.
    source_receipt_id: str = ""


@dataclass(frozen=True)
class MileageItem:
    """One business-mileage row on the official reimbursement form."""

    entry_id: str
    transaction_date: date | None
    purpose: str
    destination: str
    miles: Decimal | str | float | None
    allocation: ExpenseAllocation


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
    employee_signature_confirmed: bool = False


@dataclass(frozen=True)
class ExpensePackage:
    """Generated workbook plus an optional rendered PDF packet."""

    basename: str
    workbook_bytes: bytes
    pdf_bytes: bytes | None
    total: Decimal
    receipt_count: int
    pdf_error: str = ""
    mileage_count: int = 0


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


def parse_mileage(value: object) -> Decimal | None:
    """Return a positive mileage quantity, or ``None`` for invalid input."""
    if isinstance(value, Decimal):
        miles = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        miles = Decimal(str(value))
    else:
        text = str(value or "").strip()
        if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", text):
            return None
        try:
            miles = Decimal(text.replace(",", ""))
        except InvalidOperation:
            return None
    if not miles.is_finite() or miles <= 0 or miles > Decimal("100000"):
        return None
    return miles.quantize(Decimal("0.01"))


def irs_business_mileage_rate(travel_date: date | None) -> Decimal | None:
    """Return the configured IRS business rate for one travel date."""
    if travel_date is None:
        return None
    for effective, through, rate in _IRS_BUSINESS_MILEAGE_RATES:
        if effective <= travel_date <= through:
            return rate
    return None


def mileage_reimbursement(item: MileageItem) -> Decimal | None:
    """Return the rounded reimbursement for one valid mileage row."""
    miles = parse_mileage(item.miles)
    rate = irs_business_mileage_rate(item.transaction_date)
    if miles is None or rate is None:
        return None
    return (miles * rate).quantize(Decimal("0.01"))


def allocation_problems(
    allocation: ExpenseAllocation,
    *,
    prefix: str = "",
    allowed_job_numbers: Sequence[str] | None = None,
) -> list[str]:
    """Validate the job coding used by RRH reimbursement reports."""
    label = f"{prefix}: " if prefix else ""
    problems: list[str] = []
    if allocation.kind != ALLOCATION_JOB:
        return [f"{label}use job coding; work orders and Other Expenses are not used"]
    if allocation.job_number not in JOB_NUMBER_OPTIONS:
        problems.append(f"{label}choose the job number")
    elif (
        allowed_job_numbers is not None
        and allocation.job_number not in allowed_job_numbers
    ):
        problems.append(f"{label}choose a job number for the selected account")
    if not allocation.account_cost_type.strip():
        problems.append(f"{label}enter the account / cost type")
    if not allocation.cost_code_or_wo_type.strip():
        problems.append(f"{label}enter the cost code")
    return problems


def validate_expense_report(
    details: ExpenseReportDetails,
    items: list[ExpenseItem],
    mileage_items: Sequence[MileageItem] = (),
) -> list[str]:
    """Return actionable blocking problems in interaction order."""
    problems: list[str] = []
    for value, field in (
        (details.account, "choose the account / contract"),
        (details.employee_name, "enter the employee name"),
        (details.employee_number, "enter the employee number"),
        (
            details.employee_home_bu,
            "enter the Employee Home Business Unit",
        ),
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
    if not details.employee_signature_confirmed:
        problems.append("confirm the generated employee signature")

    if not items and not mileage_items:
        problems.append("include at least one receipt or mileage entry")
        return _deduplicate(problems)

    seen_lines: set[str] = set()
    source_fingerprints: dict[str, tuple[str, bytes]] = {}
    allowed_job_numbers = job_numbers_for_contract(details.account)
    misc_count = 0
    entertainment_count = 0
    total = Decimal("0")
    for index, item in enumerate(items, 1):
        prefix = f"Receipt {index}"
        if not item.receipt_id or item.receipt_id in seen_lines:
            problems.append(f"{prefix}: remove the duplicate reimbursement line")
        seen_lines.add(item.receipt_id)
        source_id = _receipt_source_id(item)
        fingerprint = (item.filename, hashlib.sha256(item.file_bytes).digest())
        if source_id in source_fingerprints:
            if source_fingerprints[source_id] != fingerprint:
                problems.append(
                    f"{prefix}: split lines must use the same uploaded receipt"
                )
        else:
            source_fingerprints[source_id] = fingerprint
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
        problems.extend(
            allocation_problems(
                item.allocation,
                prefix=prefix,
                allowed_job_numbers=allowed_job_numbers,
            )
        )
        if not item.file_bytes:
            problems.append(f"{prefix}: upload the receipt image or PDF again")

    seen_mileage: set[str] = set()
    for index, item in enumerate(mileage_items, 1):
        prefix = f"Mileage {index}"
        if not item.entry_id or item.entry_id in seen_mileage:
            problems.append(f"{prefix}: remove the duplicate mileage entry")
        seen_mileage.add(item.entry_id)
        if item.transaction_date is None:
            problems.append(f"{prefix}: enter the travel date")
        if not item.purpose.strip():
            problems.append(f"{prefix}: enter the business purpose")
        if not item.destination.strip():
            problems.append(f"{prefix}: enter the destination")
        if parse_mileage(item.miles) is None:
            problems.append(f"{prefix}: enter valid business miles")
        rate = irs_business_mileage_rate(item.transaction_date)
        if item.transaction_date is not None and rate is None:
            problems.append(
                f"{prefix}: the IRS business-mileage rate for "
                f"{item.transaction_date:%Y-%m-%d} is not configured"
            )
        reimbursement = mileage_reimbursement(item)
        if reimbursement is not None:
            total += reimbursement
        problems.extend(
            allocation_problems(
                item.allocation,
                prefix=prefix,
                allowed_job_numbers=allowed_job_numbers,
            )
        )

    if len(mileage_items) > MAX_MILEAGE_ITEMS:
        problems.append(
            f"split the report: the official form allows {MAX_MILEAGE_ITEMS} "
            "mileage entries"
        )
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
    """Return the reviewed receipt total; invalid values contribute zero."""
    return sum(
        (parse_expense_amount(item.amount) or Decimal("0") for item in items),
        Decimal("0"),
    )


def total_reimbursement(
    items: Sequence[ExpenseItem],
    mileage_items: Sequence[MileageItem] = (),
) -> Decimal:
    """Return the receipt plus mileage reimbursement total."""
    receipt_total = expense_report_total(list(items))
    mileage_total = sum(
        (mileage_reimbursement(item) or Decimal("0") for item in mileage_items),
        Decimal("0"),
    )
    return receipt_total + mileage_total


def expense_report_warnings(
    details: ExpenseReportDetails,
    items: list[ExpenseItem],
    mileage_items: Sequence[MileageItem] = (),
) -> list[str]:
    """Return non-blocking checks that require human confirmation."""
    warnings: list[str] = []
    possible_duplicates: dict[
        tuple[date, Decimal, str], list[tuple[str, int]]
    ] = {}
    source_numbers: dict[str, int] = {}
    date_checked: set[str] = set()
    for item in items:
        source_id = _receipt_source_id(item)
        source_number = source_numbers.setdefault(source_id, len(source_numbers) + 1)
        if item.transaction_date and source_id not in date_checked:
            if item.transaction_date > details.report_date:
                warnings.append(
                    f"Receipt {source_number} is dated after the report date"
                )
            elif (details.report_date - item.transaction_date).days > 366:
                warnings.append(
                    f"Receipt {source_number} is more than one year older than the report date"
                )
            date_checked.add(source_id)
        amount = parse_expense_amount(item.amount)
        merchant = re.sub(
            r"[^a-z0-9]+", "", item.merchant_name.casefold()
        )
        if item.transaction_date and amount is not None and merchant:
            key = (item.transaction_date, amount, merchant)
            possible_duplicates.setdefault(key, []).append(
                (source_id, source_number)
            )
    for matches in possible_duplicates.values():
        distinct_sources = dict(matches)
        if len(distinct_sources) > 1:
            labels = ", ".join(
                str(number) for number in distinct_sources.values()
            )
            warnings.append(
                f"Receipts {labels} have the same merchant, date, and amount; "
                "confirm they are separate purchases"
            )
    for index, item in enumerate(mileage_items, 1):
        if item.transaction_date and item.transaction_date > details.report_date:
            warnings.append(f"Mileage {index} is dated after the report date")
    return _deduplicate(warnings)


def expense_report_signature(
    details: ExpenseReportDetails,
    items: list[ExpenseItem],
    mileage_items: Sequence[MileageItem] = (),
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
                    item.source_receipt_id,
                )
            ).encode("utf-8")
        )
        digest.update(hashlib.sha256(item.file_bytes).digest())
    for item in mileage_items:
        digest.update(repr(item).encode("utf-8"))
    return digest.hexdigest()


def build_expense_workbook(
    details: ExpenseReportDetails,
    items: list[ExpenseItem],
    *,
    mileage_items: Sequence[MileageItem] = (),
    template_path: Path = EXPENSE_TEMPLATE_PATH,
) -> bytes:
    """Fill the official workbook and append printable receipt images."""
    problems = validate_expense_report(details, items, mileage_items)
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
    image_buffers: list[BytesIO] = []
    _fill_report_header(form, details, mileage_items, image_buffers)

    ordered_mileage = _mileage_grouped_for_form(mileage_items)
    for row, item in zip(MILEAGE_ROWS, ordered_mileage):
        _fill_mileage_row(form, row, item)

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
    form["H18"] = "=SUM(H10:H17)"
    form["H39"] = "=SUM(H24:H38)"
    form["H59"] = "=SUM(H45:H58)"
    form["Q60"] = "=H18+H39+H59"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"

    if "RECEIPTS" in workbook.sheetnames:
        workbook.remove(workbook["RECEIPTS"])
    if ordered_items:
        receipt_sheet = workbook.create_sheet("RECEIPTS")
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
    mileage_items: Sequence[MileageItem] = (),
    include_pdf: bool = True,
) -> ExpensePackage:
    """Generate the workbook and, when available, its combined PDF packet."""
    workbook_bytes = build_expense_workbook(
        details,
        items,
        mileage_items=mileage_items,
    )
    pdf_bytes = None
    pdf_error = ""
    if include_pdf:
        try:
            pdf_bytes = convert_expense_workbook_to_pdf(workbook_bytes)
        except Exception as exc:  # noqa: BLE001 - see below; this must not re-raise
            # Preserve the editable workbook so a renderer outage never forces
            # re-entry, but the UI withholds the approval draft because RRH's
            # approved email submission artifact is the PDF.
            #
            # This deliberately catches Exception rather than ExpenseReportError.
            # The workbook above is already built and validated; the ONLY thing
            # that can fail here is the renderer, and every renderer failure must
            # degrade to "Excel ready, PDF unavailable" rather than discarding
            # work the operator already typed. ExpenseReportError alone was not
            # sufficient: subprocess.run(..., timeout=120) raises
            # subprocess.TimeoutExpired (a receipt-heavy workbook is exactly the
            # case that exceeds the budget), and the Gotenberg backend can raise
            # requests.ConnectionError before any wrapping runs. Both escaped,
            # the caller's generic handler dropped the package, and the
            # Excel-only fallback this block exists to enable became unreachable.
            pdf_error = str(exc) or exc.__class__.__name__
    basename = expense_report_basename(details)
    return ExpensePackage(
        basename=basename,
        workbook_bytes=workbook_bytes,
        pdf_bytes=pdf_bytes,
        total=total_reimbursement(items, mileage_items),
        receipt_count=_unique_receipt_count(items),
        pdf_error=pdf_error,
        mileage_count=len(mileage_items),
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
    """Return the submission PDF; Excel remains a separate editable download."""
    if not package.pdf_bytes:
        return []
    return [(f"{package.basename}.pdf", package.pdf_bytes)]


def email_attachment_size_warning(package: ExpensePackage) -> str:
    """Warn when the submission PDF may exceed a common mail-server limit."""
    if not package.pdf_bytes:
        return ""
    size = len(package.pdf_bytes)
    if size <= _EMAIL_SAFE_RAW_ATTACHMENT_BYTES:
        return ""
    return (
        f"The PDF attachment is {size / (1024 * 1024):.1f} MB before email "
        "encoding. Outlook or the mail server may require a smaller report."
    )


def receipt_preview_bytes(file_bytes: bytes, filename: str) -> bytes:
    """Return a bounded JPEG preview of the first receipt page/frame."""
    pages = receipt_attachment_pages(file_bytes, filename, render_limit=1)
    if not pages:
        raise ExpenseReportError("The receipt did not contain a readable page.")
    return pages[0]


def receipt_attachment_pages(
    file_bytes: bytes,
    filename: str,
    *,
    max_pages: int = _MAX_RECEIPT_PAGES_PER_FILE,
    render_limit: int | None = None,
) -> list[bytes]:
    """Validate and normalize receipt pages to compact, print-readable JPEGs.

    ``max_pages`` is the security/business limit for the source. ``render_limit``
    only limits returned pages, allowing a first-page preview without weakening
    validation of a multipage source.
    """
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
                for page_number, page in enumerate(document, 1):
                    width = ceil(page.rect.width * 150 / 72)
                    height = ceil(page.rect.height * 150 / 72)
                    _validate_receipt_dimensions(
                        width,
                        height,
                        label=f"{filename} page {page_number}",
                    )
                    if render_limit is not None and len(pages) >= render_limit:
                        continue
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
            for frame_index in range(frame_count):
                image.seek(frame_index)
                _validate_receipt_dimensions(
                    image.width,
                    image.height,
                    label=filename,
                )
                if render_limit is None or len(pages) < render_limit:
                    pages.append(_compact_receipt_image(image.copy()))
        if not pages:
            raise ExpenseReportError(f"{filename} does not contain a receipt image.")
        return pages
    except ExpenseReportError:
        raise
    except Exception as exc:
        raise ExpenseReportError(f"{filename} is not a readable receipt image.") from exc


def _compact_receipt_image(source: Image.Image) -> bytes:
    _validate_receipt_dimensions(source.width, source.height)
    image = ImageOps.exif_transpose(source)
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        background = Image.new("RGB", image.size, "white")
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        background.paste(image.convert("RGB"), mask=alpha)
        image = background
    else:
        image = image.convert("RGB")
    if (
        image.width > _ATTACHMENT_MAX_SIZE[0]
        or image.height > _ATTACHMENT_MAX_SIZE[1]
    ):
        image = ImageOps.contain(image, _ATTACHMENT_MAX_SIZE)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=78, optimize=True, progressive=True)
    return buffer.getvalue()


def _validate_receipt_dimensions(
    width: int,
    height: int,
    *,
    label: str = "Receipt image",
) -> None:
    """Reject invalid or decompression-heavy pages before raster allocation."""
    if width <= 0 or height <= 0:
        raise ExpenseReportError(f"{label} has invalid dimensions.")
    if width * height > _MAX_RECEIPT_PIXELS:
        raise ExpenseReportError(
            f"{label} is too large ({width}×{height}); use a smaller image or PDF page."
        )


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


def _fill_report_header(
    sheet,
    details: ExpenseReportDetails,
    mileage_items: Sequence[MileageItem],
    image_buffers: list[BytesIO],
) -> None:
    sheet["B2"] = f"REIMBURSEMENT OF EXPENSES - 01.01.{details.report_date:%Y}"
    _write_excel_text(sheet["C5"], details.employee_name)
    _write_excel_text(sheet["G5"], details.employee_number)
    _write_excel_text(sheet["K5"], details.employee_home_bu)
    sheet["P5"] = details.report_date
    sheet["P5"].number_format = "m/d/yyyy"

    rates = {
        rate
        for item in mileage_items
        if (rate := irs_business_mileage_rate(item.transaction_date)) is not None
    }
    default_rate = irs_business_mileage_rate(details.report_date)
    if len(rates) == 1:
        displayed_rate = next(iter(rates))
        sheet["B6"] = f"GAS MILEAGE @ ${displayed_rate} PER MILE"
    elif len(rates) > 1:
        sheet["B6"] = "GAS MILEAGE @ APPLICABLE IRS RATE"
    elif default_rate is not None:
        sheet["B6"] = f"GAS MILEAGE @ ${default_rate} PER MILE"
    else:
        sheet["B6"] = "GAS MILEAGE @ IRS BUSINESS RATE"
    formula_rate = default_rate or Decimal("0")
    for row in MILEAGE_ROWS:
        sheet.cell(row=row, column=7, value=0)
        sheet.cell(
            row=row,
            column=8,
            value=f"=ROUND(G{row}*{formula_rate},2)",
        ).number_format = '"$"#,##0.00'

    sheet["B62"] = "x" if details.mail_destination == "home" else ""
    sheet["B64"] = "x" if details.mail_destination == "satellite" else ""
    if details.mail_destination == "satellite":
        _write_excel_text(sheet["F64"], details.satellite_office)

    signature_buffer = BytesIO(employee_signature_png(details.employee_name))
    image_buffers.append(signature_buffer)
    signature_image = ExcelImage(signature_buffer)
    signature_image.width = 170
    signature_image.height = 30
    sheet.add_image(signature_image, "C66")
    sheet["D66"] = (
        f"Date: {details.report_date.month}/{details.report_date.day}/"
        f"{details.report_date.year % 100:02d}"
    )
    sheet["D66"].font = Font(name="Arial", size=8)
    sheet["D66"].alignment = Alignment(shrinkToFit=True)
    sheet["E66"] = ""
    _write_excel_text(sheet["C68"], details.employee_name)
    sheet["C68"].font = Font(name="Arial", size=12)
    sheet["C68"].alignment = Alignment(shrinkToFit=True)


def employee_signature_png(employee_name: str) -> bytes:
    """Render a deterministic cursive employee-name signature preview.

    The font is shrunk to fit the canvas rather than left at a fixed size and
    clipped. This is a correctness property, not an aesthetic one: the rendered
    image is embedded at C66 of the official JDE reimbursement form that goes to
    the approver, and the employee attests to it via "I confirm this generated
    signature represents me". A fixed 112pt size drew any long name straight
    past the 1600px canvas edge, and the subsequent crop clamp silently returned
    a cut-off signature — so the employee could attest to a truncated version of
    their own name on a financial document.
    """
    name = " ".join(str(employee_name or "").split())
    if not name or len(name) > _SIGNATURE_MAX_NAME_CHARS:
        raise ExpenseReportError("Enter a valid employee name for the signature.")
    font_path = next(
        (candidate for candidate in _SIGNATURE_FONT_CANDIDATES if candidate.is_file()),
        None,
    )
    if font_path is None:
        raise ExpenseReportError(
            "The cursive signature font is unavailable in this deployment."
        )

    canvas = Image.new("RGBA", _SIGNATURE_CANVAS, (255, 255, 255, 0))
    drawing = ImageDraw.Draw(canvas)
    max_width = _SIGNATURE_CANVAS[0] - _SIGNATURE_MARGIN[0] * 2
    max_height = _SIGNATURE_CANVAS[1] - _SIGNATURE_MARGIN[1] * 2

    size = _SIGNATURE_MAX_FONT_SIZE
    while True:
        font = ImageFont.truetype(str(font_path), size)
        box = drawing.textbbox((0, 0), name, font=font)
        width = max(1, box[2] - box[0])
        height = max(1, box[3] - box[1])
        if size <= _SIGNATURE_MIN_FONT_SIZE or (
            width <= max_width and height <= max_height
        ):
            break
        # Step toward a proportional fit, but always shrink by at least 1pt so a
        # pathological metric can never stall this loop.
        scale = min(max_width / width, max_height / height)
        size = max(_SIGNATURE_MIN_FONT_SIZE, min(size - 1, int(size * scale)))

    if width > max_width or height > max_height:
        # Reached the legibility floor and it still does not fit. Refuse rather
        # than emit a clipped signature: a visible error the employee can act on
        # is always better than a financial document carrying a silently
        # truncated attestation of their name.
        raise ExpenseReportError(
            "That name is too long to render as a signature. Use a shorter form "
            "of the name (for example, a middle initial instead of full middle "
            "names)."
        )

    drawing.text(
        (_SIGNATURE_MARGIN[0] - box[0], _SIGNATURE_MARGIN[1] - box[1]),
        name,
        font=font,
        fill=(0, 0, 0, 255),
    )
    cropped = canvas.crop(
        (
            0,
            0,
            min(_SIGNATURE_CANVAS[0] - 1, width + _SIGNATURE_MARGIN[0] * 2),
            min(_SIGNATURE_CANVAS[1] - 1, height + _SIGNATURE_MARGIN[1] * 2),
        )
    )
    if cropped.width > 1100:
        cropped = ImageOps.contain(cropped, (1100, 190))
    payload = BytesIO()
    cropped.save(payload, format="PNG")
    return payload.getvalue()


def _mileage_grouped_for_form(
    items: Sequence[MileageItem],
) -> list[MileageItem]:
    """Group mileage rows by coding, then date, for an auditable form."""
    return sorted(
        items,
        key=lambda item: (
            item.allocation.job_number,
            item.allocation.account_cost_type,
            item.allocation.cost_code_or_wo_type,
            item.transaction_date or date.max,
            item.entry_id,
        ),
    )


def _fill_mileage_row(sheet, row: int, item: MileageItem) -> None:
    miles = parse_mileage(item.miles)
    rate = irs_business_mileage_rate(item.transaction_date)
    assert item.transaction_date is not None and miles is not None and rate is not None
    sheet.cell(row=row, column=2, value=item.transaction_date).number_format = "m/d/yyyy"
    _write_excel_text(sheet.cell(row=row, column=3), item.purpose)
    _write_excel_text(sheet.cell(row=row, column=6), item.destination)
    sheet.cell(row=row, column=7, value=float(miles)).number_format = "0.00"
    sheet.cell(
        row=row,
        column=8,
        value=f"=ROUND(G{row}*{rate},2)",
    ).number_format = '"$"#,##0.00'
    _fill_allocation(sheet, row, item.allocation)


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
    sheet.cell(row=row, column=2, value=item.transaction_date).number_format = "m/d/yyyy"
    _write_excel_text(sheet.cell(row=row, column=3), item.description)
    if entertainment:
        _write_excel_text(sheet.cell(row=row, column=6), item.contact_name)
    sheet.cell(row=row, column=8, value=float(amount)).number_format = '"$"#,##0.00'
    _fill_allocation(sheet, row, item.allocation)


def _fill_allocation(sheet, row: int, allocation: ExpenseAllocation) -> None:
    if allocation.kind != ALLOCATION_JOB:
        raise ExpenseReportError(
            "Expense reports use job coding only; Work Order and Other Expenses "
            "columns must remain blank."
        )
    job_identifier = job_number_identifier(allocation.job_number)
    if not job_identifier:
        raise ExpenseReportError("The selected job number has no usable identifier.")
    _write_code(sheet, row, 9, job_identifier)
    _write_code(sheet, row, 10, allocation.account_cost_type)
    _write_code(sheet, row, 11, allocation.cost_code_or_wo_type)


def _write_code(sheet, row: int, column: int, value: str) -> None:
    cell = sheet.cell(row=row, column=column)
    _write_excel_text(cell, value)
    cell.number_format = "@"


def _write_excel_text(cell, value: object) -> None:
    """Write an explicit string so user text can never become an Excel formula."""
    cell.value = str(value or "").strip()
    cell.data_type = "s"


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

    receipt_groups = _receipt_groups(items)
    block_index = 0
    for receipt_number, group in enumerate(receipt_groups, 1):
        item = group[0]
        pages = receipt_attachment_pages(item.file_bytes, item.filename)
        for page_number, image_bytes in enumerate(pages, 1):
            start = block_index * _RECEIPT_PAGE_ROWS + 1
            end = start + _RECEIPT_PAGE_ROWS - 1
            sheet.merge_cells(start_row=start, start_column=1, end_row=start, end_column=12)
            sheet.cell(start, 1).value = (
                f"Receipt {receipt_number} of {len(receipt_groups)}"
                + (
                    f" · {len(group)} reimbursement lines"
                    if len(group) > 1
                    else ""
                )
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
            amount = sum(
                (parse_expense_amount(line.amount) or Decimal("0") for line in group),
                Decimal("0"),
            )
            detail = " · ".join(
                part
                for part in (
                    item.transaction_date.strftime("%m/%d/%Y") if item.transaction_date else "",
                    item.merchant_name.strip(),
                    f"${amount:,.2f} reimbursable",
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


def _receipt_source_id(item: ExpenseItem) -> str:
    """Return the uploaded-receipt identity shared by split lines."""
    return str(item.source_receipt_id or item.receipt_id or "").strip()


def _receipt_groups(items: Sequence[ExpenseItem]) -> list[list[ExpenseItem]]:
    """Group reimbursement lines by source receipt, preserving first use order."""
    grouped: dict[str, list[ExpenseItem]] = {}
    for item in items:
        grouped.setdefault(_receipt_source_id(item), []).append(item)
    return list(grouped.values())


def _unique_receipt_count(items: Sequence[ExpenseItem]) -> int:
    return len({_receipt_source_id(item) for item in items})


def _looks_like_email(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text)
        and len(text) <= 254
    )


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
