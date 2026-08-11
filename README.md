# Process Control

Process Control provides two workflows in one Dockerized Streamlit application:

1. Purchase Order Process Control turns a vendor quote into a reviewed,
   prefilled Smartsheet request and a two-file supporting package.
2. Expense Report Process Control turns receipt images/PDFs into the official
   employee-reimbursement workbook, a combined PDF packet, and a ready-to-review
   email draft.

The repository retains its historical `msapo-generator` name. The PO workflow
is no longer an email or MSAPO document generator; email-draft generation is
used only by the separately approved expense-reimbursement workflow.

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

## Purchase-order workflow

1. Choose Upload or Paste and provide one quote. The inactive source can never
   silently override the selected source.
2. Review one compact summary, enter or confirm the requester name, and answer
   only fields the tool could not determine. AI/defaulted values stay in a
   collapsed correction panel; unresolved fields stay visible and stable.
   Vendor representative name and email are required and are recalled from
   prior verified requests for the same account and vendor when available.
3. Press one button to create the scope PDF and reveal both downloads plus the
   native new-tab Smartsheet link. Upload both files near the end of the form,
   review, and submit it manually.

There is no email-submission route in the active UI.

## Expense-reimbursement workflow

1. Choose **Expense reimbursement** in the top workflow switch and upload one
   image or PDF per receipt. Exact duplicate files are ignored. HEIC phone
   photos, screenshots, common image formats, and multi-page PDF receipts are
   supported without modifying the uploaded files.
2. Confirm employee number, Employee Home Business Unit, report date, administrator, mail
   destination, and one default JDE allocation. RRH defaults to David Siegal;
   other accounts remain blank until reviewed. The examples are not treated as
   accounting policy: a home address is not accepted as the Employee Home
   Business Unit.
3. Review the editable merchant, transaction date, description/business
   purpose, reimbursable amount, and Miscellaneous/Entertainment selection below
   every receipt. Required values remain visible when AI cannot determine them.
   Every receipt uses the report-level coding unless its explicit override is
   enabled.
4. Generate three artifacts from one action: the official `.xlsx` workbook with
   a printable `RECEIPTS` worksheet, one `.pdf` with the form first and receipt
   pages afterward, and an Outlook `.eml` draft with the generated files
   attached. A `mailto:` fallback is provided for iPhone/iPad and webmail; it
   cannot carry attachments.

The report supports all three allocation layouts in the supplied JDE form:

| Allocation | Required coding | Workbook columns |
|---|---|---|
| Job expense | Verified job number, account/cost type, cost code | Job/Service Center, Account/Cost Type, Cost Code |
| Work-order expense | Service center, account/cost type, WO type, work-order number | Job/Service Center, Account/Cost Type, Cost Code/WO Type, Work Order # |
| Overhead/other | Company, department, OU, GL account | Other Expenses columns |

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
2. One generated PDF containing Scope, Inclusions, and Exclusions.

The active workflow does not generate or request the old MSAPO DOCX/form. The
custom URL can prefill fields but cannot place local files in Smartsheet's upload
control, so the user downloads both verified files and uploads them in the form.
On Windows, both downloaded files can be selected in File Explorer and dragged
together onto the form's attachment box.

## Project structure

```text
app/web_ui.py                 Active quote-to-Smartsheet workflow
app/quote_analyzer.py          Structured quote extraction
app/analysis_schema.py         Model-response validation
app/ocr.py                     PDF/image extraction and normalization
app/equipment_policy.py        Ashley's exact Group A equipment policy
app/asset_guess.py             Unique-best site asset suggestion
app/po_rules.py                Canonical route/account/agreement rules
app/scope_pdf.py               Lightweight supporting PDF generation
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
templates/Employee_Reimbursement_Expense_Report_JDE_10012025.xlsx
                               Supplied official reimbursement template
pages/2_Smartsheet_PO.py       Non-submitting legacy bookmark notice
docs/STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md
                               Authoritative policy and successor handoff
docs/RRH_STREAMLINING_AND_HARDENING_2026-08-08.md
                               Quick-path and reliability hardening notes
docs/RRH_UNIFIED_REVIEW_BRAND_BROWSER_HARDENING_2026-08-09.md
                               Current UI, brand, browser, and release notes
tests/                         Pytest regression suite
```

`app/document_generator.py` and `app/pdf_converter.py` remain dormant historical
compatibility modules. `app/eml_builder.py` is used only to create the approved
expense-report draft; the PO workflow does not import or call it.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate      # Windows
python -m pip install -r requirements-dev.txt
cp .env.example .env
streamlit run run_web.py
```

Synthetic quote data is disabled by default. For a controlled local test only,
set `EPC_ENABLE_SYNTHETIC_SAMPLE=true`; production must leave it false.

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
Miscellaneous and 14 Entertainment rows; generation blocks with a split-report
instruction rather than silently dropping overflow. A PDF receipt may contain
up to 10 pages. Receipt images embedded in output files are bounded and
compressed for email while the uploaded source remains unchanged.

## Requester memory

The page uses a random opaque first-party browser cookie. The token is hashed
before SQLite storage and contains no requester, quote, vendor, price, or PO
data. After the first verified package, that browser remembers the latest
requester for that exact ENFRA account. Streamlit reruns do not increase the
count, account memories do not cross, and there is no Forget button in the
active flow. Blocked cookies disable only this convenience.

After a valid expense package is generated, the same browser/account pair also
remembers the reviewed employee name/number, Employee Home Business Unit,
administrator, mail destination, and default JDE allocation. It never persists receipt files,
merchant names, transaction dates, descriptions, or amounts. An in-progress
draft is mirrored in the current Streamlit session so switching workflows does
not discard typed values; **Clear receipts and start over** explicitly removes
that session draft.

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
| Expense generation is blocked | Resolve the visible receipt/profile/coding fields; the official form also requires a total over $20.00. |
| Combined expense PDF is unavailable | Download the completed Excel workbook; it still contains the form and all receipt pages. Restore LibreOffice/Gotenberg before relying on the PDF. |
| iPhone/iPad email has no attachments | Expected for `mailto:`. Download the Excel/PDF files, open the mobile email draft, and attach the files manually. |

## Security cautions

- Quotes can contain pricing, contacts, facility, and asset information.
- Receipts can contain employee, location, purchase, payment, and customer
  information. Image/PDF receipts are sent to the configured AI analysis
  endpoint; generated artifacts remain in the user's active session.
- Do not commit API keys, service tokens, production credentials, or real quotes.
- Do not commit real receipts or generated employee expense reports.
- Review every prefilled form and both attachments before submission.
- Review every extracted receipt value and complete the employee signature only
  outside the generator; the tool never creates or copies a signature.
- Do not add an automatic submit action to the custom-URL route.
- Migrate SQLite state to a shared transactional database before running more
  than one application instance.
