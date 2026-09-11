"""Behavioral regressions for draft durability, reading completeness and latency."""

from concurrent.futures import Future
from datetime import date
from io import BytesIO
from pathlib import Path
import hashlib
import sqlite3
import threading
import time

import anthropic
import httpx
import fitz
import pytest
from PIL import Image
from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

from app import (
    api_retry,
    expense_ui,
    memory,
    ocr,
    quote_analyzer,
    receipt_analyzer,
    receipt_jobs,
    web_ui,
)
from app.content_cache import ContentDigests
from app.receipt_analyzer import ReceiptAnalysis
from app.receipt_analyzer import ReceiptLineItem

ROOT = Path(__file__).resolve().parents[1]


def picture(color="white", *, format="PNG"):
    data = BytesIO()
    Image.new("RGB", (120, 220), color).save(data, format=format)
    return data.getvalue()


@pytest.fixture
def configured(monkeypatch, tmp_path):
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(expense_ui, "prepare_receipt_content", lambda *_: [])
    monkeypatch.setattr(
        expense_ui, "analyze_prepared_receipt", lambda _: ReceiptAnalysis()
    )

    def immediate(prepare, read):
        future = Future()
        future.set_result(read(prepare()))
        return future

    monkeypatch.setattr(expense_ui, "start_receipt", immediate)


def field(app, label):
    return next(w for w in app.text_input if w.label == label)


@pytest.mark.parametrize("source", ["sample", "paste", "upload"])
def test_complete_po_draft_survives_workflow_switch(configured, monkeypatch, source):
    calls = []

    def analyze(_):
        calls.append(True)
        return web_ui._build_test_analysis()

    monkeypatch.setattr(web_ui, "analyze_quote", analyze)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    if source == "sample":
        app.button[0].click().run()
    elif source == "paste":
        app.radio[0].set_value("Paste text").run()
        app.text_area[0].set_value("Synthetic vendor scope and price quote.").run()
    else:
        app.file_uploader[0].upload(
            "quote.txt", b"Synthetic vendor scope and price quote.", "text/plain"
        ).run()
    edits = {
        "Vendor name *": "Reviewed Vendor",
        "PO/CO amount — final total including every fee and tax *": "8765.43",
        "Vendor representative email *": "reviewed@example.invalid",
        "Short description (20 characters maximum) *": "Reviewed work",
    }
    for label, value in edits.items():
        field(app, label).set_value(value).run()
    next(w for w in app.text_area if w.label == "Scope of Work").set_value(
        "Reviewed custom scope"
    ).run()
    checkbox = next(w for w in app.checkbox if str(w.key).startswith("inc_"))
    key = checkbox.key
    checkbox.set_value(False).run()
    count = len(calls)
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.segmented_control[0].set_value("Purchase order").run()
    assert not app.exception
    for label, value in edits.items():
        assert field(app, label).value == value
    assert (
        next(w for w in app.text_area if w.label == "Scope of Work").value
        == "Reviewed custom scope"
    )
    assert app.session_state[key] is False
    assert len(calls) == count
    if source == "upload":
        next(w for w in app.button if w.label == "Remove retained quote").click().run()
        assert "analysis" not in app.session_state.filtered_state
        app.run()
        assert "analysis" not in app.session_state.filtered_state


def test_po_refresh_reuses_pdf_but_scope_edit_rebuilds(configured, monkeypatch):
    rendered = []

    def render(**kwargs):
        rendered.append(kwargs)
        return b"%PDF-1.7 synthetic"

    monkeypatch.setattr(web_ui, "build_msapo_pdf", render)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.button[0].click().run()
    field(app, "Your name (Requester / Asset Manager) *").set_value(
        "Synthetic Reviewer"
    ).run()

    def generate():
        next(
            w
            for w in app.button
            if w.label == "Generate both files and Smartsheet link"
        ).click().run()
        assert not app.exception

    generate()
    field(app, "Your name (Requester / Asset Manager) *").set_value(
        "Another Reviewer"
    ).run()
    generate()
    assert len(rendered) == 1
    next(w for w in app.text_area if w.label == "Scope of Work").set_value(
        "Different scope"
    ).run()
    generate()
    assert len(rendered) == 2


def test_blank_mileage_date_can_be_corrected(configured):
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    next(w for w in app.toggle if "Include reimbursable" in w.label).set_value(
        True
    ).run()
    next(w for w in app.date_input if w.label == "Travel date *").set_value(None).run()
    assert not app.exception
    assert any("Enter the travel date" in w.value for w in app.error)
    next(w for w in app.date_input if w.label == "Travel date *").set_value(
        date(2026, 8, 1)
    ).run()
    assert not app.exception


def test_over_budget_receipt_can_be_removed_without_losing_edits(
    configured, monkeypatch
):
    first, second = picture(), picture("black")
    monkeypatch.setattr(
        expense_ui, "_MAX_REPORT_UPLOAD_BYTES", len(first) + len(second) - 1
    )
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload("first.png", first, "image/png").run()
    field(app, "Merchant").set_value("Reviewed merchant").run()
    app.session_state["expense_receipt_files"] = [
        ("first.png", first, "image/png"),
        ("second.png", second, "image/png"),
    ]
    app.run()
    next(w for w in app.button if w.label.startswith("Remove second.png")).click().run()
    assert not app.exception
    assert field(app, "Merchant").value == "Reviewed merchant"
    assert len(app.session_state["expense_receipt_files"]) == 1


def test_mixed_pdf_ocr_preserves_page_order(monkeypatch):
    with fitz.open() as pdf:
        pdf.new_page().insert_text((30, 40), "Native cover with sufficient text.")
        p = pdf.new_page()
        p.insert_image(p.rect, stream=picture())
        pdf.new_page().insert_text((30, 40), "Native final page with sufficient text.")
        payload = pdf.tobytes()
    counts = []

    def read(data, **_):
        with fitz.open(stream=data, filetype="pdf") as part:
            counts.append(part.page_count)
        return "Scanned scope and total."

    monkeypatch.setattr(ocr, "_ocr_pdf_via_document", read)
    result = ocr.extract_text_from_pdf(payload)
    assert (
        result.index("Native cover")
        < result.index("Scanned scope")
        < result.index("Native final")
    )
    assert counts == [1]


def test_native_pdf_needs_no_api_call(monkeypatch):
    with fitz.open() as pdf:
        pdf.new_page().insert_text(
            (30, 40), "Complete native scope and price information."
        )
        payload = pdf.tobytes()
    monkeypatch.setattr(
        ocr,
        "_ocr_pdf_via_document",
        lambda *_a, **_k: pytest.fail("native PDF reached OCR"),
    )
    assert "Complete native" in ocr.extract_text_from_pdf(payload)


def test_blank_ocr_cannot_silently_omit_scanned_pages(monkeypatch):
    monkeypatch.setattr(ocr, "_ocr_pdf_via_document", lambda *_a, **_k: "")
    monkeypatch.setattr(ocr, "_ocr_pdf_via_page_images", lambda *_a, **_k: "")
    with pytest.raises(ValueError, match="Scanned quote pages could not be read"):
        ocr._ocr_pdf(b"synthetic", until=100)


def test_multipage_tiff_all_frames_reach_receipt_analysis(monkeypatch):
    data = BytesIO()
    Image.new("RGB", (40, 40), "red").save(
        data,
        format="TIFF",
        save_all=True,
        append_images=[Image.new("RGB", (40, 40), "blue")],
    )
    monkeypatch.setattr(receipt_analyzer, "ANTHROPIC_API_KEY", "synthetic")
    content = receipt_analyzer.prepare_receipt_content(data.getvalue(), "receipt.tiff")
    blocks = [b for b in content if b["type"] == "image"]
    assert len(blocks) == 2
    assert blocks[0]["source"]["data"] != blocks[1]["source"]["data"]


@pytest.mark.parametrize(
    "read", [receipt_analyzer._call_with_retry, quote_analyzer._call_api_with_retry]
)
def test_one_retry_owner_makes_three_http_attempts(monkeypatch, read):
    calls, sleeps = [], []

    def unavailable(request):
        calls.append(request)
        return httpx.Response(
            503,
            json={"error": {"type": "api_error", "message": "synthetic"}},
            request=request,
        )

    monkeypatch.setattr(api_retry.time, "sleep", sleeps.append)
    with anthropic.Anthropic(
        api_key="synthetic",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(unavailable)),
    ) as client:
        with pytest.raises(anthropic.APIStatusError):
            read(
                client, [] if read is receipt_analyzer._call_with_retry else "synthetic"
            )
    assert len(calls) == 3
    assert sleeps == [3, 6]
    assert all(
        req.extensions["timeout"]["read"] <= api_retry.REQUEST_TIMEOUT_SECONDS
        for req in calls
    )


def test_expired_operation_does_not_issue_request(monkeypatch):
    monkeypatch.setattr(api_retry.time, "monotonic", lambda: 100)
    with pytest.raises(TimeoutError):
        api_retry.request_with_retry(
            lambda _: pytest.fail("expired request issued"), until=99
        )


@pytest.mark.parametrize("value", ["invalid", "nan", "inf", "0", "601"])
def test_invalid_timeout_settings_use_bounded_default(monkeypatch, value):
    monkeypatch.setenv("EPC_TEST_TIMEOUT", value)
    assert api_retry._seconds_setting("EPC_TEST_TIMEOUT", 60, 10, 120) == 60


@pytest.mark.parametrize("kind", ["receipt", "quote"])
def test_analyzers_disable_sdk_retries_and_close_clients(monkeypatch, kind):
    from types import SimpleNamespace

    created, closed = [], []

    def client(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(close=lambda: closed.append(True))

    monkeypatch.setattr(anthropic, "Anthropic", client)
    if kind == "receipt":
        monkeypatch.setattr(
            receipt_analyzer, "_call_with_retry", lambda *_a, **_k: "{}"
        )
        receipt_analyzer.analyze_prepared_receipt([])
    else:
        monkeypatch.setattr(
            quote_analyzer, "_call_api_with_retry", lambda *_a, **_k: "{}"
        )
        quote_analyzer.analyze_quote("synthetic")
    assert created[0]["max_retries"] == 0
    assert created[0]["timeout"] == api_retry.REQUEST_TIMEOUT_SECONDS
    assert closed == [True]


def test_digest_cache_is_bounded_and_content_sensitive(monkeypatch):
    cache = ContentDigests(max_bytes=10, max_entries=2)
    payload = b"receipt"
    expected = hashlib.sha256(payload).digest()
    calls = []
    real = hashlib.sha256
    monkeypatch.setattr(hashlib, "sha256", lambda b: calls.append(b) or real(b))
    assert cache.digest(payload) == expected
    assert cache.digest(payload) == expected
    assert len(calls) == 1
    assert cache.digest(b"changed") != expected
    assert cache._size <= 10
    cache.retain([])
    assert not cache._entries


def test_database_initializes_once_and_rechecks_external_ddl(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    calls = []
    real = memory._migrate_expense_approver_identity
    monkeypatch.setattr(
        memory,
        "_migrate_expense_approver_identity",
        lambda conn: calls.append(True) or real(conn),
    )
    for _ in range(3):
        conn = memory._connect()
        assert conn is not None
        conn.close()
    assert len(calls) == 1
    with sqlite3.connect(tmp_path / "epc_memory.db") as conn:
        conn.execute("CREATE TABLE test_external_change (id INTEGER)")
    memory._connect().close()
    assert len(calls) == 2


def test_receipt_pool_is_bounded_and_preparation_stays_on_caller():
    release = threading.Event()
    caller = threading.get_ident()
    prepared = []

    def prepare():
        prepared.append(threading.get_ident())
        return "prepared"

    def read(value):
        assert threading.get_ident() != caller
        assert release.wait(timeout=5)
        return value

    futures = []
    try:
        futures = [receipt_jobs.start_receipt(prepare, read) for _ in range(2)]
        assert all(f is not None for f in futures)
        assert receipt_jobs.start_receipt(prepare, read) is None
        assert prepared == [caller, caller]
    finally:
        release.set()
        for future in futures:
            if future:
                assert future.result(timeout=5) == "prepared"


def test_late_background_results_cannot_restore_removed_receipts(monkeypatch):
    future = Future()
    future.set_result(ReceiptAnalysis(merchant_name="Removed merchant"))
    state = {"expense_analysis_jobs": {"gone": (future, 0)}}
    monkeypatch.setattr(expense_ui.st, "session_state", state)
    expense_ui._advance_receipt_jobs([])
    assert "expense_receipt_analysis_gone" not in state
    assert not state["expense_analysis_jobs"]


def test_pending_receipt_keeps_form_editable_and_preserves_manual_values(
    configured, monkeypatch
):
    future = Future()
    monkeypatch.setattr(expense_ui, "start_receipt", lambda *_: future)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload("receipt.png", picture(), "image/png").run()
    assert not app.exception
    assert any("remaining receipt" in w.value for w in app.caption)
    field(app, "Merchant").set_value("Reviewed merchant").run()
    field(app, "Reimbursable amount *").set_value("29.00").run()
    field(app, "Description / business purpose *").set_value("Reviewed purpose").run()
    future.set_result(
        ReceiptAnalysis(
            merchant_name="Automatic merchant",
            total_amount="22.00",
            suggested_description="Automatic purpose",
            transaction_date=date(2026, 8, 1),
            line_items=(
                ReceiptLineItem("One", "10.00"),
                ReceiptLineItem("Two", "12.00"),
            ),
        )
    )
    app.run()
    assert not app.exception
    assert field(app, "Merchant").value == "Reviewed merchant"
    assert field(app, "Reimbursable amount *").value == "29.00"
    assert field(app, "Description / business purpose *").value == "Reviewed purpose"
    assert next(
        w for w in app.date_input if w.label == "Transaction date *"
    ).value == date(2026, 8, 1)
    # The report-date control is also clearable and must fail validation safely.
    next(w for w in app.date_input if w.label == "Report date *").set_value(None).run()
    assert not app.exception


def test_stopping_automatic_reading_cannot_publish_late_result(configured, monkeypatch):
    future = Future()
    future.set_running_or_notify_cancel()
    monkeypatch.setattr(expense_ui, "start_receipt", lambda *_: future)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload("receipt.png", picture(), "image/png").run()
    next(
        w for w in app.button if w.label.startswith("Stop automatic reading")
    ).click().run()
    future.set_result(ReceiptAnalysis(merchant_name="Late merchant"))
    app.run()
    assert not app.exception
    assert field(app, "Merchant").value == ""
    assert not app.session_state["expense_analysis_jobs"]


@pytest.mark.parametrize("kind", ["quote", "receipt", "ocr"])
@pytest.mark.parametrize("stop_reason", ["end_turn", "max_tokens", "refusal"])
def test_incomplete_model_output_is_never_published(monkeypatch, kind, stop_reason):
    calls = []
    real_client = anthropic.Anthropic

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "msg_synthetic",
                "type": "message",
                "role": "assistant",
                "model": "synthetic",
                # Valid text/JSON is not sufficient proof of a complete reply.
                "content": [{"type": "text", "text": "{}"}],
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    def client(**kwargs):
        kwargs["api_key"] = "synthetic"
        return real_client(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))
        )

    monkeypatch.setattr(anthropic, "Anthropic", client)

    def read():
        if kind == "quote":
            return quote_analyzer.analyze_quote("Synthetic complete quote")
        if kind == "receipt":
            return receipt_analyzer.analyze_prepared_receipt([])
        return ocr._ocr_pdf(b"synthetic", until=time.monotonic() + 120)

    if stop_reason == "end_turn":
        assert read() is not None
    else:
        with pytest.raises(RuntimeError, match="incomplete"):
            read()
    # An incomplete output is not repaired by a transport retry or re-encoding
    # the same PDF as images. Avoid paying for a second doomed request.
    assert len(calls) == 1


@pytest.mark.parametrize("arrival", ["ready", "pending", "pending_with_override"])
def test_receipt_section_suggestion_respects_explicit_choice(
    configured, monkeypatch, arrival
):
    future = Future()
    result = ReceiptAnalysis(
        merchant_name="Synthetic business meeting",
        expense_section_guess="entertainment",
    )
    if arrival == "ready":
        future.set_result(result)
    monkeypatch.setattr(expense_ui, "start_receipt", lambda *_: future)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload("receipt.png", picture(), "image/png").run()

    def section():
        return next(w for w in app.selectbox if w.label == "Expense section *")

    if arrival == "pending_with_override":
        section().set_value("entertainment").run()
        section().set_value("miscellaneous").run()
        app.segmented_control[0].set_value("Purchase order").run()
        app.segmented_control[0].set_value("Expense reimbursement").run()
    if arrival != "ready":
        future.set_result(result)
        app.run()
    assert not app.exception
    expected = "miscellaneous" if arrival == "pending_with_override" else "entertainment"
    assert section().value == expected
    assert any(w.label == "Entertainment contact name *" for w in app.text_input) == (
        expected == "entertainment"
    )
    app.run()
    assert section().value == expected
