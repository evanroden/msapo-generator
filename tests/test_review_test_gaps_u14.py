"""Missing 2026-11 review contracts; only invented data and local state.

Existing native-file and Monthly size tests are inventoried in the U14 PR. These
checks cover byte identity, mixed receipt status, and an edited capacity cell.
"""

from concurrent.futures import Future
from dataclasses import replace
from datetime import date
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from openpyxl import load_workbook

from app import expense_ui, monthly_report_capacity as capacity
from app import monthly_report_directory as directory
from app.document_generator import build_msapo_pdf
from app.expense_report import (
    ALLOCATION_JOB,
    EXPENSE_SECTION_MISC,
    ExpenseAllocation,
    ExpenseItem,
    build_expense_package,
    total_reimbursement,
)
from app.monthly_report_model import Facility, ReportProfile
from app.quote_analyzer import QuoteAnalysis
from app.receipt_analyzer import ReceiptAnalysis
from tests.conftest import requires_libreoffice
from test_expense_report import _details, _item


def test_ten_distinct_mixed_receipts_have_one_mocked_read_status_and_exact_total(monkeypatch):
    """Ten reads of four formats must not collapse, borrow a status, or double count."""
    extensions = ("pdf", "png", "jpeg", "heic", "pdf", "png", "jpeg", "heic", "pdf", "png")
    files = [
        (f"synthetic-{index:02d}.{extension}", f"invented-{index}-{extension}".encode(),
         "image/heic" if extension == "heic" else "application/pdf" if extension == "pdf" else f"image/{extension}")
        for index, extension in enumerate(extensions, 1)
    ]
    session = {}
    monkeypatch.setattr(expense_ui.st, "session_state", session)
    monkeypatch.setattr(expense_ui, "_receipt_digest", lambda raw: sha256(raw).hexdigest())
    reads = []

    def prepare(payload, filename):
        reads.append((filename, payload))
        return filename, payload

    def analyze(prepared):
        filename, _ = prepared
        index = int(filename.split("-")[1].split(".")[0])
        return ReceiptAnalysis(
            merchant_name=f"Synthetic merchant {index}",
            transaction_date=date(2026, 11, 1),
            total_amount=f"{index}.25",
            suggested_description=f"Invented business item {index}",
            confidence="high" if index % 2 else "low",
        )

    def immediate(prepare_call, analyze_call):
        future = Future()
        try:
            future.set_result(analyze_call(prepare_call()))
        except Exception as exc:
            future.set_exception(exc)
        return future

    monkeypatch.setattr(expense_ui, "prepare_receipt_content", prepare)
    monkeypatch.setattr(expense_ui, "analyze_prepared_receipt", analyze)
    monkeypatch.setattr(expense_ui, "start_receipt", immediate)
    receipts, duplicates = expense_ui._unique_receipts(files)
    assert duplicates == [] and len(receipts) == 10
    assert len({receipt_id for receipt_id, _, _ in receipts}) == 10
    assert expense_ui._advance_receipt_jobs(receipts)
    assert reads == [(name, payload) for name, payload, _ in files]
    assert not session["expense_analysis_jobs"]
    assert not expense_ui._unread_receipts(receipts)

    items = []
    for index, (receipt_id, filename, payload) in enumerate(receipts, 1):
        key = f"expense_receipt_analysis_{receipt_id}"
        assert key in session and f"expense_receipt_error_{receipt_id}" not in session
        analysis = session[key]
        assert analysis.merchant_name == f"Synthetic merchant {index}"
        assert analysis.confidence == ("high" if index % 2 else "low")
        items.append(ExpenseItem(
            receipt_id=receipt_id, filename=filename, file_bytes=payload,
            transaction_date=analysis.transaction_date,
            description=analysis.suggested_description,
            amount=analysis.total_amount, section=EXPENSE_SECTION_MISC,
            allocation=ExpenseAllocation(kind=ALLOCATION_JOB, job_number="SYNTHETIC"),
        ))
    assert total_reimbursement(items) == Decimal("57.50")
    assert expense_ui._advance_receipt_jobs(receipts) is False
    assert len(reads) == 10


def test_receipt_native_upload_limit_is_exactly_fifteen_mib(monkeypatch, tmp_path):
    """The browser enforces the per-file bound before any mocked receipt read."""
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    assert expense_ui._MAX_RECEIPT_BYTES == 15 * 1024 * 1024
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "run_web.py").run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    assert not app.exception
    uploader, = app.get("file_uploader")
    assert uploader.proto.max_upload_size_mb == 15
    assert {"pdf", "png", "jpeg", "heic"}.issubset(set(expense_ui._RECEIPT_TYPES))


def test_report_only_capacity_cell_edit_is_not_a_reusable_site_correction(tmp_path, monkeypatch):
    """Only a second reviewed shared-data save can change the site inventory."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    site = Facility("synthetic-north", "Synthetic North", ("SN",))
    profile = ReportProfile("Synthetic Capacity Agreement", site.key, site.title, (site,))
    directory.save_directory(
        profile.contract, (directory.DirectorySite(site.key, site.title, site.aliases),),
        expected_revision=0, actor="Synthetic Reviewer", confirmed=True,
    )
    before = (b"Facility,Service,Required capacity,Available capacity,Units\n"
              b"SN,Steam,1200,1600,lb/hr\n")
    inspection = capacity.inspect_capacity(profile, "synthetic.csv", before)
    initial = capacity.save_capacity(
        profile, inspection.tables, expected_revision=0, actor="Synthetic Reviewer",
        reviewed_fingerprint=capacity.review_fingerprint(inspection.tables),
    )
    original = capacity.capacity_block(profile)
    assert original is not None and original.extra_tables
    table = original.extra_tables[0]
    original_row = table.rows[0]
    assert "1200" in original_row
    changed_row = tuple("1250" if cell == "1200" else cell for cell in original_row)
    report_only = replace(original, extra_tables=(replace(table, rows=(changed_row,)),))
    assert "1250" in report_only.extra_tables[0].rows[0]
    assert not capacity.can_refresh_capacity(profile, report_only)
    assert capacity.load_capacity(profile.contract) == initial
    assert capacity.capacity_block(profile).extra_tables[0].rows[0] == original_row

    # Correcting the reusable site inventory is an explicit separate review/save.
    correction = capacity.inspect_capacity(profile, "synthetic-correction.csv",
                                           before.replace(b"1200", b"1250"))
    revised = capacity.save_capacity(
        profile, correction.tables, expected_revision=initial.revision,
        actor="Synthetic Reviewer", reviewed_fingerprint=capacity.review_fingerprint(correction.tables),
    )
    assert revised.revision == initial.revision + 1
    assert "1250" in capacity.capacity_block(profile).extra_tables[0].rows[0]
    assert "1200" in capacity.load_capacity(profile.contract, initial.revision).tables[0].rows[0]


@requires_libreoffice
def test_generated_expense_outlook_draft_contains_the_exact_rendered_pdf_bytes():
    details = _details()
    package = build_expense_package(details, [_item("synthetic-native-check")])
    assert not package.pdf_error and package.pdf_bytes
    workbook = load_workbook(BytesIO(package.workbook_bytes), data_only=False)
    form = workbook["EXPENSE REIMBURSEMENT"]
    assert form["C5"].value == details.employee_name
    assert form["H24"].value == 31.25
    assert form["Q60"].value == "=H18+H39+H59"
    assert package.total == Decimal("31.25")
    with fitz.open(stream=package.pdf_bytes, filetype="pdf") as pdf:
        assert pdf.page_count == 2
        assert details.employee_name in pdf[0].get_text()
        assert "Receipt 1 of 1" in pdf[1].get_text()
    message = BytesParser(policy=policy.default).parsebytes(
        expense_ui._build_expense_eml(details, package)
    )
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    attachment, = attachments
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_filename() == f"{package.basename}.pdf"
    assert attachment.get_payload(decode=True) == package.pdf_bytes
    assert all(not part.get_filename().endswith(".xlsx") for part in attachments)


@requires_libreoffice
def test_po_package_original_and_reviewed_msapo_are_openable_without_quote_price_in_scope():
    with fitz.open() as quote:
        quote.new_page().insert_text((72, 72), "Synthetic estimate for valve repair")
        original_pdf = quote.tobytes()
    analysis = QuoteAnalysis(
        vendor_name="Synthetic Supplier", facility_name="Synthetic Facility",
        project_description="Valve repair", scope_of_work="Unreviewed estimate $9,999.00",
    )
    msapo_pdf = build_msapo_pdf(
        analysis=analysis, scope="Replace sample valve, test operation.",
        inclusions=["Synthetic labor and materials"], exclusions=["Unrelated work"],
        facility_display="Synthetic Facility", vendor_display="Synthetic Supplier",
    )
    for payload in (original_pdf, msapo_pdf):
        assert payload.startswith(b"%PDF-")
        with fitz.open(stream=payload, filetype="pdf") as document:
            assert document.page_count > 0
            assert not document.is_closed
    with fitz.open(stream=msapo_pdf, filetype="pdf") as form:
        text = "\n".join(page.get_text() for page in form)
    assert "MSAPO" in text and "Replace sample valve" in text
    assert "9,999" not in text and "Unreviewed estimate" not in text
