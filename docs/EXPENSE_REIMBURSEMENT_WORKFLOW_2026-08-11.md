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
   worksheet.
2. A single `.pdf` packet with the official form first and each receipt page
   afterward.
3. An Outlook `.eml` approval draft with the generated artifacts attached when
   their combined size is email-safe.
4. A `mailto:` fallback for iPhone/iPad, Outlook web, and other mail clients.
   `mailto:` cannot include local attachments, so the UI says exactly which
   generated files must be attached manually.

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

The completed examples were treated as examples, not policy. One example placed
a home address in **Employee Home BU**, which may be incorrect. The workflow
therefore leaves that field required and remembered only after review; it does
not hard-code the address. The help text calls out the uncertainty.

The form itself is the authority for layout, row capacity, formulas, and JDE
column placement. Business-policy values that were not provided—such as a full
expense account/cost-type catalog—were not invented.

## User interaction order

### 1. Upload all receipts

- Upload one image or PDF per receipt.
- Supported: PDF, PNG, JPEG, WebP, TIFF, BMP, HEIC/HEIF/HIF.
- Per-file limit: 15 MB.
- In-progress report upload limit: 60 MB.
- Exact duplicate bytes are ignored and named in a warning.
- Removed/changed receipt sets invalidate generated artifacts.
- Original uploaded bytes remain unchanged.
- A non-widget receipt mirror preserves the in-progress upload set if the user
  briefly switches to the purchase-order workflow.

### 2. Confirm report details and default coding

Required report values:

- Account / contract
- Employee name
- Employee number
- Employee home BU
- Report date
- Contract administrator name and email
- Mail destination; satellite office becomes required when selected

For RRH, the first default administrator is David Siegal at the existing
configured address. A different reviewed administrator replaces the remembered
default for that browser/account.

One default allocation is entered once and applied to all receipts. A receipt
gets its own coding controls only when **Use different coding for this receipt**
is turned on.

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

Entertainment requires a contact name. Miscellaneous is the conservative
default because the supplied completed packet placed ordinary employee travel
meals in Miscellaneous.

### 4. Generate and open the approval draft

Generation is disabled until every active route-specific field is valid. The
page then exposes the Excel, PDF, Outlook draft, and mail-client fallback. Any
edit changes the draft signature and suppresses stale downloads until the user
generates again.

## JDE allocation rules

| Allocation choice | Required UI fields | Cells populated on form rows |
|---|---|---|
| Job expense | Verified job-number option; Account / Cost Type; Cost Code | `I`, `J`, `K` |
| Work-order expense | Service Center; Account / Cost Type; WO Type; Work Order # | `I`, `J`, `K`, `L` |
| Overhead / other | Company #; Department #; OU #; GL Account # | `N`, `O`, `P`, `Q` |

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
| Employee home BU | `K5` |
| Report date | `P5` |
| Mail home selection | `B62` |
| Mail satellite selection | `B64` |
| Satellite office | `F64` |

The tool deliberately leaves the employee and approver signature lines blank.
Typing a name is not treated as certification or a signature.

### Expense rows and totals

- Miscellaneous rows: 24–38, maximum 15 receipts.
- Entertainment rows: 45–58, maximum 14 receipts.
- Miscellaneous total: `H39 = SUM(H24:H38)`.
- Entertainment total: `H59 = SUM(H45:H58)`.
- Total reimbursement: `Q60 = H18+H39+H59`.
- Workbook calculation mode is set to automatic/full recalculation.

The template's mileage rows remain intact and unused. The approved request was
receipt-based; mileage entry was not added because no policy was provided for
when or how this workflow should use that section.

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
contains digits.

## Memory and privacy boundary

After a valid package, SQLite stores only the latest profile for the exact
hashed-browser-token/account pair:

- Employee name and number
- Employee home BU
- Administrator name and email
- Mail destination/satellite office
- Default allocation type and coding fields

It does not persist:

- Receipt bytes or previews
- Merchant
- Transaction date
- Description/business purpose
- Amount or tax
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
| Missing job/cost/WO/overhead code | Only route-relevant fields are shown, but each shown field is required. |
| Leading-zero accounting code | All coding cells use Excel text format. |
| More rows than official form | Clear split-report blocker at 15 Miscellaneous or 14 Entertainment; no silent truncation. |
| Total is $20 or less | Generation blocks because the supplied form says the total must exceed $20.00. |
| User switches workflows | Plain session-state mirror preserves typed values and receipt bytes; a Streamlit AppTest covers the rerun. |
| User changes a generated draft | Content signature suppresses stale files/email until regeneration. Receipt bytes are hashed without creating a second full-byte representation. |
| PDF renderer unavailable | Completed Excel remains downloadable; email draft attaches the workbook. |
| Email attachments too large | If raw Excel+PDF exceeds 18 MB, the `.eml` keeps only the Excel workbook, which already contains all receipts. |
| Outlook/mobile incompatibility | Windows gets an attached `.eml`; mobile/web gets separate downloads plus `mailto:` and explicit attachment instructions. |
| Signature/certification risk | Signature fields remain blank; output and UI state that the employee must complete them. |
| Template drift | Anchor cells are verified before any write; a changed template fails closed. |

## Browser and platform behavior

Automated Streamlit coverage verifies the workflow switch, multi-file uploader,
AI-filled editable fields, required default coding, draft preservation across a
hidden-widget rerun, the generation gate, three downloads, and administrator
mailto link.

Expected platform handoff:

| Platform | Receipt input | Approval handoff |
|---|---|---|
| iOS/iPadOS | Photos, Files, screenshots, HEIC, PDF; responsive single-column review | Download Excel/PDF, open mailto draft, attach manually |
| Windows Chrome | Multi-select or drag receipts into uploader | Download/open `.eml` in Outlook; attachments included |
| Windows Edge | Same web controls and downloads as Chrome | Download/open `.eml` in Outlook; attachments included |

Physical device acceptance remains required before production promotion,
particularly Outlook's local `.eml` association and the iOS share/download
sequence. The code does not claim that `mailto:` can attach local files.

## Automated verification

Feature checkpoint after `2504c23`:

```text
python -m pytest -q
199 passed

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
- Allocation and capacity blockers
- Duplicate/date warnings
- Account/browser profile isolation
- Renderer/deployment dependencies
- Full Streamlit expense generation path
- All pre-existing purchase-order regressions

## Unresolved policy inputs — do not guess

1. Confirm what **Employee Home BU** must contain. The example's home address is
   not treated as authoritative.
2. Confirm whether administrators want both Excel and PDF, Excel only, or PDF
   only. The current email draft includes both when size permits.
3. Confirm whether a typed/digital signature workflow is permitted. The current
   tool leaves signatures blank.
4. Supply the approved expense Account / Cost Type, Cost Code, WO Type, Company,
   Department, OU, and GL catalogs if these should become dropdowns.
5. Confirm whether mileage should be added and which reimbursement-rate policy
   controls it. The form displays `$0.70`; the tool does not assume that rate is
   approved for every report date.
6. Confirm foreign-currency conversion evidence and rounding rules. The current
   tool requires an operator-entered approved USD amount.
