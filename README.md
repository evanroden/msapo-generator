# Purchase Order Process Control

Purchase Order Process Control turns a vendor quote into a reviewed, prefilled
Smartsheet PO request and a two-file supporting package. It is a Dockerized
Streamlit application deployed on Render. The repository retains its historical
`msapo-generator` name, but the active product is no longer an email or MSAPO
document generator.

The authoritative business and implementation handoff is
[`docs/PO_WORKFLOW_POLICY_AND_ATTACHMENT_HANDOFF_2026-08-06.md`](docs/PO_WORKFLOW_POLICY_AND_ATTACHMENT_HANDOFF_2026-08-06.md).
Read that document before changing routing, field mappings, attachments, or the
Smartsheet handoff.

## Current workflow

1. Upload a PDF/image/text quote or paste quote text.
2. Extract and review the vendor, site, amount, Scope, Inclusions, and Exclusions.
3. Explicitly choose how the vendor will fulfill the order.
4. Confirm contract, site, cost code, numeric asset ID, vendor contact, and the
   all-in amount including taxes and every fee.
5. Generate one simple Scope/Inclusions/Exclusions PDF.
6. Prepare the Smartsheet handoff inline on the same page.
7. Confirm the requester—the person currently filling out the request—and the
   exact job/site values.
8. Download the unchanged original quote and generated PDF.
9. Open the custom prefilled Smartsheet URL, upload both files, review, and submit.

There is no email-submission route in the active UI.

## Canonical classification matrix

| Fulfillment route | Object Account | Agreement Type |
|---|---|---|
| Vendor performs labor onsite | `5511-SUBCONTRACTOR` | `03 - MSAPO (SERVICE)` |
| Onsite rental service | `5411-OUTSIDE RENTALS` | `03 - MRAPO (RENTAL)` |
| Vendor only delivers/drops off onsite; no labor | `5301-MATERIALS` | `< $25,000`: `ON - STANDARD PO UNDER $25K`; otherwise `OR - STANDARD PO OVER $25K` |
| Third-party shipping; vendor never onsite; no labor | `5302-EQUIPMENT` | `OR - EQUIPMENT PO` |

The live Smartsheet option is spelled `MRAPO` for rental even though people may
say “MSAPO rental.” CSAPO is intentionally not selected by this tool.

## Locked field rules

- Request Type is always `PO`.
- Requester is always the person filling out the current request. It is never
  sourced from a deployment-wide default.
- Dispatch WO to Service Center is always `NA`.
- Leave Request Completed, PO #, Work Order #, and Original PO Number always
  remain blank. They are omitted from custom-URL prefilling and API cell writes.
- PO/CO Amount is the final payable amount including tax, freight, delivery,
  surcharges, and every other fee.
- Asset ID contains numbers only; displayed letter prefixes are removed.

## Attachment package

Every route requires exactly two files:

1. The original quote, byte-for-byte unchanged when uploaded, or a TXT snapshot
   when the user supplied pasted quote text.
2. One generated PDF containing Scope, Inclusions, and Exclusions.

The active workflow does not generate or request the old MSAPO DOCX/form. The
custom URL can prefill fields but cannot place local files in Smartsheet's upload
control, so the user downloads both verified files and uploads them in the form.

## Project structure

```text
app/web_ui.py                 Active quote-to-Smartsheet workflow
app/quote_analyzer.py          Structured quote extraction
app/analysis_schema.py         Model-response validation
app/ocr.py                     PDF/image extraction and normalization
app/po_rules.py                Canonical route/account/agreement rules
app/scope_pdf.py               Lightweight supporting PDF generation
app/po_context.py              Verified PO fields and two-file snapshot
app/smartsheet.py              Manual/prefill/API validation and adapters
app/smartsheet_inline.py       Mobile-safe inline handoff and requester entry
app/smartsheet_ui.py           Prefilled-link and copy controls
app/device_identity.py         Opaque first-party browser identity cookie
app/memory.py                  Contract and anonymous-browser learning
app/smartsheet_store.py        Leased/idempotent future API state
pages/2_Smartsheet_PO.py       Non-submitting legacy bookmark notice
docs/PO_WORKFLOW_POLICY_AND_ATTACHMENT_HANDOFF_2026-08-06.md
                               Authoritative policy and successor handoff
tests/                         Pytest regression suite
```

`app/document_generator.py`, `app/pdf_converter.py`, and `app/eml_builder.py`
remain only as dormant historical compatibility modules. The active UI does not
import or call them. Do not reconnect them without a new approved business
requirement.

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

Pull requests and pushes to `main` run the same suite in GitHub Actions.

## Deployment

Render runs one Docker web service on port 8501. Production stores contract
learning, anonymous-browser requester learning, and guarded Smartsheet API state
on the persistent disk at `EPC_DATA_DIR=/test1`.

Render dashboard values override `render.yaml`. When form behavior differs from
the repository, compare `SMARTSHEET_FORM_URL`,
`SMARTSHEET_FORM_FIELD_MAP_JSON`, `SMARTSHEET_URL_PREFILL_ENABLED`, and
`SMARTSHEET_API_MODE` in both places.

## Input support

The UI accepts PDF, TXT, PNG, JPEG, WebP, TIFF/TIF, BMP, and HEIC/HEIF/HIF.
Text PDFs are extracted locally. Scans and images use the configured analysis
path. The original uploaded bytes are retained for the attachment package.

## Requester memory

The page uses a random opaque first-party browser cookie. The token is hashed
before SQLite storage and contains no requester, quote, vendor, price, or PO
data. After the same requester is used on three distinct verified PO contexts,
that browser suggests the name. Streamlit reruns do not increase the count, and
shared devices can forget the requester. Blocked cookies disable only this
convenience.

## Smartsheet modes

### Custom-URL handoff

Production uses exact visible field labels and percent-encoded values. The link
opens but does not submit the form. Empty locked fields are deliberately omitted.
Any field that cannot fit safely in the URL remains available through a Copy
control.

### Direct API

Direct row creation remains disabled. Do not enable it without a least-privilege
token, destination sheet ID, exact column IDs/titles/types/options, a dedicated
submission-key column, dry-run validation, and one controlled row-plus-two-files
acceptance test. The existing adapter is fail-closed and retains duplicate and
ambiguous-write controls for possible future use.

## Troubleshooting

| Problem | Action |
|---|---|
| Quote analysis is stale after a new upload | Re-analyze the current quote; the handoff blocks mismatched fingerprints. |
| Route classification looks wrong | Recheck the four route definitions in `app/po_rules.py`; do not infer from “comes onsite” alone. |
| Standard PO tier is missing | Enter and confirm a valid all-in PO/CO Amount. |
| Asset contains letters | Confirm the selected registry asset; only its numeric identifier is sent. |
| Scope PDF became stale | Regenerate it after changing contract, site, Inclusions, or Exclusions. |
| Attachments are not in Smartsheet | Download both files from the handoff and upload them to the form; URL parameters cannot carry files. |
| Prefilled fields are blank | Compare exact form labels and the `%20` URL encoding with production environment values. |
| Requester is not remembered | Prepare three distinct PO contexts in the same browser and verify cookies are permitted. |
| API mode is blocked | Leave it disabled until the complete activation gate in the handoff document is satisfied. |

## Security cautions

- Quotes can contain pricing, contacts, facility, and asset information.
- Do not commit API keys, service tokens, production credentials, or real quotes.
- Review every prefilled form and both attachments before submission.
- Do not add an automatic submit action to the custom-URL route.
- Migrate SQLite state to a shared transactional database before running more
  than one application instance.
