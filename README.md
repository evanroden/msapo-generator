# Process Control

Process Control provides two workflows in one Dockerized Streamlit application:

1. Purchase Order Process Control turns a vendor quote into a reviewed,
   prefilled Smartsheet request and a two-file supporting package.
2. Expense Report Process Control turns receipt images/PDFs into the official
   employee-reimbursement workbook, a combined PDF packet, and a ready-to-review
   email draft.

The repository retains its historical `msapo-generator` name. The PO workflow is
no longer an email generator; email-draft generation is used only by the
separately approved expense-reimbursement workflow. It **does** generate the
MSAPO form — as a PDF, restored 2026-08-12 at contract administration's request.

**Start with [`docs/README.md`](docs/README.md)** if you are picking this project
up. It orders every document, records which ones have been superseded and on
what narrow subject, and is pinned by `tests/test_docs_index.py` so it cannot
quietly fall behind the directory.

The authoritative business policy handoff is
[`docs/STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md`](docs/STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md).
Read that document before changing routing, field mappings, attachments, or the
Smartsheet handoff. The current three-step UI, brand-aligned alpha theme,
browser matrix, and release hardening are documented in
[`docs/RRH_UNIFIED_REVIEW_BRAND_BROWSER_HARDENING_2026-08-09.md`](docs/RRH_UNIFIED_REVIEW_BRAND_BROWSER_HARDENING_2026-08-09.md).
Earlier quick-path reliability history remains in
[`docs/RRH_STREAMLINING_AND_HARDENING_2026-08-08.md`](docs/RRH_STREAMLINING_AND_HARDENING_2026-08-08.md).
The verified 87-value job catalog and the Arkansas-versus-RRH Unity rule are in
[`docs/JOB_NUMBER_CATALOG_AND_UNITY_DISAMBIGUATION_2026-08-10.md`](docs/JOB_NUMBER_CATALOG_AND_UNITY_DISAMBIGUATION_2026-08-10.md).
The expense form mapping, receipt controls, AI boundary, failure modes, and
open policy questions are in
[`docs/EXPENSE_REIMBURSEMENT_WORKFLOW_2026-08-11.md`](docs/EXPENSE_REIMBURSEMENT_WORKFLOW_2026-08-11.md).
The commit-level architecture, invariants, failure matrix, test evidence, and
regression guidance for the attached Outlook/iOS expense-email handoff are in
[`docs/COMMIT_NOTES_2026-08-11_EXPENSE_EMAIL_ATTACHMENT_HANDOFF.md`](docs/COMMIT_NOTES_2026-08-11_EXPENSE_EMAIL_ATTACHMENT_HANDOFF.md).
The ready-to-send IT review email and exact AI call-path summary are in
[`docs/ENFRA_IT_AI_API_REVIEW_EMAIL_2026-08-11.md`](docs/ENFRA_IT_AI_API_REVIEW_EMAIL_2026-08-11.md).
The crawler-visible page title, favicon, Open Graph/Twitter card, build-time
patch, cache behavior, and production verification contract are documented in
[`docs/LINK_PREVIEW_METADATA_2026-08-11.md`](docs/LINK_PREVIEW_METADATA_2026-08-11.md).

## Purchase-order workflow

1. Choose Upload or Paste and provide one quote. The inactive source can never
   silently override the selected source.
2. Review one compact summary, enter or confirm the requester name, and answer
   only fields the tool could not determine. AI/defaulted values stay in a
   collapsed correction panel; unresolved fields stay visible and stable.
   Vendor representative name and email are required and are recalled from
   prior verified requests for the same account and vendor when available.
3. Press one button to render the MSAPO form to PDF and reveal both downloads
   plus the
   native new-tab Smartsheet link. Upload both files near the end of the form,
   review, and submit it manually.

There is no email-submission route in the active UI.

## Expense-reimbursement workflow

1. Choose **Expense reimbursement** in the top workflow switch and upload one
   image or PDF per receipt. Exact duplicate files are ignored. HEIC phone
   photos, screenshots, common image formats, and multi-page PDF receipts are
   supported without modifying the uploaded files. Receipt upload is optional
   for a mileage-only report.
2. Confirm the employee, report date, administrator, mail destination, and RRH
   service year. RRH derives Employee Home Business Unit `695` from the account
   and defaults the approval recipient from private deployment configuration.
   Confirmed employee numbers are recalled by employee name. Administrator
   names are searchable per account, and selecting one fills the remembered
   email without carrying contacts between accounts.
3. Review the editable merchant, transaction date, description/business
   purpose, reimbursable amount, and Miscellaneous/Entertainment selection below
   every receipt. Required values remain visible when AI cannot determine them.
   A receipt containing several reimbursable purposes can be split into
   independently editable lines; nonbusiness items are simply omitted, and the
   source receipt is attached only once.
   When the receipt itself lists multiple priced purchases, each detected item
   is selectable. Unchecking a personal/nonreimbursable item recalculates the
   amount and proportionally carries through receipt-level tax, tip, fees, or
   discounts; the calculated total remains editable.
   Job number, Account / Cost Type, and Cost Code appear under every receipt
   with the confirmed RRH defaults of `695400022`, `01AMA`, and `5490`;
   each remains editable. Service year 2 changes the Account / Cost Type default
   to `02AMA`, year 3 to `03AMA`, and so on.
4. Add up to eight mileage entries when needed. Each trip records date, miles,
   purpose, destination, and the same editable job coding. The travel date
   selects the applicable IRS business-mileage rate.
5. Confirm the generated cursive employee signature and printed name, then
   generate the editable `.xlsx`, submission `.pdf`, and email draft. Windows
   defaults to an Outlook `.eml` containing only the PDF; the same attached
   draft can be opened/imported in Outlook on the web. iPhone/iPad uses the
   browser share sheet to pass the PDF and message directly to Mail or Outlook.
   Excel, PDF, and the generic attachment-free fallback remain collapsed under
   **Other file and email options**.

The expense workflow uses only the Job or Service Center, Account / Cost Type,
and Cost Code columns (`I:K`). Work Order (`L`) and Other Expenses (`N:Q`) are
never populated and are rejected by validation.

The Smartsheet job-number description is converted to its exact numeric or `VI`
identifier in the JDE form. Leading zeros in every accounting code are preserved
as text. Rows are grouped by section and coding, and the appended receipt pages
follow that same order.

## Canonical classification matrix

| Fulfillment route | Object Account | Agreement Type |
|---|---|---|
| Vendor performs labor onsite | `5511-SUBCONTRACTOR` | `03 - MSAPO (SERVICE)` |
| Onsite rental service | `5411-OUTSIDE RENTALS` | `03 - MRAPO (RENTAL)` |
| Complete approved Group A equipment purchase; no labor/rental | `5302-EQUIPMENT` | `OR - EQUIPMENT PO` |
| Parts, supplies, consumables, or other non-Group-A purchase; no labor/rental | `5301-MATERIALS` | `< $25,000`: `ON - STANDARD PO UNDER $25K`; otherwise `OR - STANDARD PO OVER $25K` |

Labor and rentals take precedence. Delivery/drop-off versus third-party shipping
does not determine Equipment versus Materials. The live option is spelled
`MRAPO` for rental; CSAPO is represented for schema validation but is not selected
by this classification policy.

## Locked field rules

- Request Type is `PO` or `CHANGE ORDER`; a change order requires Original PO
  Number, while a new PO forces that field blank.
- Requester is the person filling out the current request. It is remembered only
  for the same anonymous device and account after a verified package.
- Dispatch WO to Service Center is always `NA`.
- Leave Request Completed, PO #, and Work Order # always remain blank.
- PO/CO Amount is the final payable amount including tax, freight, delivery,
  surcharges, and every other fee.
- Description of Work is capped at 20 characters during export.
- Asset ID is the complete configured site asset UID, with prefixes preserved.
- Job Number must be one of the 87 verified Smartsheet dropdown values. Values
  beginning `Unity` belong to Unity Health System in Arkansas; Rochester-area
  Unity facilities use RRH-prefixed job numbers.
- Additional Information is blank unless the operator enters a note; tax notes
  are not copied into it.

## Attachment package

Every route requires exactly two files:

1. The original quote, byte-for-byte unchanged when uploaded, or a TXT snapshot
   when the user supplied pasted quote text.
2. The MSAPO agreement form, populated with the reviewed Scope, Inclusions, and
   Exclusions and rendered to PDF.

The reviewed values are edited upstream in the web UI, so the form is delivered
as a PDF only — no DOCX is offered. This reverses the 2026-08-08 policy of
attaching a lightweight scope-only PDF; see
[`docs/COMMIT_NOTES_2026-08-12_MSAPO_FORM_RESTORED.md`](docs/COMMIT_NOTES_2026-08-12_MSAPO_FORM_RESTORED.md).
The custom URL can prefill fields but cannot place local files in Smartsheet's upload
control, so the user downloads both verified files and uploads them in the form.
On Windows, both downloaded files can be selected in File Explorer and dragged
together onto the form's attachment box.

## Project structure

```text
app/web_ui.py                 Active quote-to-Smartsheet workflow
app/quote_analyzer.py          Structured quote extraction
app/analysis_schema.py         Model-response validation
app/ocr.py                     PDF/image extraction and normalization
app/equipment_policy.py        Approved Group A equipment policy
app/asset_guess.py             Unique-best site asset suggestion
app/po_rules.py                Canonical route/account/agreement rules
app/document_generator.py      MSAPO form population and PDF build (LIVE)
app/pdf_converter.py           Headless LibreOffice DOCX/XLSX to PDF (LIVE)
app/ui_highlight.py            Transient highlighting of fields needing a value
app/scope_pdf.py               Scope-only PDF; dormant since 2026-08-12
app/po_context.py              Verified PO fields and two-file snapshot
app/smartsheet.py              Manual/prefill/API validation and adapters
app/smartsheet_inline.py       Two downloads, prefilled link, and hidden fallback
app/smartsheet_ui.py           Prefilled-link and copy controls
app/device_identity.py         Opaque first-party browser identity cookie
app/memory.py                  Contract and anonymous-browser learning
app/workflow_state.py          Active-source and stale-analysis state controls
app/workflow_review.py         Exception-only question and tax-alert rules
app/smartsheet_store.py        Leased/idempotent future API state
app/expense_ui.py              Receipt review and reimbursement workflow
app/receipt_analyzer.py        Structured receipt OCR/extraction
app/expense_report.py          JDE workbook, receipt sheet, and PDF packet
branding/                       Public favicon and social-preview sources/assets
scripts/patch_streamlit_metadata.py
                               Build-time crawler metadata installation
templates/Employee_Reimbursement_Expense_Report_JDE_10012025.xlsx
                               Supplied official reimbursement template
pages/2_Smartsheet_PO.py       Non-submitting legacy bookmark notice
docs/README.md                 Index of every document, reading order, and
                               what supersedes what
docs/STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md
                               Authoritative policy and successor handoff
docs/COMMIT_NOTES_*.md         Per-change engineering notes, newest first
tests/                         Pytest regression suite
```

`app/document_generator.py` and `app/pdf_converter.py` were dormant until
2026-08-12 and are now the live PO attachment path — do not treat them as
removable. `app/scope_pdf.py` took the opposite trip and is now reached only by
its own tests. `app/eml_builder.py` is used only to create the approved
expense-report draft; the PO workflow does not import or call it.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate      # Windows
python -m pip install -r requirements-dev.lock
cp .env.example .env
streamlit run run_web.py
```

`requirements.txt` and `requirements-dev.txt` declare the supported direct
dependencies. The fully resolved lock files drive local, CI, and production
installs so the same commit receives the same dependency set.

The discreet **Built by Evan Roden** control below the purchase-workflow header
loads a static synthetic quote for a safe end-to-end test. It contains no
customer/vendor data, makes no AI request, and does not submit the resulting
Smartsheet form.

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

Render runs one Docker web service on port 8501. The image includes LibreOffice
Calc so the completed workbook and receipt worksheet can be rendered as one
PDF. Production stores contract learning, anonymous-browser requester learning,
and guarded Smartsheet API state
on the persistent disk at `EPC_DATA_DIR=/test1`.

Render dashboard values override `render.yaml`. When form behavior differs from
the repository, compare `SMARTSHEET_FORM_URL`,
`SMARTSHEET_FORM_FIELD_MAP_JSON`, `SMARTSHEET_URL_PREFILL_ENABLED`, and
`SMARTSHEET_API_MODE` in both places.

## Input support

The PO UI accepts PDF, TXT, PNG, JPEG, WebP, TIFF/TIF, BMP, and HEIC/HEIF/HIF up
to 30 MB. Text PDFs are extracted locally. Scans and images use the configured
analysis path. The original uploaded bytes are retained for the attachment
package. File-reading and model failures expose explicit retry actions instead
of leaving an older analysis visible or retrying on every rerun.

The expense uploader accepts PDF and the same image formats, up to 15 MB per
receipt and 60 MB for the in-progress report. The official form holds 15
Miscellaneous and 14 Entertainment reimbursement lines; a single source
receipt may supply several lines but is attached only once. Generation blocks
with a split-report instruction rather than silently dropping overflow. A PDF
receipt may contain up to 10 pages. Receipt images embedded in output files are
bounded and compressed for email while the uploaded source remains unchanged.
Up to eight mileage rows are supported; the travel date selects the configured
IRS business rate and an unknown future rate blocks generation.

## Requester memory

The page uses a random opaque first-party browser cookie. The token is hashed
before SQLite storage and contains no requester, quote, vendor, price, or PO
data. After the first verified package, that browser remembers the latest
requester for that exact ENFRA account. Streamlit reruns do not increase the
count, account memories do not cross, and there is no Forget button in the
active flow. Blocked cookies disable only this convenience.

After a valid expense package is generated, the same browser/account pair also
remembers the reviewed employee name/number, administrator, and mail destination.
Employee Home Business Unit and baseline coding are derived from account policy.
It never persists receipt files, merchant names, transaction dates, descriptions,
amounts, or mileage. An in-progress draft is mirrored in the current Streamlit
session so switching workflows does not discard typed values; **Clear expense
report and start over** explicitly removes that session draft.

## Smartsheet modes

### Custom-URL handoff

Production uses exact visible field labels and percent-encoded values. The link
opens but does not submit the form. Empty locked fields are deliberately omitted.
The user should have Smartsheet opened or signed into in the same browser within
the last few hours. If values do not appear, sign back in and use the same link
again. Manual Copy controls are hidden inside a collapsed troubleshooting panel.

### Direct API

Direct row creation remains disabled. Do not enable it without a least-privilege
token, destination sheet ID, exact column IDs/titles/types/options, a dedicated
submission-key column, dry-run validation, and one controlled row-plus-two-files
acceptance test. The existing adapter is fail-closed and retains duplicate and
ambiguous-write controls for possible future use.

## Troubleshooting

| Problem | Action |
|---|---|
| Quote analysis is stale after a new upload | The current build clears it automatically. Use the visible file-reading or analysis retry action. |
| Route classification looks wrong | Recheck labor/rental precedence and the exact Group A list in `app/equipment_policy.py`; delivery method is not the deciding factor. |
| Standard PO tier is missing | Enter a valid all-in PO/CO Amount greater than zero. Every route now applies the same amount gate. |
| Asset contains letters | Expected: the complete configured asset UID is sent, including letters and separators. |
| Scope PDF became stale | Regenerate it after changing contract, site, vendor, Scope, Inclusions, or Exclusions. |
| Attachments are not in Smartsheet | Download both files and upload both near the end of the form; URL parameters cannot carry files. |
| Prefilled fields are blank | Sign back into/open Smartsheet, return to the tool, and use the same link again; then verify exact labels and `%20` encoding. |
| Requester is not remembered | Complete one ready package for the same account in the same browser and verify cookies are permitted. |
| API mode is blocked | Leave it disabled until the complete activation gate in the handoff document is satisfied. |
| A receipt could not be read | Use the visible retry once, then complete every required field beside that receipt manually. |
| Expense generation is blocked | Resolve the visible receipt, mileage, coding, and signature-confirmation fields; the official form also requires a total over $20.00. |
| A future mileage date is blocked | Add the newly published IRS business rate to the dated rate table; the tool never carries an old rate into an unknown period. |
| Combined expense PDF is unavailable | Download the completed Excel workbook for edits. The Outlook approval draft remains withheld until the submission PDF can be generated. |
| iPhone/iPad share button is unavailable | Switch to an Outlook destination, or open **Other file and email options** for the attachment-free fallback and combined PDF. Supported iOS/iPadOS browsers receive the PDF directly through the system share sheet. |

## Security cautions

- Quotes can contain pricing, contacts, facility, and asset information.
- Receipts can contain employee, location, purchase, payment, and customer
  information. Image/PDF receipts are sent to the configured AI analysis
  endpoint; generated artifacts remain in the user's active session.
- Do not commit API keys, service tokens, production credentials, or real quotes.
- Do not commit real receipts or generated employee expense reports.
- Review every prefilled PO form and both PO attachments before submission.
- Review every expense form and its submission PDF before emailing it.
- Review every extracted receipt value and the generated employee signature.
  Signature confirmation is required before the report and email draft are built.
- Do not add an automatic submit action to the custom-URL route.
- Migrate SQLite state to a shared transactional database before running more
  than one application instance.
