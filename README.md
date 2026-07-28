# Email Process Control

Email Process Control turns a vendor quote into a reviewed MSAPO scope package and a ready-to-send purchase-order email. It is a Streamlit application deployed as a single Docker service on Render.

The repository retains its original `msapo-generator` name, but the current product is a quote-to-email workflow rather than a standalone document generator.

## Current workflow

1. Select standard MSAPO or Equipment-only PO mode.
2. Upload a PDF, image, or text file, or paste quote text.
3. Extract the quote text. Text-layer PDFs use PyMuPDF; scans and images fall back to Claude vision.
4. Analyze the quote with Claude to identify the vendor, facility, scope, inclusions, exclusions, tax, pricing, contact, work category, and any specific asset tag.
5. Review the extracted scope and choose which inclusion and exclusion items belong in the document.
6. Generate the MSAPO DOCX and, when LibreOffice conversion succeeds, a PDF.
7. Confirm the ENFRA contract, site, cost code, asset, administrator, contact, description, and pricing.
8. Open a ready-to-send Outlook draft on desktop or use the Apple Mail share flow on iPhone or iPad.
9. Explicitly record a completed send so frequently used contract-specific contacts can be suggested later.

Equipment-only POs skip MSAPO generation and attach the original quote only.

## Core behavior

- **All contracts receive MSAPO documents when the order is not equipment-only.** Do not gate document generation to RRH.
- **RRH retains its dedicated flow:** known sites, site/category cost-code derivation, David as administrator, and the 246-asset RRH registry.
- **Other ENFRA contracts use the project-agnostic registry:** contract-specific sites and assets, free-text cost codes, and contract-specific administrators.
- **Contract memory is isolated.** Data learned for one contract is never suggested for another.
- **Asset matching is conservative.** A specific tag must resolve to a real asset at the selected site; otherwise the interface defaults to `None Applicable`.
- **The original quote is preserved byte-for-byte** and attached to the outgoing draft or future Smartsheet handoff.
- **Prices are excluded from the generated Scope of Work** but retained in the email and submission fields.
- **Generated files are transient.** Unique internal filenames prevent concurrent sessions from overwriting one another, and files older than 24 hours are removed.
- **The app does not send email from the server.** It prepares a client-side Outlook or Apple Mail draft for the user to review and send.

## Project structure

```text
msapo-generator/
├── app/
│   ├── web_ui.py              # Current Streamlit quote/email workflow
│   ├── quote_analyzer.py      # Claude structured quote extraction
│   ├── analysis_schema.py     # Claude response validation
│   ├── ocr.py                 # PDF/image text extraction and OCR fallback
│   ├── document_generator.py  # MSAPO template mutation and DOCX generation
│   ├── pdf_converter.py       # DOCX-to-PDF conversion
│   ├── eml_builder.py         # Outlook .eml and Apple Mail body construction
│   ├── config.py              # RRH facilities, cost codes, and environment settings
│   ├── assets.py              # RRH asset registry
│   ├── contracts.py           # Non-RRH contract/site/asset access and matching
│   ├── memory.py              # Per-contract SQLite learning
│   ├── po_context.py          # Shared finalized PO snapshot
│   ├── smartsheet.py          # Manual, URL-prefill, and API Smartsheet routes
│   ├── smartsheet_store.py    # Persistent API idempotency state
│   ├── smartsheet_ui.py       # Mobile-friendly manual copy assistant
│   └── data/
│       └── contracts.json     # Non-RRH contract registry
├── pages/
│   └── 2_Smartsheet_PO.py     # Future Smartsheet handoff page
├── templates/
│   └── Master_MSAPO_Template.docx
├── tests/                     # Pytest regression tests
├── run_web.py                 # Production entry point
├── requirements.txt
├── requirements-dev.txt
├── Dockerfile
└── render.yaml
```

## Template behavior

The application does **not** use `{{TAG}}` placeholder replacement.

`app/document_generator.py` opens `templates/Master_MSAPO_Template.docx`, verifies that it contains the sentinel paragraph:

```text
Subcontractor shall execute the following Scope of Work in strict accordance with this MSAPO:
```

It preserves the template and appends the reviewed facility, vendor, project description, detailed scope, inclusions, exclusions, and tax warning/status. It also clears the pre-filled Included mark and date from the first exhibit row.

The legal and branding applicability of the current template across all ENFRA contracts must be confirmed by the business owner before wider rollout.

## Local development

### Prerequisites

- Python 3.12 recommended
- An Anthropic API key
- LibreOffice Writer for production-equivalent PDF conversion

### Install

```bash
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate      # Windows
python -m pip install -r requirements-dev.txt
```

### Configure

Copy `.env.example` to `.env` and set at least:

```text
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-sonnet-4-6
PDF_BACKEND=libreoffice
```

### Run

```bash
streamlit run run_web.py
```

The local application is available on port 8501 by default. Streamlit exposes the Smartsheet handoff as a second page in the same application, so both pages share session state.

### Test

```bash
python -m pytest -q
```

Pull requests and pushes to `main` run the same suite through GitHub Actions.

## Deployment

Render runs the repository as one Docker web service:

- Dockerfile: `./Dockerfile`
- Port: `8501`
- Command: `streamlit run run_web.py`
- PDF backend: LibreOffice
- Persistent state directory: `/test1`, configured through `EPC_DATA_DIR`

Environment variables represented in `render.yaml`:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `PDF_BACKEND`
- `EPC_DATA_DIR`
- `SMARTSHEET_URL_PREFILL_ENABLED` — defaults to `false`
- `SMARTSHEET_API_MODE` — defaults to `disabled`
- `SMARTSHEET_FORM_URL` — unset until the final form exists
- `SMARTSHEET_API_TOKEN` — unset secret
- `SMARTSHEET_SHEET_ID` — unset until the final sheet exists

Render dashboard values can override blueprint values. When a model, credential, or Smartsheet change appears ineffective after deployment, check both `render.yaml` and the service's dashboard environment.

The application currently uses SQLite on the Render persistent disk for learned contacts and Smartsheet duplicate-prevention state. This is suitable only for a single application instance. Scaling to multiple instances requires a shared database.

## PDF conversion

The supported converter implementations are:

- `libreoffice` — production/default on Render
- `gotenberg` — optional HTTP service
- `docx2pdf` — optional local Windows/macOS path requiring Microsoft Word

A PDF conversion error does not discard the DOCX. The interface warns the user and continues with the DOCX attachment.

## Input support

The UI accepts:

- PDF
- TXT
- PNG
- JPG/JPEG
- WebP
- TIFF/TIF
- BMP
- HEIC/HEIF/HIF

Text PDFs are extracted locally. Scanned PDFs and Claude-native image formats are sent directly to vision. TIFF, BMP, and iPhone HEIC/HEIF uploads are decoded in memory and converted to ordered PNG image blocks for analysis; the original uploaded file remains unchanged for attachment.

## Security and operational cautions

- Vendor quotes may contain pricing, contact, facility, and asset information and are sent to Anthropic for analysis when OCR or extraction is required.
- The codebase does not currently implement application authentication. Confirm Render access controls before sharing the service broadly.
- SQLite stores administrator/vendor contacts and Smartsheet submission fingerprints, row IDs, attachment fingerprints, status, and error text.
- Do not place API keys, Smartsheet tokens, exact production column maps, or real credentials in the repository.
- The original quote is attached unchanged; generated documents and submission values should always be reviewed.

## Smartsheet transition

The future handoff is available as a separate Streamlit page and supports three independently configurable routes. All are inert until configured.

### 1. Manual copy/paste

Set `SMARTSHEET_FORM_URL`. The page opens the form, displays every populated PO value in configurable form order, provides one-tap copy controls with progress tracking, and downloads the quote/DOCX/PDF with adjacent filenames. This route requires no API token.

### 2. Exact-label URL prefill

After testing the final form, set:

- `SMARTSHEET_URL_PREFILL_ENABLED=true`
- `SMARTSHEET_FORM_FIELD_MAP_JSON` with logical field names mapped to the form's exact visible labels
- optionally `SMARTSHEET_FORM_VALUE_MAP_JSON` for dropdown/radio option translation

The generated link pre-populates mapped values. Attachments must still be added through the form's file field. Prefill remains disabled until exact labels are supplied; the application never guesses form parameter names.

### 3. Direct API submission

Configure the token, sheet ID, explicit numeric column IDs, and confirmed required fields. Use `SMARTSHEET_API_MODE=dry_run` first to validate credentials and column IDs, then change it to `live` only after a production-like test.

API safety rules:

- no fuzzy title matching;
- required fields and column IDs must be explicit;
- submissions use a deterministic field-and-attachment fingerprint;
- the persistent SQLite store prevents duplicate rows across reruns or reopened browsers;
- partial attachment failures resume the existing row rather than creating another;
- API submission fails closed if duplicate-prevention storage is unavailable;
- files larger than 30 MB are blocked before upload.

The example ENFRA work-order form informs the field model, but its URL, labels, dropdown values, and required fields are not treated as the final PO configuration.

## Troubleshooting

| Problem | Action |
|---|---|
| Analysis returns a model-not-found error | Check `ANTHROPIC_MODEL` in both Render dashboard settings and `render.yaml`. |
| A scanned PDF appears blank | Confirm the API key and model support PDF/image input; try a clearer scan. |
| PDF conversion fails | Use the DOCX attachment and inspect LibreOffice logs/path availability. |
| A routing change invalidates the document | Regenerate the MSAPO so the attachment reflects the final contract, site, inclusions, and exclusions. |
| No asset is selected | Confirm the quote names a specific unit tag and that it exists at the selected site; otherwise keep `None Applicable`. |
| Learned contacts do not appear | Confirm the Render persistent disk is mounted at `EPC_DATA_DIR` and that the same entry has reached the suggestion threshold. |
| Manual Smartsheet mode is absent | Set `SMARTSHEET_FORM_URL` to the final PO form URL. |
| URL prefill is absent | Verify the exact form labels, set the field-map JSON, and explicitly enable URL prefilling. |
| API mode is blocked | Validate token access, sheet ID, explicit column IDs, required fields, and the persistent `/test1` disk. |
