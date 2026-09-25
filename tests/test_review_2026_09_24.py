"""Adversarial money, OCR and operator-recovery regressions from code review."""

from concurrent.futures import Future
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from dotenv import dotenv_values
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import expense_ui, ocr, web_ui
from app.po_context import build_po_context
from app.po_rules import MATERIALS_PURCHASE, classify_po, parse_amount
from app.receipt_analyzer import ReceiptAnalysis, ReceiptLineItem
from test_po_context import _state

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "raw", ["123,45", "1,23,4.50", "1,,000", "12,", ",123", "1$2", "$$12"]
)
def test_po_money_rejects_ambiguous_grouping_and_symbols(raw):
    assert parse_amount(raw) is None
    with pytest.raises(ValueError):
        classify_po(MATERIALS_PURCHASE, raw)


@pytest.mark.parametrize(
    ("raw", "amount"),
    [
        ("$1,234.50", "1234.50"),
        ("USD 1,234.50", "1234.50"),
        ("1,234.50 USD", "1234.50"),
        ("-$1,234.50", "-1234.50"),
        ("$-1.00", "-1.00"),
        (".50", ".50"),
        (0, "0"),
    ],
)
def test_po_money_preserves_unambiguous_currency_forms(raw, amount):
    assert parse_amount(raw) == Decimal(amount)


@pytest.mark.parametrize("key", ["sub", "tax"])
@pytest.mark.parametrize("amount", ["not money", "12,34", "-5.00"])
def test_invalid_optional_price_cannot_bypass_context_validation(key, amount):
    state = _state(route=MATERIALS_PURCHASE)
    state[f"{key}_{state['analysis_token']}"] = amount
    context = build_po_context(state)
    assert not context.ready
    label = "subtotal" if key == "sub" else "sales tax"
    assert any(label in message.lower() for message in context.warnings)


def _picture():
    out = BytesIO()
    Image.new("RGB", (80, 160), "white").save(out, format="PNG")
    return out.getvalue()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_tiled_scan_under_native_heading_is_not_silently_omitted(monkeypatch, rotation):
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=300)
        page.insert_text((10, 20), "Vendor quote heading and page number")
        page.insert_image(fitz.Rect(0, 30, 100, 300), stream=_picture())
        page.insert_image(fitz.Rect(100, 30, 200, 300), stream=_picture())
        page.set_rotation(rotation)
        payload = pdf.tobytes()
    calls = []

    def read(data, **_):
        calls.append(data)
        return "Complete scanned scope and final price"

    monkeypatch.setattr(ocr, "_ocr_pdf", read)
    assert "Complete scanned scope" in ocr.extract_text_from_pdf(payload)
    assert len(calls) == 1


def test_repeated_overlapping_logos_do_not_count_as_a_full_page_scan(monkeypatch):
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=300)
        page.insert_text(
            (10, 20), "Complete native quote, with repeated decorative logos"
        )
        for _ in range(4):
            page.insert_image(fitz.Rect(0, 100, 100, 200), stream=_picture())
        payload = pdf.tobytes()
    monkeypatch.setattr(
        ocr, "_ocr_pdf", lambda *_a, **_k: pytest.fail("Logo sent to OCR")
    )
    assert "Complete native quote" in ocr.extract_text_from_pdf(payload)


def test_known_oversized_native_text_is_rejected_before_ocr(monkeypatch):
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=300)
        page.insert_image(page.rect, stream=_picture())
        pdf.new_page().insert_text((20, 30), "NATIVE_QUOTE " * 6)
        payload = pdf.tobytes()
    monkeypatch.setattr(ocr, "_MAX_EXTRACTED_CHARS", 30)
    calls = []
    monkeypatch.setattr(ocr, "_ocr_pdf", lambda *_a, **_k: calls.append(True) or "scan")
    with pytest.raises(ValueError, match="characters of text"):
        ocr.extract_text_from_pdf(payload)
    assert calls == [], "A known invalid document should cost no OCR requests"


def test_native_pdf_text_is_decoded_once_per_page(monkeypatch):
    with fitz.open() as pdf:
        for i in range(4):
            pdf.new_page().insert_text((20, 30), f"Complete native quote page {i}")
        payload = pdf.tobytes()
    calls = []
    real = fitz.Page.get_text

    def text(page, *args, **kwargs):
        calls.append(page.number)
        return real(page, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_text", text)
    assert "quote page 3" in ocr.extract_text_from_pdf(payload)
    assert calls == [0, 1, 2, 3]


def test_ocr_stops_before_later_requests_when_combined_text_exceeds_budget(monkeypatch):
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=300)
        page.insert_image(page.rect, stream=_picture())
        pdf.new_page().insert_text((20, 30), "Complete native quote content")
        page = pdf.new_page(width=200, height=300)
        page.insert_image(page.rect, stream=_picture())
        payload = pdf.tobytes()
    monkeypatch.setattr(ocr, "_MAX_EXTRACTED_CHARS", 35)
    calls = []
    monkeypatch.setattr(
        ocr, "_ocr_pdf", lambda *_a, **_k: calls.append(True) or "Scanned text"
    )
    with pytest.raises(ValueError, match="characters of text"):
        ocr.extract_text_from_pdf(payload)
    assert calls == [True]


@pytest.fixture
def configured(monkeypatch, tmp_path):
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(expense_ui, "prepare_receipt_content", lambda *_: [])


def _field(app, label):
    return next(w for w in app.text_input if w.label == label)


def test_price_errors_are_correctable_before_render_and_survive_switches(
    configured, monkeypatch
):
    renders = []
    monkeypatch.setattr(
        web_ui,
        "build_msapo_pdf",
        lambda **kw: renders.append(kw) or b"%PDF-1.7\nsynthetic",
    )
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.button[0].click().run()
    _field(app, "Your name (Requester / Asset Manager) *").set_value(
        "Synthetic Reviewer"
    ).run()
    _field(app, "PO/CO amount — final total including every fee and tax *").set_value(
        "108.00"
    ).run()

    def generate():
        return next(
            w
            for w in app.button
            if w.label == "Generate both files and Smartsheet link"
        )

    assert generate().disabled, "Do not render a PDF for a known pricing blocker"
    _field(app, "Subtotal after discounts (optional)").set_value("100.00").run()
    _field(app, "Sales tax (optional)").set_value("8.00").run()
    assert not generate().disabled
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.segmented_control[0].set_value("Purchase order").run()
    assert _field(app, "Subtotal after discounts (optional)").value == "100.00"
    assert _field(app, "Sales tax (optional)").value == "8.00"
    generate().click().run()
    assert not app.exception
    assert len(renders) == 1
    assert len(app.get("download_button")) == 2


@pytest.mark.parametrize("currency", ["CAD", "EUR"])
@pytest.mark.parametrize("pending", [False, True])
def test_foreign_receipt_requires_manual_usd_amount(
    configured, monkeypatch, currency, pending
):
    future = Future()
    reading = ReceiptAnalysis(
        merchant_name="Synthetic merchant",
        currency=currency,
        transaction_date=date(2026, 9, 1),
        total_amount="100.00",
        tax_amount="10.00",
        line_items=(
            ReceiptLineItem("Business item", "40.00"),
            ReceiptLineItem("Second item", "50.00"),
        ),
    )
    if not pending:
        future.set_result(reading)
    monkeypatch.setattr(expense_ui, "start_receipt", lambda *_: future)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload("receipt.png", _picture(), "image/png").run()
    if pending:
        future.set_result(reading)
        app.run()
    assert not app.exception
    assert _field(app, "Reimbursable amount *").value == ""
    assert not any(str(w.key).startswith("expense_item_") for w in app.checkbox)
    assert any(f"{currency} 10.00" in c.value for c in app.caption)
    _field(app, "Reimbursable amount *").set_value("75.00").run()
    assert _field(app, "Reimbursable amount *").value == "75.00"


def test_late_foreign_reading_preserves_an_already_entered_usd_amount(
    configured, monkeypatch
):
    future = Future()
    monkeypatch.setattr(expense_ui, "start_receipt", lambda *_: future)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload("receipt.png", _picture(), "image/png").run()
    _field(app, "Reimbursable amount *").set_value("75.00").run()
    future.set_result(ReceiptAnalysis(currency="CAD", total_amount="100.00"))
    app.run()
    assert not app.exception
    assert _field(app, "Reimbursable amount *").value == "75.00"
    app.segmented_control[0].set_value("Purchase order").run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    assert _field(app, "Reimbursable amount *").value == "75.00"
