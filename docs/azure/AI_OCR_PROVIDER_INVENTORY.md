# A06 — AI/OCR data-flow inventory and ENFRA provider contract

Status: **PREPARATION ONLY / NO PROVIDER APPROVAL OR LIVE SWITCH**.
Audited code: `57c5cd87e3e441dfea3cddbc666248f8e469d986` on
2026-11-11, plus A01 proposed migration manifest in draft PR #849.
Architecture: **Linux Azure App Service**, not Azure Container Apps.
This public document intentionally contains no live prompts, customer originals,
credentials, internal hostnames, account identifiers or raw provider responses.

## Decision and routing guard

A01 `docs/azure/MIGRATION_MANIFEST.md` (PR #849, not yet merged) says the
**approved AI provider, endpoint, model and credential path are TBD**.
Azure App Service, Entra, Azure AI, Copilot, and Anthropic egress are separate
decisions. No evidence establishes that the existing Anthropic SDK key is
authorized for ENFRA hosting, or that a Copilot UI subscription supplies a
compatible API.

The smallest safe preparation is `app/ai_provider.py`: one SDK-client factory
boundary and **explicit fail-closed routing** for existing Anthropic. All four
direct production model-call modules use it. The only supported setting values:

- `EPC_AI_PROVIDER=anthropic`: current legacy/Render-compatible SDK behavior
  using the existing `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`; **not**
  approval for future ENFRA egress.
- `EPC_AI_PROVIDER=disabled`: no new model calls; continue local parsing,
  manual entry and cached reviews when appropriate.
- Any other value, including an enterprise gateway or Azure endpoint: fail
  before creating a client. An explicit reviewed adapter is required first.
- An `ANTHROPIC_BASE_URL` override fails closed rather than redirecting the
  SDK key and uploaded documents to an unreviewed compatible endpoint.
  Network proxy/CA approval remains a separate ENFRA decision.

**For ENFRA deployment preparation, explicitly set `EPC_AI_PROVIDER=disabled`
until an authorized provider contract is recorded.** No environment variable,
model endpoint or production credential has been changed by A06. Render's
legacy default remains unchanged. The adapter does not implement a gateway,
Azure OpenAI, or automatic fallback.

## Executable outbound-call inventory

Default target for the existing Anthropic SDK is `api.anthropic.com` over
HTTPS unless the host's networking/proxy changes it. All model calls use
`client.messages.create`, with a server-side API key and model selected from
`ANTHROPIC_MODEL` (checked-in default `claude-sonnet-4-6`). They are not
browser calls; model answers are **editable suggestions**, never authority for
report generation, approvals or Smartsheet submission.

| ID | Caller and purpose | Payload categories (synthetic examples only) | Response and bound | Fallback/review |
|---|---|---|---|---|
| Q1 | `app/ocr.py::_ocr_request` from PO images and scanned PDF | Vendor quote image(s) as base64 JPEG; contiguous scanned PDF as native base64 PDF first, plus OCR instruction. May contain vendor contact, site, equipment, quoted scope, prices and dates. | Free text, max 8,192 output tokens. Up to 20 scanned PDF pages (native-text pages do not count), 20 image frames, 40 MP/frame, 1,568px normalized image edge, 5 MiB encoded/frame and 24 MiB encoded image batch; direct PDF also capped at 24 MiB base64. | Native text and .txt remain local. Only a native-document 400/413 or local PDF-document budget rejection may try **the same provider** with rendered page images. Auth/429/5xx/timeout/partial output do not trigger a different paid OCR route. |
| Q2 | `app/quote_analyzer.py::analyze_quote`, PO classification | Full extracted quote text (which can contain prices, tax and identifying details), facility/equipment policy and scoped task instructions. | Structured JSON; max 4,096 output tokens; strict `analysis_schema` validation, deterministic cost codes/asset/site matching and price stripping from published descriptions. | Up to two response-shape attempts within the shared deadline; invalid/unavailable analysis leaves a visible retry and source text. **Gap:** pasting text alone does not complete the normal structured PO workflow while the model is down. |
| E1 | `app/receipt_analyzer.py::analyze_prepared_receipt`, Expense extraction | After preflight, original base64 PDF (max 10 pages) **or** normalized JPEG receipt pages; merchant, purchased items, dates, tax, totals, customer information and possibly payment traces. PDF retains original bytes in request. | Structured JSON; max 3,000 output tokens, two response-shape attempts, 60 examined line items, deterministic amount and policy validation. Image/page dimensions preflight capped at 40 MP. | Bad shape, auth, 429/5xx, deadline or OCR failures leave completeable required manual fields, an explicit retry and original receipt view. |
| M1 | `app/monthly_report_ai.py::request_json` via `extraction_request`, Monthly fact reading | Selected native source text with source/page IDs, date, facility, vendor, equipment/operations narratives (e.g., “inspected synthetic pump”). Capped at 60,000 evidence characters. | JSON up to 8,000 output tokens, at most 100 facts; source page and exact supporting quote verified before acceptance. | Error or malformed/incomplete response does not alter accepted facts; retry or enter facts manually. Local native ingestion continues. |
| M2 | Same transport via `drafting_request`, Monthly narrative suggestion | Compact source-bound facts, period, vendor names/tags and optional user drafting notes (max 2,000 chars); excludes priced fact text. Max 60,000 payload characters. | JSON up to 8,000 output tokens, max 60 draft paragraphs; fact IDs, numerical claims, dates and price exclusions verified. | Cached result or manual writing; operator explicitly reviews Add/Replace. Invalid answer cannot silently change assembled document. |
| M3 | `app/monthly_report_image_review.py::read_image` through `app/ocr.py::_ocr_request`, Monthly image transcription | One normalized page/image and prompt. Could contain operations/safety data, dates, handwritten names, readings or incident text. | Text max 8,192 model tokens; downstream 40,000-character reading cap, 20 distinct image reviews per scope; shared JPEG pixel/base64 guards. | Original image retained; review/enter visible facts manually. Cached successful transcriptions and budget ledger stored separately. |
| D1 | `scripts/host_check.py::check_anthropic`, optional operator-run diagnostics | Anthropic model ID and API key; **no customer document**. Calls `client.models.retrieve`, timeout 30 s; this is a real external call even if no generation tokens. | Model metadata/status only. | **Do not run in A06 preparation.** Use `python scripts/host_check.py --offline` to skip it; live probe needs separate approval. |

Additional AI-related entry points: `app/monthly_report_ai_ui.py` enqueues
M1/M2/M3 through bounded `app/receipt_jobs.py`; `app/expense_ui.py` enqueues
E1 through the same two-slot worker. Cancellation discards late results but
cannot guarantee a request already accepted by the external provider has
stopped executing or billing. `app/web_ui.py` calls Q1 then Q2. There are no
other direct AI SDK calls in these inspected app execution paths. Existing
`app/pdf_converter.py` (optional Gotenberg) and Smartsheet HTTP requests are
**non-AI integration destinations** and must be separately approved.

## A second, operator-mediated Copilot path (no MSAPO HTTP call)

`app/monthly_report_prompts.py::copilot_prompt` creates text an operator
can copy into Copilot, referencing site names, reporting dates, vendor names
and asset tags. The operator performs the search in their existing
Outlook/Teams/Calendar access and pastes notes into MSAPO, where source
attribution remains reviewable. This is **not** an API integration or consent
to send uploaded files to Copilot. Its separate external access, data boundary
and retention must be approved by ENFRA if retained in the new environment.

## Authentication, timeouts, error policy and storage

- **Current transport:** Anthropic SDK server-side `ANTHROPIC_API_KEY`,
  `ANTHROPIC_MODEL`; SDK automatic retries disabled (`max_retries=0`).
  Default I/O timeout 60s (configurable 10–120), common operation deadline 120s
  (30–300). The shared retry owner uses at most three transport attempts,
  retrying connection failures, 429 and 5xx only; 4xx auth/validation failures
  do not retry. Q2/E1 have up to two response-shape attempts under that same
  deadline. No automatic cross-provider retry.
- **Client transport:** this SDK uses an HTTPS API key; no managed identity,
  OIDC or enterprise gateway authentication is currently implemented.
  Corporate DNS, proxy, TLS interception and certificate trust require an
  approved ENFRA contract. Do not place credentials in git, CLI args, PRs,
  synthetic fixtures or application telemetry.
- **Application persistence:** Monthly source originals, selected evidence,
  approved facts and generated report history are application data. Monthly
  `ai/extraction`, `ai/draft` caches, per-month 80-call allowance and image
  review cache/budget live under the contract/site-scoped local data tree
  (`EPC_DATA_DIR`). Expense analysis is primarily in the Streamlit session
  and employee draft state; originals are embedded in the reviewed expense
  packet. PO quote source/review state is maintained for the interactive
  workflow. A06 changes no storage semantics. A05 owns durable storage design.
- **Retention and logging unknowns:** provider-side retention, training use,
  abuse monitoring, subprocess/proxy traces, cross-region processing, and
  incident access **cannot be inferred from SDK defaults or an Azure host**.
  The new adapter logs no payloads. Existing UI error handlers can surface
  provider exception text; review their redaction and hosting application
  logs before enabling real customer use. Do not assert zero retention or
  no telemetry. Set retention, residency, DLP and log redaction in the approved
  contract and enforce them on both provider and enterprise networking paths.

## ENFRA endpoint contract still required

Mark each item *unresolved* until the authorized ENFRA decision record is
available; never invent a value in this public repository.

1. Explicit allowed provider and destination category (existing Anthropic
   egress vs internal enterprise gateway vs Azure model service vs other),
   owner/approval ticket and separate nonproduction/production authorization.
2. Exact API base URL and protocol/schema: Anthropic Messages, Azure OpenAI
   Responses/Chat Completions, or approved gateway; supported tool/stop reasons
   and JSON output semantics. A Copilot app license is not a substitute.
3. Auth mechanism (Key Vault secret, Entra managed identity/token audience or
   gateway-specific header), principal, rotation, network egress/allowlist,
   private endpoint/proxy, DNS, TLS CA and regional processing.
4. Approved model and deployment IDs, version lifecycle, output-token
   ceilings, context limits, rate/token quotas, parallelism and timeouts.
5. Input support: plain text, ordered images/multiframe TIFF, base64 or
   multipart native PDFs, max sizes/pages, image preprocess requirements and
   deterministic fallback order on 400/413 vs 401/403/429/5xx.
6. Provider retention, training/data-use exclusions, abuse review, prompts
   and outputs in logging, audit identifiers, deletion and data-residency rules.
7. Required application redaction/telemetry/incident handling, cancellation
   semantics and managed retry-rate control; approved synthetic nonprod QA
   endpoint and available test credentials (never publish values).

After approval, add **one** reviewed adapter behind
`app/ai_provider.py`. Maintain the existing `client.messages.create`
contract or add a precise translation with tested text, image and native-PDF
capabilities. For an endpoint without native PDF, select a locally rendered
page-image route **before** any send, not after paying for an unsupported
request. Translate provider errors into the existing single bounded retry
policy; do not accept a partial output; no implicit fallback to Anthropic.
If the approved provider cannot support a workflow, disable that AI path
while retaining the manual/local workflow. Do not move deterministic report
assembly or source validation into the model.

## Synthetic-only verification and release gate

`tests/test_ai_provider_contract.py` covers disabled/unapproved destinations
and SDK base-URL overrides before any client creation, text/image/scanned PDF,
receipt native PDF preservation, invalid JSON, 400/401/403, 429/5xx retry
bounds, deadlines and local text reading. Existing focused regression tests:
`tests/test_ocr_images.py`, `tests/test_pdf_page_budget.py`,
`tests/test_receipt_analyzer.py`, `tests/test_monthly_report_ai.py`,
`tests/test_analysis_schema.py`, `tests/test_quote_analysis_guesses.py`
and `tests/test_ai_evidence_focus_width.py`. All use synthetic data and
fake/model-mocked network calls. Re-run after integrating future approved
provider code and report exact SHA/CI evidence, rather than claiming
provider compatibility from mocked tests alone.

Suggested focused command (offline):
```sh
EPC_AI_PROVIDER=anthropic pytest -q tests/test_ai_provider_contract.py \
  tests/test_ocr_images.py tests/test_pdf_page_budget.py \
  tests/test_receipt_analyzer.py tests/test_monthly_report_ai.py \
  tests/test_analysis_schema.py tests/test_quote_analysis_guesses.py
```

Do **not** run `host_check.py` without `--offline`, supply real documents,
attempt a live provider switch, merge this migration preparation automatically
or describe a synthetic success as ENFRA approval. Coordinate merge/rebase
with A01/A05/P20 and the final immutable release baseline.
