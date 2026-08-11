# Expense reimbursement workflow handoff

**Feature commit:** `2504c23` — `Add employee expense report workflow`  
**Documentation commit:** this handoff's repository commit  
**Date:** 2026-08-11  
**Source template:** `Employee Reimbursement Expense Report _JDE_10012025.xlsx`  
**Source-template SHA-256:** `9bc532c2d55b0600450d51e23eb1517c243ece614722aa8365b5879a8920bc33`

## Outcome

The application now has a top-level **Purchase order / Expense reimbursement**
switch. The expense path replaces the manual sequence of copying an old Excel
file, reading receipts, placing values in JDE columns, combining receipt pages,
and composing an approval email.

One generation action creates:

1. The official `.xlsx` form with reviewed values and a printable `RECEIPTS`
   worksheet when receipts are present. This remains available for edits.
2. A single `.pdf` packet with the official form first and each receipt page
   afterward.
3. An Outlook `.eml` approval draft addressed to the reviewed administrator,
   with only the submission PDF attached.
4. A `mailto:` fallback for iPhone/iPad, Outlook web, and other mail clients.
   `mailto:` cannot include local attachments, so the UI directs the employee
   to attach the generated PDF manually.

The tool prepares a draft. It does not email, approve, sign, reimburse, or post
anything to JDE.

## Evidence used and decisions made

The supplied files represented three different stages:

- The three `Employee Reimbursement Expense Report _JDE_10012025*.xlsx` files
  are byte-identical blank templates.
- `2026.03.19 Expense Report 2.xlsx` is a completed workbook example.
- `May Expenses.pdf` is a one-page rendering of a completed form.
- `Evan Roden Expenses.pdf` is a 16-page packet: the completed form followed by
  15 receipt pages.
- `Employee Reimbursement Expense Report - JDE - Dane 27JUL26.pdf` is the RRH
  approved-reference report: signed form first, one receipt second, job-only
  coding, and a receipt reimbursement smaller than the full receipt total.
- Dane confirmed that the submitted artifact is the PDF. Excel remains useful
  only as an editable download and is not attached to the approval email.

The earlier completed examples remain non-authoritative where Dane's approved
RRH report or a later product-owner direction conflicts with them. RRH now
derives Employee Home Business Unit from the account instead of asking the
employee to type it.

The form itself is the authority for layout, row capacity, formulas, and JDE
column placement. Business-policy values that were not provided—such as a full
expense account/cost-type catalog—were not invented.

## User interaction order

### 1. Upload receipts

- Upload one image or PDF per receipt.
- Supported: PDF, PNG, JPEG, WebP, TIFF, BMP, HEIC/HEIF/HIF.
- Per-file limit: 15 MB.
- In-progress report upload limit: 60 MB.
- Exact duplicate bytes are ignored and named in a warning.
- Removed/changed receipt sets invalidate generated artifacts.
- Original uploaded bytes remain unchanged.
- A non-widget receipt mirror preserves the in-progress upload set if the user
  briefly switches to the purchase-order workflow.
- Receipt upload is optional for a mileage-only report.

### 2. Confirm report details and default coding

Required report values:

- Account / contract
- Employee name
- Employee number
- Report date
- Contract administrator name and email
- Mail destination; satellite office becomes required when selected

For RRH, Employee Home Business Unit is derived from the account, and David
Siegal at the existing configured address is the default administrator. A
different reviewed administrator can still be entered.

RRH service year controls the cost-code default: `01AMA` for year 1, `02AMA`
for year 2, `03AMA` for year 3, and so on.

### 3. Review each receipt

The receipt image and editable fields remain together. The tool attempts to
extract:

- Merchant
- Transaction date
- Final charged amount
- Separately printed tax, for review only
- Currency
- Short receipt-based description
- Miscellaneous versus Entertainment suggestion
- Confidence and ambiguity notes

It does not infer accounting codes, job numbers, attendees, or a business
purpose that the receipt cannot support. If automatic reading fails, blank
required fields stay visible beside the receipt; they are never relabeled as
optional or moved into a hidden panel.

Job number, cost type, and cost code appear directly under every receipt. RRH
starts with `695400022`, `5490`, and the service-year `AMA` code. All three are
editable for that receipt; `695400023` is the usual Startup alternative.

Entertainment requires a contact name. Miscellaneous is the conservative
default because the supplied completed packet placed ordinary employee travel
meals in Miscellaneous.

### 4. Add mileage when applicable

Mileage is optional and supports up to eight form rows. Each entry collects:

- Travel date
- Business miles
- Business purpose
- Destination
- Editable job number, cost type, and cost code

The travel date selects the IRS business rate. The dated table uses `$0.725`
through June 30, 2026 and `$0.76` beginning July 1, 2026. Unknown future dates
block instead of silently reusing an expired rate.

### 5. Confirm signature, generate, and open the approval draft

The page renders the employee name in a cursive signature preview and displays
the printed name beneath it. Generation remains disabled until the employee
confirms that signature and agrees to review it again before sending. The
signature, printed name, and report date are then placed on the form.

The page exposes the editable Excel file, submission PDF, Outlook draft, and
mail-client fallback. The `.eml` contains the PDF only. Any edit changes the
content fingerprint and suppresses stale downloads until regeneration.

## JDE allocation rules

The RRH workflow uses one allocation route:

| Required UI field | Form column |
|---|---|
| Job / Service Center | `I` |
| Account / Cost Type | `J` |
| Cost Code | `K` |

Work Order (`L`) and Other Expenses (`N:Q`) are never populated. The data model
rejects those routes even if a stale session or direct function call attempts to
use them.

Job choices reuse the exact 87-value Smartsheet catalog. The descriptive label
is never copied into the numeric JDE column; `job_number_identifier()` extracts
the catalog's exact `695…` or `VI…` identifier. This also retains the explicit
Unity rule:

- `Unity …` options are Unity Health System in Arkansas.
- Rochester Unity Hospital and Unity Specialty Hospital use `RRH-…` options.

Every code is written as text so leading zeros survive Excel/LibreOffice.

The workbook groups rows by form section and complete coding tuple, as directed
by the template's “Group by job number and code” note. Receipt pages follow the
same order so the packet remains auditable.

## Exact workbook mapping

### Header and payment routing

| Value | Cell |
|---|---|
| Employee name | `C5` |
| Employee number | `G5` |
| Employee Home Business Unit | `K5` |
| Report date | `P5` |
| Mail home selection | `B62` |
| Mail satellite selection | `B64` |
| Satellite office | `F64` |
| Cursive employee signature | image anchored at `C66` |
| Submitted date | `D66` |
| Employee printed name | `C68` |

The approver signature and printed-name lines remain blank. The employee
signature is generated only after an explicit confirmation tied to the current
employee name; changing the name clears the confirmation.

### Mileage rows

- Mileage rows: 10–17, maximum 8 entries.
- `B`: travel date; `C`: purpose; `F`: destination; `G`: miles.
- `H`: rounded `miles × dated IRS rate` formula.
- `I:K`: job, cost type, and cost code.
- Mileage total: `H18 = SUM(H10:H17)`.

### Expense rows and totals

- Miscellaneous rows: 24–38, maximum 15 receipts.
- Entertainment rows: 45–58, maximum 14 receipts.
- Miscellaneous total: `H39 = SUM(H24:H38)`.
- Entertainment total: `H59 = SUM(H45:H58)`.
- Total reimbursement: `Q60 = H18+H39+H59`.
- Workbook calculation mode is set to automatic/full recalculation.

The form title and mileage heading are refreshed from the report year and the
applicable dated rate rather than retaining the original October 2025 template
text. When mileage rows span multiple rate periods, the heading says
`APPLICABLE IRS RATE` and each row uses its own travel-date rate.

## Receipt attachment rendering

- Each image frame or PDF page becomes a separate printed page in `RECEIPTS`.
- A receipt PDF may contain up to 10 pages.
- Each page gets a header with receipt number, date, merchant, amount, and source
  filename.
- Images are EXIF-rotated, converted to RGB, bounded to 1200×1600, and encoded
  as quality-78 JPEG for legibility and mail size.
- Images over 40 million decoded pixels are rejected before workbook insertion.
- Multi-page attachments receive manual row page breaks and Letter/portrait
  print settings.
- The PDF renderer uses an isolated LibreOffice user profile per generation to
  prevent cross-session profile locks.

If LibreOffice/Gotenberg fails, the official Excel workbook still succeeds and
the page explains that the PDF was unavailable. The email draft then contains
the workbook rather than crashing or requiring re-entry.

## Receipt-analysis request

`app/receipt_analyzer.py` is the only new AI call path. It sends the image or PDF
to the configured model and requests JSON with these keys:

```text
merchant_name
transaction_date
total_amount
tax_amount
currency
suggested_description
expense_section_guess
confidence
review_notes
```

For images, the code first creates a bounded, orientation-corrected JPEG. PDFs
are sent as document blocks. Malformed JSON is re-rolled once; transient
429/5xx/529 errors use bounded retries. A failed or unavailable integration
degrades to required manual fields.

The analyzer is instructed to select the final paid/charged total—including
charged tax and tip—not subtotal, change due, loyalty points, a suggested tip,
or an unpaid balance. Parser validation rejects arbitrary text that merely
contains digits. Dane's approved example reimburses only one business line item
from a larger receipt, so the UI explicitly tells the employee to replace the
prefill with only the business-reimbursable portion when appropriate.

## Memory and privacy boundary

After a valid package, SQLite stores only the latest profile for the exact
hashed-browser-token/account pair:

- Employee name and number
- Administrator name and email
- Mail destination/satellite office

Employee Home Business Unit and RRH baseline coding come from account policy,
not another employee's remembered transaction. Legacy allocation columns remain
in the SQLite table for backward-compatible schema reads, but the active RRH UI
does not use them to override the approved defaults.

It does not persist:

- Receipt bytes or previews
- Merchant
- Transaction date
- Description/business purpose
- Amount or tax
- Mileage entries
- Signature image or confirmation
- Generated workbook, PDF, or email draft

Changing accounts or browsers cannot surface another profile. Blocked cookies
disable only the memory convenience.

## Failure modes and controls

| Failure mode | Control |
|---|---|
| AI cannot read a receipt | Error is cached instead of retried on every rerun; required manual fields remain visible; explicit retry is available. |
| Same file uploaded twice | Exact SHA-256 duplicate is ignored. |
| Cropped/re-encoded duplicate | Same merchant/date/amount produces a non-blocking confirmation warning; it is not auto-deleted because legitimate repeated purchases exist. |
| Invalid or ambiguous total | Strict positive currency parser; generation remains blocked. |
| Foreign currency | Currency warning requires the user to enter the approved USD reimbursement amount. No exchange rate is invented. |
| Receipt dated after report | Visible review warning. |
| Receipt more than one year old | Visible review warning. |
| Missing job/cost coding | Job, cost type, and cost code stay visible on the affected receipt or mileage row and block generation. |
| Work Order or Other Expenses route reaches the generator | Validation rejects it; columns `L` and `N:Q` remain blank. |
| Leading-zero accounting code | All coding cells use Excel text format. |
| Wrong RRH service-year cost code | One service-year selector updates untouched receipt/mileage defaults from `01AMA` to `02AMA`, `03AMA`, etc.; manual row edits are preserved. |
| Stale job number survives an account change | UI choices reset and generator validation rejects any catalog job outside the selected account. |
| Mileage crosses the July 2026 IRS change | Rate is selected per travel date: `$0.725` through June 30 and `$0.76` beginning July 1. |
| Future IRS rate is unknown | Generation blocks with the exact unconfigured travel date rather than carrying a prior rate forward. |
| More rows than official form | Clear split-report blocker at 15 Miscellaneous or 14 Entertainment; no silent truncation. |
| Total is $20 or less | Generation blocks because the supplied form says the total must exceed $20.00. |
| User switches workflows | Plain session-state mirror preserves typed values and receipt bytes; a Streamlit AppTest covers the rerun. |
| User changes a generated draft | Content signature suppresses stale files/email until regeneration. Receipt bytes are hashed without creating a second full-byte representation. |
| PDF attachment is large | The `.eml` still contains the required PDF and shows a size warning instead of silently substituting Excel. |
| PDF renderer unavailable | Excel remains downloadable, but the approval `.eml` is withheld because the PDF is the submission artifact. |
| Employee edits the optional Excel download | UI directs the employee to export the edited workbook to PDF and replace the draft's attached PDF before sending. |
| Outlook/mobile incompatibility | Windows gets a PDF-attached `.eml`; mobile/web gets the PDF download plus `mailto:` and explicit attachment instructions. |
| Signature confirmed for a different name | Changing the employee name clears confirmation and blocks generation until the new preview is confirmed. |
| Template drift | Anchor cells are verified before any write; a changed template fails closed. |

## Browser and platform behavior

Automated Streamlit coverage verifies the workflow switch, multi-file uploader,
AI-filled editable fields, required default coding, draft preservation across a
hidden-widget rerun, the generation gate, three downloads, and administrator
mailto link.

Expected platform handoff:

| Platform | Receipt input | Approval handoff |
|---|---|---|
| iOS/iPadOS | Photos, Files, screenshots, HEIC, PDF; responsive single-column review | Download PDF, open mailto draft, attach PDF manually; Excel remains optional |
| Windows Chrome | Multi-select or drag receipts into uploader | Download/open `.eml` in Outlook; submission PDF included |
| Windows Edge | Same web controls and downloads as Chrome | Download/open `.eml` in Outlook; submission PDF included |

Physical device acceptance remains required before production promotion,
particularly Outlook's local `.eml` association and the iOS share/download
sequence. The code does not claim that `mailto:` can attach local files.

## Automated verification

Verification for this RRH policy revision:

```text
python -m pytest -q
205 passed

python -m py_compile app/*.py
silent success
```

Coverage includes:

- Exact template packaging
- Field/cell mapping and leading zeros
- Formula preservation and recalculation settings
- Receipt image normalization and ordering
- Two-sheet Excel integrity
- Form-first multi-page PDF rendering
- Strict amount/response parsing
- Job-only allocation and prohibited-column blockers
- Dated IRS mileage rates and mileage-only reports
- Generated signature placement and confirmation reset
- PDF-only Outlook attachment
- Duplicate/date warnings
- Account/browser profile isolation
- Renderer/deployment dependencies
- Full Streamlit expense generation path
- All pre-existing purchase-order regressions

## Remaining RRH coding conflict — product-owner confirmation required

One source conflict remains. The written direction identifies `5490` as
Account / Cost Type and `01AMA` as Cost Code. Dane's PDF visually places
`01AMA` in column `J` and `5490` in column `K`, the reverse of the form headers
and written labels. The implementation currently follows the explicitly labeled
written values while awaiting confirmation.

Resolved decisions:

- Outlook email contains only the submission PDF; Excel is an optional editable
  download.
- Employee Home Business Unit is `RRH`, following the explicit product-owner
  direction even though Dane's reference PDF displays `695`.
- Employee cursive signature and printed name are generated after confirmation.
- Work Order and Other Expenses are never used.
- Mileage uses the official IRS business rate for each travel date.
- Foreign currency is deferred; the operator enters the bank-converted USD
  amount when it rarely occurs.
