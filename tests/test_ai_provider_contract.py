"""Synthetic A06 provider-contract tests: never use a real endpoint or document."""

from __future__ import annotations

import base64
from io import BytesIO
import time
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from PIL import Image

from app import api_retry, monthly_report_ai, ocr, quote_analyzer, receipt_analyzer
from app.ai_provider import (
    AIProviderConfigurationError,
    anthropic_client,
    require_configured_provider,
)


def _never_contact_provider(**kwargs):
    raise AssertionError("An external client must not be constructed")


@pytest.mark.parametrize("mode", ["disabled", "azure-openai", "enterprise-gateway", "", "unknown"])
def test_unapproved_or_disabled_provider_never_constructs_client(monkeypatch, mode):
    monkeypatch.setenv("EPC_AI_PROVIDER", mode)
    with pytest.raises(AIProviderConfigurationError, match="disabled|approved adapter"):
        anthropic_client(factory=_never_contact_provider, api_key="synthetic-key")


def test_anthropic_sdk_base_override_fails_closed(monkeypatch):
    monkeypatch.setenv("EPC_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://unapproved.example.invalid")
    with pytest.raises(AIProviderConfigurationError, match="custom Anthropic base URL"):
        anthropic_client(factory=_never_contact_provider, api_key="synthetic-key")


def test_current_anthropic_adapter_keeps_sdk_retries_disabled(monkeypatch):
    monkeypatch.setenv("EPC_AI_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    seen = []

    def factory(**kwargs):
        seen.append(kwargs)
        return object()

    assert anthropic_client(factory=factory, api_key="synthetic", timeout=17)
    assert seen == [{"api_key": "synthetic", "max_retries": 0, "timeout": 17}]
    with pytest.raises(AIProviderConfigurationError, match="credentials"):
        anthropic_client(factory=_never_contact_provider, api_key="")


@pytest.mark.parametrize("mode", ["disabled", "not-reviewed"])
@pytest.mark.parametrize("operation", ["ocr", "po", "receipt", "monthly"])
def test_all_four_network_entrypoints_fail_before_creating_sdk_client(monkeypatch, mode, operation):
    monkeypatch.setenv("EPC_AI_PROVIDER", mode)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", _never_contact_provider)
    for module in (ocr, quote_analyzer, receipt_analyzer, monthly_report_ai):
        monkeypatch.setattr(module, "ANTHROPIC_API_KEY", "synthetic-key")
    content = [{"type": "text", "text": "synthetic"}]
    operations = {
        "ocr": lambda: ocr._ocr_request(content),
        "po": lambda: quote_analyzer.analyze_quote("Synthetic inspection scope"),
        "receipt": lambda: receipt_analyzer.analyze_prepared_receipt(content),
        "monthly": lambda: monthly_report_ai.request_json(content),
    }
    with pytest.raises(AIProviderConfigurationError):
        operations[operation]()


def _mock_transport(monkeypatch, responses):
    """Capture exact synthetic calls without constructing an HTTP client."""
    seen = []
    results = iter(responses)

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            self.messages = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def close(self):
            pass

        def create(self, **kwargs):
            seen.append(kwargs)
            result = next(results)
            if isinstance(result, BaseException):
                raise result
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=result)],
            )

    monkeypatch.setenv("EPC_AI_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", Client)
    for module in (ocr, quote_analyzer, receipt_analyzer, monthly_report_ai):
        monkeypatch.setattr(module, "ANTHROPIC_API_KEY", "synthetic-key")
    return seen


def _png():
    image = Image.new("RGB", (180, 240), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _scan_pdf():
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    page = document.new_page(width=180, height=240)
    page.insert_image(page.rect, stream=_png())
    raw = document.tobytes()
    document.close()
    return raw


def test_synthetic_image_and_scanned_quote_pdf_use_bounded_vision(monkeypatch):
    seen = _mock_transport(monkeypatch, ["Synthetic image text", "Synthetic PDF text"])
    assert ocr.extract_text_from_image(_png(), ".png") == "Synthetic image text"
    assert ocr.extract_text_from_pdf(_scan_pdf()) == "Synthetic PDF text"
    image_block = seen[0]["messages"][0]["content"][0]
    pdf_block = seen[1]["messages"][0]["content"][0]
    assert image_block["type"] == "image"
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert len(image_block["source"]["data"]) <= ocr._MAX_ENCODED_BYTES_PER_IMAGE
    assert pdf_block["type"] == "document"
    assert pdf_block["source"]["media_type"] == "application/pdf"
    assert all(req["model"] == ocr.ANTHROPIC_MODEL for req in seen)
    assert all(req["timeout"] for req in seen)


def test_receipt_pdf_preflight_sends_original_only_after_local_validation(monkeypatch):
    raw = _scan_pdf()
    monkeypatch.setattr(receipt_analyzer, "ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setenv("EPC_AI_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    parts = receipt_analyzer.prepare_receipt_content(raw, "synthetic.pdf")
    assert parts[0]["type"] == "document"
    assert base64.b64decode(parts[0]["source"]["data"]) == raw
    assert parts[-1]["type"] == "text"
    assert len(parts) == 2


def test_monthly_structured_result_and_malformed_response(monkeypatch):
    seen = _mock_transport(monkeypatch, ['{"facts": []}', "not JSON"])
    content = [{"type": "text", "text": 'Synthetic page 1: inspected pump'}]
    assert monthly_report_ai.request_json(content) == {"facts": []}
    with pytest.raises(ValueError, match="incomplete response"):
        monthly_report_ai.request_json(content)
    assert seen[0]["max_tokens"] == 8000
    assert seen[0]["messages"][0]["content"] == content


def test_receipt_structured_result_remains_editable_and_malformed_is_rejected(monkeypatch):
    _mock_transport(monkeypatch, [
        '{"merchant_name":"Synthetic Merchant","transaction_date":"2026-11-01",'
        '"total_amount":"12.00","tax_amount":"0","currency":"USD",'
        '"suggested_description":"Synthetic office supplies","line_items":[],"confidence":"low"}',
    ])
    result = receipt_analyzer.analyze_prepared_receipt(
        [{"type": "text", "text": "Synthetic fixture only"}]
    )
    assert result.merchant_name == "Synthetic Merchant"
    assert result.total_amount == "12.00"
    with pytest.raises(receipt_analyzer.ReceiptAnalysisError):
        receipt_analyzer.normalize_receipt_response("invalid JSON")


def _status_error(status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request)
    return anthropic.APIStatusError("synthetic-status", response=response, body=None)


@pytest.mark.parametrize("status,expected_calls", [(400, 1), (401, 1), (403, 1), (429, 3), (500, 3)])
def test_error_policy_auth_and_validation_do_not_retry_throttle_and_server_do(monkeypatch, status, expected_calls):
    monkeypatch.setattr(api_retry.time, "sleep", lambda _: None)
    called = []

    def request(timeout):
        called.append(timeout)
        raise _status_error(status)

    with pytest.raises(anthropic.APIStatusError):
        api_retry.request_with_retry(
            request, until=time.monotonic() + 120, backoff=0,
        )
    assert len(called) == expected_calls


def test_expired_deadline_never_calls_provider():
    with pytest.raises(TimeoutError, match="timed out"):
        api_retry.request_with_retry(
            lambda _: _never_contact_provider(), until=time.monotonic() - 1
        )


def test_disabled_provider_keeps_local_text_reading_available(monkeypatch):
    monkeypatch.setenv("EPC_AI_PROVIDER", "disabled")
    monkeypatch.setattr(anthropic, "Anthropic", _never_contact_provider)
    assert ocr.extract_text(b"Synthetic operator notes", "notes.txt") == (
        "Synthetic operator notes"
    )
    # The same file model and deterministic assembly remain importable.
    assert callable(monthly_report_ai.normalize_facts)
    assert callable(receipt_analyzer.normalize_receipt_response)


def test_disabled_pdf_reader_refuses_before_fallback_raster(monkeypatch):
    monkeypatch.setenv("EPC_AI_PROVIDER", "disabled")
    monkeypatch.setattr(ocr, "ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setattr(
        ocr, "_ocr_pdf_via_page_images",
        lambda *args, **kwargs: pytest.fail("provider refusal cannot raster-fallback"),
    )
    with pytest.raises(AIProviderConfigurationError):
        ocr.extract_text_from_pdf(_scan_pdf())


def test_disabled_host_diagnostic_skips_outbound_probe(monkeypatch):
    from scripts import host_check
    monkeypatch.setenv("EPC_AI_PROVIDER", "disabled")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setattr(anthropic, "Anthropic", _never_contact_provider)
    report = host_check.Report()
    host_check.check_anthropic(report)
    assert report.failures == 0
