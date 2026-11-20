"""U11: PO and expense status text stays actionable and free of internals."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

import app.expense_ui as expense_ui
import app.web_ui as web_ui
from app.expense_report import ExpensePackage
from app.receipt_analyzer import ReceiptAnalysis
from app.status_copy import safe_status_detail
from tests.test_web_ui_app import _configure_smartsheet


ROOT = Path(__file__).parents[1]
_FORBIDDEN = re.compile(
    r"(?<![a-zA-Z0-9])(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{40})(?![a-zA-Z0-9])"
    r"|\b(?:application|audio|image|message|multipart|text|video)/[a-zA-Z0-9.+_-]+"
    r"|\b(?:Traceback|[a-zA-Z_][a-zA-Z0-9_]*(?:Error|Exception))\b",
    flags=re.IGNORECASE,
)


def _assert_no_internal_status(app: AppTest) -> None:
    assert not app.exception
    messages = [
        str(element.value)
        for name in ("error", "warning", "info", "success", "toast", "caption")
        for element in getattr(app, name, ())
    ]
    assert not any(_FORBIDDEN.search(message) for message in messages), messages


def test_po_status_scan_through_generation_with_mocked_model(monkeypatch, tmp_path):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(web_ui, "analyze_quote", lambda *_args: None)
    monkeypatch.setattr(
        web_ui, "build_msapo_pdf", lambda **_kwargs: b"%PDF-1.7\nsynthetic"
    )
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    _assert_no_internal_status(app)
    app.button[0].click().run()  # Built-in synthetic quote needs no model call.
    _assert_no_internal_status(app)
    next(
        field for field in app.text_input
        if field.label == "Your name (Requester / Asset Manager) *"
    ).set_value("Synthetic Requester").run()
    _assert_no_internal_status(app)
    generate = next(
        button for button in app.button
        if button.label == "Generate both files and Smartsheet link"
    )
    assert not generate.disabled
    generate.click().run()
    _assert_no_internal_status(app)
    assert len(app.get("download_button")) == 2


def test_expense_status_scan_through_generation_with_mocked_receipt_model(
    monkeypatch, tmp_path
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(expense_ui, "prepare_receipt_content", lambda *_: [])
    monkeypatch.setattr(
        expense_ui,
        "analyze_prepared_receipt",
        lambda *_args: ReceiptAnalysis(
            merchant_name="Synthetic Parking",
            transaction_date=date(2026, 8, 10),
            total_amount="31.25",
            suggested_description="Business parking",
            review_notes=(
                "Check total. Traceback RuntimeError application/pdf "
                + "a" * 40 + " " + "b" * 64,
            ),
            confidence="medium",
        ),
    )
    monkeypatch.setattr(
        expense_ui, "build_expense_package",
        lambda _details, _items, **_kwargs: ExpensePackage(
            basename="synthetic-expense",
            workbook_bytes=b"synthetic-workbook",
            pdf_bytes=b"%PDF-synthetic",
            total=Decimal("31.25"),
            receipt_count=1,
        ),
    )
    photo = BytesIO()
    Image.new("RGB", (120, 220), "white").save(photo, format="JPEG")
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    _assert_no_internal_status(app)
    app.file_uploader[0].upload("synthetic.jpg", photo.getvalue(), "image/jpeg").run()
    _assert_no_internal_status(app)
    for label, value in (
        ("Employee name *", "Synthetic Employee"),
        ("Employee number *", "TEST-1001"),
        ("Your manager's name (Cc) *", "Synthetic Manager"),
        ("Your manager's email (Cc) *", "manager@example.invalid"),
    ):
        next(field for field in app.text_input if field.label == label).set_value(value).run()
        _assert_no_internal_status(app)
    next(
        box for box in app.checkbox
        if box.label.startswith("I confirm this generated")
    ).set_value(True).run()
    _assert_no_internal_status(app)
    generate = next(
        button for button in app.button
        if button.label == "Generate expense report and email draft"
    )
    assert not generate.disabled
    generate.click().run()
    _assert_no_internal_status(app)
    assert any(button.label == "Download combined PDF packet"
               for button in app.get("download_button"))


def test_external_status_details_do_not_display_internal_tokens():
    raw = "Traceback ValueError application/pdf " + "a" * 40 + " " + "b" * 64
    clean = safe_status_detail(raw)
    assert _FORBIDDEN.search(clean) is None
    assert "details omitted" in clean
