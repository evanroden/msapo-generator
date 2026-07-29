import json
import sys
import types

import pytest

from app.adapter_loader import AdapterConfigurationError, load_adapter
from app.ai_provider import AIProviderError, AIRequest, CAP_IMAGE, CAP_TEXT
from app.memory import SQLiteMemoryBackend
from app.ocr import extract_text_from_pdf
from app.pdf_converter import PDFConversionError, convert_to_pdf, get_pdf_converter
from app.pdf_reader import PDFReadResult, RenderedPage
from app.quote_analyzer import analyze_quote
from app.runtime import RuntimeSettings
from app.smartsheet_store import SubmissionStore


class FakeProvider:
    name = "fake"
    capabilities = frozenset({CAP_TEXT, CAP_IMAGE})

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.requests = []

    def complete(self, request: AIRequest):
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else "text"

    def diagnostic(self):
        return {"configured": True, "name": self.name}


def test_dynamic_adapter_loads_and_validates():
    module = types.ModuleType("fake_portability_adapter")
    module.create = lambda env: FakeProvider()
    sys.modules[module.__name__] = module
    adapter = load_adapter(
        "fake_portability_adapter:create",
        kind="AI",
        required_methods=("complete", "diagnostic"),
        env={},
    )
    assert adapter.name == "fake"
    with pytest.raises(AdapterConfigurationError):
        load_adapter("missing", kind="AI", required_methods=("complete",), env={})


def test_optional_environment_factory_receives_environment():
    module = types.ModuleType("optional_env_adapter")
    captured = {}

    def create(env=None):
        captured.update(env or {})
        return FakeProvider()

    module.create = create
    sys.modules[module.__name__] = module
    load_adapter(
        "optional_env_adapter:create",
        kind="AI",
        required_methods=("complete", "diagnostic"),
        env={"MARKER": "present"},
    )
    assert captured["MARKER"] == "present"


def test_quote_analyzer_uses_provider_contract():
    payload = {
        "vendor_name": "Vendor",
        "project_description": "Pump repair $900.00",
        "scope_of_work": "Repair pump for $900.00",
        "inclusions": ["Labor $900.00"],
        "exclusions": [],
        "tax_status": "unclear",
        "ai_assumptions": [],
    }
    provider = FakeProvider([json.dumps(payload)])
    result = analyze_quote("quote", provider=provider)
    assert result.vendor_name == "Vendor"
    assert "$" not in result.scope_of_work
    assert provider.requests[0].operation == "quote_analysis"


def test_quote_analysis_input_limit_is_fail_closed():
    provider = FakeProvider([])
    with pytest.raises(ValueError, match="above the configured AI input limit"):
        analyze_quote(
            "x" * 1001,
            provider=provider,
            env={"EPC_AI_MAX_INPUT_CHARS": "1000"},
        )
    assert provider.requests == []


class TextReader:
    name = "reader"
    rendered = False

    def extract_text(self, data):
        return PDFReadResult("embedded text is definitely long enough", data, 1)

    def render_pages(self, *args, **kwargs):
        self.rendered = True
        raise AssertionError("should not render")

    def diagnostic(self):
        return {"configured": True}


class ImageReader:
    name = "reader"

    def extract_text(self, data):
        return PDFReadResult("", data, 7)

    def render_pages(self, data, **kwargs):
        return [RenderedPage(i, f"page-{i}".encode()) for i in range(1, 8)]

    def diagnostic(self):
        return {"configured": True}


def test_pdf_text_layer_avoids_ai():
    provider = FakeProvider([])
    reader = TextReader()
    text = extract_text_from_pdf(b"pdf", provider=provider, reader=reader, env={})
    assert text.startswith("embedded")
    assert provider.requests == []
    assert not reader.rendered


def test_image_only_ai_is_batched_for_pdf_ocr():
    provider = FakeProvider(["one", "two", "three"])
    text = extract_text_from_pdf(
        b"pdf",
        provider=provider,
        reader=ImageReader(),
        env={"EPC_OCR_PAGES_PER_BATCH": "3"},
    )
    assert text == "one\ntwo\nthree"
    assert [len(request.parts) for request in provider.requests] == [3, 3, 1]


class DocumentErrorProvider(FakeProvider):
    capabilities = frozenset({CAP_TEXT, CAP_IMAGE, "document"})

    def complete(self, request):
        raise AIProviderError("bad key", code="authentication")


def test_authentication_error_is_not_hidden_by_image_fallback():
    with pytest.raises(AIProviderError, match="bad key"):
        extract_text_from_pdf(
            b"pdf",
            provider=DocumentErrorProvider(),
            reader=ImageReader(),
            env={},
        )


def test_pdf_adapter_value_objects_reject_invalid_results():
    with pytest.raises(ValueError, match="page_count"):
        PDFReadResult("text", b"pdf", 0)
    with pytest.raises(ValueError, match="non-empty"):
        RenderedPage(1, b"")


def test_custom_pdf_reader_factory():
    from app.pdf_reader import get_pdf_reader

    module = types.ModuleType("fake_pdf_reader_adapter")
    module.create = lambda env: TextReader()
    sys.modules[module.__name__] = module
    reader = get_pdf_reader(
        {
            "EPC_PDF_READER": "custom",
            "EPC_PDF_READER_ADAPTER": "fake_pdf_reader_adapter:create",
        }
    )
    assert reader.name == "reader"


class CustomConverter:
    name = "custom"

    def convert(self, docx_path, output_dir):
        target = output_dir / f"{docx_path.stem}.pdf"
        target.write_bytes(b"%PDF-1.7\n")
        return target

    def diagnostic(self):
        return {"configured": True}


def test_custom_converter_injection(tmp_path):
    docx = tmp_path / "a.docx"
    docx.write_bytes(b"docx")
    result = convert_to_pdf(docx, converter=CustomConverter())
    assert result.read_bytes().startswith(b"%PDF-")


def test_custom_converter_factory():
    module = types.ModuleType("fake_converter_adapter")
    module.create = lambda env: CustomConverter()
    sys.modules[module.__name__] = module
    converter = get_pdf_converter(
        {
            "EPC_PDF_CONVERTER": "custom",
            "EPC_PDF_CONVERTER_ADAPTER": "fake_converter_adapter:create",
        }
    )
    assert converter.name == "custom"


def test_libreoffice_does_not_reuse_stale_pdf(monkeypatch, tmp_path):
    from app.pdf_converter import LibreOfficeConverter

    docx = tmp_path / "quote.docx"
    docx.write_bytes(b"docx")
    stale = tmp_path / "quote.pdf"
    stale.write_bytes(b"%PDF-old")
    monkeypatch.setattr(
        "app.pdf_converter.shutil.which", lambda name: "/usr/bin/libreoffice"
    )
    monkeypatch.setattr(
        "app.pdf_converter.subprocess.run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
    )
    with pytest.raises(PDFConversionError, match="without the expected PDF"):
        LibreOfficeConverter().convert(docx, tmp_path)
    assert stale.read_bytes() == b"%PDF-old"


def test_gotenberg_rejects_html_success_response(monkeypatch, tmp_path):
    from app.pdf_converter import GotenbergConverter

    class Response:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        content = b"<html>not a pdf</html>"
        text = "not a pdf"

    monkeypatch.setattr(
        "app.pdf_converter.requests.post", lambda *args, **kwargs: Response()
    )
    docx = tmp_path / "quote.docx"
    docx.write_bytes(b"docx")
    with pytest.raises(PDFConversionError, match="valid PDF"):
        GotenbergConverter(base_url="http://localhost:3000").convert(docx, tmp_path)


def test_openai_compatible_provider_uses_explicit_endpoint(monkeypatch):
    from app.ai_provider import OpenAIChatCompatibleProvider

    class Response:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        return Response()

    monkeypatch.setattr("app.ai_provider.requests.post", post)
    provider = OpenAIChatCompatibleProvider(
        endpoint="https://ai.example.com/v1/chat/completions",
        api_key="secret",
        model="enterprise-model",
    )
    assert provider.complete(AIRequest(operation="test", prompt="hello")) == "ok"
    assert captured["url"].startswith("https://ai.example.com")
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_openai_compatible_provider_rejects_remote_http():
    from app.ai_provider import OpenAIChatCompatibleProvider

    with pytest.raises(AdapterConfigurationError, match="HTTPS"):
        OpenAIChatCompatibleProvider(
            endpoint="http://ai.example.com/chat",
            api_key="secret",
            model="model",
        )


def test_openai_compatible_nonretryable_400_is_not_retried(monkeypatch):
    from app.ai_provider import OpenAIChatCompatibleProvider

    class Response:
        status_code = 400
        headers = {}
        text = "bad request"

    calls = {"count": 0}

    def post(*args, **kwargs):
        calls["count"] += 1
        return Response()

    monkeypatch.setattr("app.ai_provider.requests.post", post)
    provider = OpenAIChatCompatibleProvider(
        endpoint="https://ai.example.com/chat",
        api_key="secret",
        model="model",
        max_retries=3,
    )
    with pytest.raises(AIProviderError) as exc:
        provider.complete(AIRequest(operation="test", prompt="hello"))
    assert exc.value.code == "http_400"
    assert exc.value.retryable is False
    assert calls["count"] == 1


def test_runtime_paths_and_port_are_host_neutral(tmp_path):
    settings = RuntimeSettings.from_environment(
        {
            "EPC_DATA_DIR": str(tmp_path / "data"),
            "EPC_WORK_DIR": str(tmp_path / "work"),
            "PORT": "9999",
        }
    )
    settings.ensure_directories()
    assert settings.port == 9999
    assert settings.output_dir.parent == settings.work_dir


def test_runtime_default_state_uses_writable_work_area():
    settings = RuntimeSettings.from_environment({})
    assert settings.data_dir.parent == settings.work_dir
    assert settings.output_dir.parent == settings.work_dir


def test_sqlite_memory_remains_contract_isolated(tmp_path):
    backend = SQLiteMemoryBackend(tmp_path / "memory.db", threshold=1)
    backend.record_send(
        contract="A",
        admin_email="admin@example.com",
        vendor="Vendor",
        contact_name="A Person",
        contact_email="a@example.com",
    )
    assert backend.suggest_admin_emails("A") == ["admin@example.com"]
    assert backend.suggest_admin_emails("B") == []
    assert backend.vendor_reps("B", "Vendor") == []


def test_custom_memory_backend_factory():
    from app.memory import get_memory_backend

    class Backend:
        name = "managed"

        def record_send(self, **kwargs):
            return True

        def suggest_admin_emails(self, contract):
            return []

        def suggest_contacts(self, contract):
            return []

        def vendor_reps(self, contract, vendor):
            return []

        def diagnostic(self):
            return {"configured": True}

    module = types.ModuleType("fake_memory_adapter")
    module.create = lambda env: Backend()
    sys.modules[module.__name__] = module
    backend = get_memory_backend(
        {
            "EPC_MEMORY_BACKEND": "custom",
            "EPC_MEMORY_ADAPTER": "fake_memory_adapter:create",
        }
    )
    assert backend.name == "managed"


def test_custom_submission_store_can_replace_sqlite():
    class Store:
        def claim(self, *args, **kwargs):
            pass

        def renew(self, *args, **kwargs):
            pass

        def record_row(self, *args, **kwargs):
            pass

        def record_attachment(self, *args, **kwargs):
            pass

        def finish(self, *args, **kwargs):
            pass

        def reconcile_row(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            pass

        def cleanup(self, *args, **kwargs):
            pass

    module = types.ModuleType("fake_submission_store")
    module.create = lambda env: Store()
    sys.modules[module.__name__] = module
    store = SubmissionStore.from_environment(
        {
            "EPC_SUBMISSION_STORE_BACKEND": "custom",
            "EPC_SUBMISSION_STORE_ADAPTER": "fake_submission_store:create",
        }
    )
    assert isinstance(store, Store)


def test_live_sqlite_submission_store_requires_explicit_durable_path():
    from app.smartsheet_store import SubmissionStoreError

    with pytest.raises(SubmissionStoreError, match="durable EPC_DATA_DIR"):
        SubmissionStore.from_environment(
            {
                "SMARTSHEET_API_MODE": "live",
                "EPC_SUBMISSION_STORE_BACKEND": "sqlite",
            }
        )
