# Email Process Control

Email Process Control turns a vendor quote into a reviewed MSAPO package and a ready-to-send purchase-order email. It is a Dockerized Streamlit application deployed on Render.

The repository retains its original `msapo-generator` name, but the product is a quote-to-email workflow with a disabled-by-default future Smartsheet handoff.

## Current workflow

1. Select standard MSAPO or Equipment-only PO mode.
2. Upload a PDF/image/text file or paste quote text.
3. Extract text locally when possible; use Claude vision for scans/images.
4. Validate Claude's structured quote analysis.
5. Review scope, inclusions, exclusions, tax, routing, cost code, asset, contact, and pricing.
6. Generate MSAPO DOCX and, when LibreOffice succeeds, PDF.
7. Open a ready-to-send Outlook draft or Apple Mail share flow.
8. Explicitly record a completed send for contract-isolated contact suggestions.

Equipment-only POs preserve and attach the original quote but skip MSAPO generation.

## Non-negotiable behavior

- Standard MSAPO documents are generated for **all contracts**, not only RRH.
- RRH retains its dedicated sites, cost-code derivation, fixed administrator, and conservative asset registry.
- Data learned for one contract never appears on another.
- An unresolved asset defaults to no applicable asset; the application never selects the first asset by convenience.
- Unknown contract/site routing must be explicitly confirmed.
- The original quote bytes are preserved unchanged.
- Generated documents are accepted only while their contract/site/review fingerprint remains current.
- Optional integrations remain inert until verified configuration exists.

## Project structure

```text
app/web_ui.py                 Current quote/email workflow
app/quote_analyzer.py          Claude quote extraction
app/analysis_schema.py         Claude response validation
app/ocr.py                     PDF/image extraction and normalization
app/document_generator.py      MSAPO DOCX generation
app/pdf_converter.py           LibreOffice/Gotenberg/docx2pdf conversion
app/eml_builder.py             Outlook and Apple Mail draft content
app/contracts.py               Non-RRH contract/site/asset registry
app/assets.py                  RRH asset registry
app/memory.py                  Contract-isolated SQLite learning
app/po_context.py              Verified cross-page PO snapshot
app/smartsheet.py              Manual, URL-prefill, and API routes
app/smartsheet_store.py        Leased/idempotent API state
app/smartsheet_ui.py           Mobile manual-copy assistant
pages/2_Smartsheet_PO.py       Future Smartsheet handoff page
docs/FAILURE_MODES_AND_CONTROLS.md
                               Reliability register and incident runbooks
tests/                         Pytest regression suite
```

## Template behavior

`app/document_generator.py` opens `templates/Master_MSAPO_Template.docx`, verifies the sentinel paragraph, clears the pre-filled first exhibit row, and appends the reviewed facility, vendor, project description, detailed scope, inclusions, exclusions, and tax status.

The template does not use `{{TAG}}` replacement. A text audit found no RRH/facility wording, but legal applicability and non-text branding still require business confirmation before broad rollout.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate      # Windows
python -m pip install -r requirements-dev.txt
cp .env.example .env
streamlit run run_web.py
```

Required local secret:

```text
ANTHROPIC_API_KEY=...
```

Run tests:

```bash
python -m pytest -q
```

Pull requests and pushes to `main` run the same suite in GitHub Actions and retain a seven-day JUnit artifact.

## Deployment

Render runs one Docker web service on port 8501. Production uses LibreOffice and stores contact learning plus Smartsheet idempotency state on the persistent disk at `EPC_DATA_DIR=/test1`.

Render dashboard values can override `render.yaml`; inspect both when a model, credential, or integration change appears ineffective.

SQLite is appropriate only while the service remains single-instance. Migrate learning and idempotency to a shared transactional database before scaling horizontally.

## Input support

The UI accepts PDF, TXT, PNG, JPEG, WebP, TIFF/TIF, BMP, and HEIC/HEIF/HIF. Text PDFs are extracted locally. TIFF/BMP/HEIC are normalized to Claude-compatible PNG blocks in memory; the original upload remains unchanged for attachment.

## Smartsheet transition

The draft handoff supports three independent routes. All are disabled by default and all reuse the same verified source record.

### Manual copy/paste

Configure the final `SMARTSHEET_FORM_URL`, form order, and confirmed required fields. The page supplies one-tap values in order and safe adjacent attachment downloads. It opens only when the source package and configured required fields pass preflight.

### Exact-label URL prefill

After testing the final form, configure:

- `SMARTSHEET_URL_PREFILL_ENABLED=true`
- `SMARTSHEET_FORM_FIELD_MAP_JSON` using exact visible labels
- optional `SMARTSHEET_FORM_VALUE_MAP_JSON` using exact option values
- `SMARTSHEET_FORM_REQUIRED_FIELDS`
- optional `SMARTSHEET_PREFILL_MAX_URL_LENGTH` (default 7000)

The application never guesses parameter names. Existing mapped parameters are replaced rather than duplicated. Oversized fields are skipped with reasons. Files must still be attached manually.

### Direct API

Proceed from `disabled` to `dry_run` before `live`. Configure:

- dedicated least-privilege `SMARTSHEET_API_TOKEN`
- `SMARTSHEET_SHEET_ID`
- `SMARTSHEET_COLUMN_SPECS_JSON`
- `SMARTSHEET_REQUIRED_FIELDS`
- a dedicated writable `submission_key` text column

Each column specification records a numeric ID, exact title, exact type, and optionally expected picklist options. Live validation blocks renamed, retyped, locked, system, formula, or option-drifted columns. Values are sent strictly typed; no `strict:false` coercion is used.

API reliability controls include:

- deterministic field/attachment submission key;
- expiring single-owner SQLite lease;
- duplicate rows blocked across reruns and reopened browsers;
- ambiguous row creation marked `uncertain`, never blindly retried;
- exact submission-key reconciliation, including recovery after local-state loss;
- deterministic remote attachment names and remote-list verification after a lost upload response;
- partial attachment retry resumes the same row;
- empty, duplicate, unsafe, or over-30-MB attachments blocked;
- values over 4,000 characters blocked before silent cell truncation;
- live tokens restricted to `api.smartsheet.com`.

The ENFRA work-order form is an example only. Its labels, options, requirements, and URL are not activated as the final PO schema.

## Reliability and activation

Read [`docs/FAILURE_MODES_AND_CONTROLS.md`](docs/FAILURE_MODES_AND_CONTROLS.md) before configuring or merging the Smartsheet route. It contains the failure-mode register, activation gates, acceptance matrix, and runbooks for uncertain writes, partial attachments, schema drift, form changes, and idempotency-store failure.

PR #25 should remain draft until the final PO form/sheet exists, exact mappings are confirmed, real Safari is tested, and one controlled live row-plus-attachments round trip succeeds.

## Security cautions

- Quotes may contain pricing, contacts, facility, and asset information and may be sent to Anthropic for analysis/OCR.
- The current production app has no merged application-level authentication. Configure Render protection or merge the fail-closed access gate only after its secret exists; ENFRA SSO is preferable before broad use.
- Do not commit API keys, tokens, production mappings, or real credentials.
- Live Smartsheet API use requires a dedicated least-privilege service account.
- The original quote and generated package must be reviewed before send/submission.

## Troubleshooting

| Problem | Action |
|---|---|
| Model-not-found or authentication error | Check `ANTHROPIC_MODEL`/key in both Render dashboard and blueprint. |
| Scanned PDF appears blank | Try a clearer scan and verify the configured model supports document/image input. |
| PDF conversion fails | Continue with DOCX and inspect LibreOffice availability/logs. |
| Routing/review edit invalidates document | Regenerate the MSAPO. |
| No asset selected | Confirm the quote names a real tagged unit; otherwise retain no applicable asset. |
| Manual Smartsheet route absent | Configure the final HTTPS Smartsheet form URL. |
| URL prefill absent | Verify exact labels/value mappings, then explicitly enable it. |
| API schema blocked | Validate exact ID/title/type/options and writability in dry-run. |
| API result says outcome uncertain | Do not resubmit; follow exact-key reconciliation in the runbook. |
| API storage blocked | Restore the persistent disk/database; never use an in-memory fallback. |
