# Portability and Provider-Abstraction Guide

**Scope:** moving Email Process Control to a different host, AI API, PDF-reading library, PDF converter, or persistent database without changing the quote-to-PO business rules.

## 1. Design rule

Business behavior must not depend on a vendor SDK. Quote analysis, OCR, facility matching, asset validation, document generation, tax handling, email construction, and Smartsheet idempotency remain in application modules. External tools sit behind narrow adapter contracts.

The application keeps safe defaults for the current deployment, but every infrastructure-sensitive component can now be selected through environment configuration:

| Concern | Default | Alternatives |
|---|---|---|
| AI generation and vision | Anthropic | OpenAI Chat-compatible HTTP endpoint; custom adapter |
| PDF text extraction/rendering | PyMuPDF | custom adapter using another library/service |
| DOCX-to-PDF conversion | LibreOffice | Gotenberg; docx2pdf; disabled; custom adapter |
| Contact learning | SQLite | disabled; custom managed-store adapter |
| Smartsheet idempotency | SQLite | custom durable-store adapter |
| Hosting | Render container | any Docker/PaaS host that supports HTTP and writable/persistent paths |

No custom adapter path is derived from user input. Adapter imports are controlled only by trusted deployment environment variables.

## 2. Runtime filesystem model

The runtime distinguishes:

- `EPC_TEMPLATE_PATH`: read-only MSAPO template.
- `EPC_DATA_DIR`: persistent state, including contact memory and Smartsheet idempotency.
- `EPC_WORK_DIR`: ephemeral scratch area.
- `EPC_OUTPUT_DIR`: ephemeral generated DOCX/PDF files.
- `PORT` or `EPC_PORT`: platform-assigned HTTP port.
- `EPC_HOST`: bind address, normally `0.0.0.0`.

The default data directory is inside the operating system's writable work area so read-only application images can start. A production deployment that needs persistence must set `EPC_DATA_DIR` explicitly. **Live Smartsheet submission refuses implicit temporary SQLite storage.** A platform without a persistent volume must use a custom submission-store adapter backed by a managed database.

Run before deployment:

```bash
python -m app.doctor
python -m app.doctor --json
```

The command checks paths, template availability, provider configuration, PDF reader/converter availability, memory, and submission-store configuration. It exits nonzero when a required component is unavailable.

## 3. AI provider contract

The provider-neutral request model is in `app/ai_provider.py`.

```python
class Provider:
    name = "company-ai"
    capabilities = frozenset({"text", "image"})

    def complete(self, request: AIRequest) -> str:
        ...

    def diagnostic(self) -> dict:
        return {"configured": True, "name": self.name}
```

`AIRequest` contains a stable operation name, provider-neutral system instructions, prompt text, optional binary image/document parts, and an output-token ceiling.

### Built-in Anthropic adapter

```text
EPC_AI_PROVIDER=anthropic
EPC_AI_API_KEY=...
EPC_AI_MODEL=...
```

Legacy `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` remain supported.

### Built-in OpenAI Chat-compatible adapter

Use when ENFRA supplies an enterprise endpoint implementing the Chat Completions message/choice shape:

```text
EPC_AI_PROVIDER=openai_chat_compatible
EPC_AI_ENDPOINT=https://enterprise-ai.example.com/v1/chat/completions
EPC_AI_API_KEY=...
EPC_AI_MODEL=...
EPC_AI_AUTH_HEADER=Authorization
EPC_AI_AUTH_PREFIX=Bearer 
```

This adapter supports text and image inputs. It does not claim native PDF support; the OCR pipeline renders pages through the selected PDF reader. Remote endpoints must use HTTPS. Non-transient 4xx responses are not retried as network failures.

### Fully custom AI adapter

```text
EPC_AI_PROVIDER=custom
EPC_AI_ADAPTER=company_epc.ai:create_provider
```

```python
class InternalProvider:
    name = "enfra-internal"
    capabilities = frozenset({"text", "image"})

    def complete(self, request: AIRequest) -> str:
        return internal_client.generate(...)

    def diagnostic(self):
        return {"configured": True, "name": self.name}


def create_provider(env):
    return InternalProvider()
```

Factories may accept zero arguments or one environment mapping. Provider-specific authentication, retry classification, and response parsing stay inside the adapter.

Quote text is subject to `EPC_AI_MAX_INPUT_CHARS` and is rejected rather than silently truncated.

## 4. PDF reader contract

```python
class Reader:
    name = "company-pdf"

    def extract_text(self, data: bytes) -> PDFReadResult:
        ...

    def render_pages(
        self, data: bytes, *, dpi: int, max_pages: int,
        max_pixels_per_page: int
    ) -> list[RenderedPage]:
        ...

    def diagnostic(self) -> dict:
        ...
```

Configure:

```text
EPC_PDF_READER=pymupdf
```

or:

```text
EPC_PDF_READER=custom
EPC_PDF_READER_ADAPTER=company_epc.pdf:create_reader
```

A custom implementation can use an approved local library, cloud document service, or internal OCR system. Business code does not import that library.

### OCR safety controls

- Embedded text must pass minimum length and printable/alphanumeric quality checks.
- Password-to-open PDFs fail clearly rather than being treated as empty.
- Owner-locked PDFs may be normalized for analysis while original bytes remain unchanged.
- Native document input is used only when the AI provider advertises support.
- Authentication/network/quota errors are not hidden by a second costly fallback request.
- Page rendering has page, DPI, pixel, and aggregate-byte limits.
- Multi-page OCR is batched to avoid one oversized model request.
- Empty rendered-page results are rejected.
- Images and normalized frames have a 50 MB safety ceiling.
- Adapter return objects validate page counts, media types, and non-empty bytes.

Environment controls:

```text
EPC_PDF_TEXT_MIN_CHARS=20
EPC_OCR_MAX_PAGES=30
EPC_OCR_DPI=150
EPC_OCR_PAGES_PER_BATCH=5
EPC_OCR_MAX_PIXELS_PER_PAGE=40000000
EPC_OCR_MAX_TOTAL_IMAGE_BYTES=52428800
```

## 5. PDF converter contract

```python
class Converter:
    name = "company-converter"

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        ...

    def diagnostic(self) -> dict:
        ...
```

Selection:

```text
EPC_PDF_CONVERTER=libreoffice
EPC_PDF_CONVERTER=gotenberg
EPC_PDF_CONVERTER=docx2pdf
EPC_PDF_CONVERTER=none
EPC_PDF_CONVERTER=custom
EPC_PDF_CONVERTER_ADAPTER=company_epc.convert:create_converter
```

Hardening added to built-ins:

- LibreOffice receives a unique user profile and output directory per conversion, avoiding concurrent profile locks and stale-output false positives.
- Every output must begin with a PDF signature before it is accepted.
- Gotenberg remote URLs require HTTPS unless an explicit local/test exception is configured.
- Gotenberg responses are status-, size-, and signature-checked.
- Output defaults to the source DOCX directory instead of a global host-specific directory.
- `none` gives a controlled DOCX-only workflow.

## 6. Persistent-store contracts

### Contact memory

```text
EPC_MEMORY_BACKEND=sqlite
EPC_MEMORY_BACKEND=disabled
EPC_MEMORY_BACKEND=custom
EPC_MEMORY_ADAPTER=company_epc.memory:create_backend
```

A custom memory backend implements `record_send`, `suggest_admin_emails`, `suggest_contacts`, `vendor_reps`, and `diagnostic`. Contract isolation remains mandatory.

### Smartsheet idempotency

```text
EPC_SUBMISSION_STORE_BACKEND=sqlite
EPC_SUBMISSION_STORE_BACKEND=custom
EPC_SUBMISSION_STORE_ADAPTER=company_epc.submissions:create_store
```

A custom store implements the existing claim/lease/row/attachment/reconciliation methods. Disabling this store while Smartsheet is live fails closed. Live SQLite also requires an explicitly configured durable `EPC_DATA_DIR`.

Managed-store implementations should provide transactional compare-and-set or row-lock semantics. Do not replace the lease with an in-memory cache on a multi-instance host.

## 7. Dependency packaging

- `requirements-core.txt`: provider-neutral web/document dependencies.
- `requirements-default-adapters.txt`: Anthropic, PyMuPDF, and HEIC support used by the current deployment.
- `requirements.txt`: installs both for backward-compatible default behavior.

A host using ENFRA-provided adapters can install core only, plus its internal adapter package:

```bash
pip install -r requirements-core.txt
pip install company-epc-adapters
```

Docker supports:

```bash
docker build \
  --build-arg EPC_REQUIREMENTS_FILE=requirements-core.txt \
  --build-arg INSTALL_LIBREOFFICE=false \
  -t email-process-control .
```

## 8. Hosting migration

The standard process command is:

```bash
python -m app.entrypoint
```

It reads `PORT`/`EPC_PORT` and `EPC_HOST`; no Render-specific port is embedded. The same command is used in the Docker image and `Procfile`.

A generic container host needs an HTTP service, read access to the template, writable ephemeral work/output storage, durable data storage or managed adapters, outbound access to selected services, and a single-instance/session-affinity strategy appropriate for Streamlit.

The current Streamlit application is not designed as a short-lived serverless function. A function migration would require separating the UI from stateless workers and storing session/job state externally.

## 9. Portability failure modes

| Failure | Prevention |
|---|---|
| New provider silently interprets prompts differently | Provider contract tests use fixed fixtures and validate normalized business output. |
| Provider advertises document support but rejects PDFs | Only `UnsupportedCapabilityError` activates page-image fallback. |
| Authentication failure triggers multiple paid fallback calls | Authentication/connection/quota errors propagate and stop the pipeline. |
| Non-transient provider 400 is retried as a network error | HTTP classification keeps definite 4xx failures non-retryable. |
| Alternate PDF reader returns invalid objects | Runtime dataclass and adapter validation. |
| Alternate PDF reader returns garbage text | Embedded-text quality gate and OCR fallback. |
| Large scan exhausts memory/model limits | Page/pixel/byte ceilings and bounded batching. |
| Old PDF from a prior conversion is returned | Unique conversion output directory and signature validation. |
| Remote converter returns HTML with HTTP 200 | PDF signature validation rejects it. |
| Host application directory is read-only | State and generated output default to the OS work area. |
| Host assigns a non-8501 port | Entrypoint reads `PORT`. |
| Ephemeral host loses contact memory | Optional managed memory backend or deliberate disablement. |
| Ephemeral host loses Smartsheet idempotency | Live mode requires explicit durable storage or a custom managed store. |
| Custom adapter misses methods | Startup validation and `app.doctor` fail before workflow use. |
| Optional adapter factory never receives configuration | Loader passes environment whenever the factory accepts it. |
| Secret is sent to an unintended host | Explicit HTTPS endpoint validation; trusted deployment configuration only. |
| Horizontal scaling creates competing local databases | Remain single-instance or migrate both stores to shared transactional backends. |

## 10. Required tests before a provider/host switch

1. Run the full repository suite.
2. Add contract tests for the new adapter using redacted real fixtures.
3. Confirm tax, pricing, facility, cost-code, and asset behavior is unchanged.
4. Test embedded-text, scan, owner-locked, image, HEIC, long, and malformed inputs.
5. Test provider 401/403, 400, 429, timeout, malformed response, empty response, and unsupported-media behavior.
6. Test converter timeout, concurrent conversion, invalid output, and disabled mode.
7. Restart the host and prove persistent learning/idempotency survives.
8. Test one real iPad/iPhone and desktop browser.
9. Run `python -m app.doctor` in the exact production image/environment.
10. Keep the old provider configuration available for rollback until acceptance is complete.

## 11. Migration sequence

1. Add the new adapter package and contract tests without changing production selection.
2. Deploy with the old adapter and run `app.doctor`.
3. Switch only one concern at a time: reader, AI, converter, storage, then host.
4. Use a controlled set of redacted quotes and compare normalized results.
5. Keep Smartsheet API mode disabled during infrastructure migration unless idempotency persistence has been explicitly verified.
6. Activate production only after operator and real-device acceptance.
