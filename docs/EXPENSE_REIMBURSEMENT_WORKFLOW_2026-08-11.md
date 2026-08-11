# Expense reimbursement workflow handoff

**Feature commit:** `9f7b1f9` — `Add employee expense report workflow`
**Documentation commit:** `b057e0b` — `Document expense reimbursement controls`
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
3. A platform-aware approval action addressed to the reviewed administrator.
   Windows defaults to an Outlook `.eml` draft with only the submission PDF
   attached. Outlook on the web gets its own prefilled compose link. iPhone and
   iPad default to a `mailto:` draft in the local default mail app.
4. A collapsed **Other file and email options** area containing the editable
   Excel file, combined PDF, and generic attachment-free email fallback. Web and
   mobile compose URLs cannot include an in-memory local attachment, so those
   routes explicitly direct the employee to add the generated PDF before send.

The tool prepares a draft. It does not email, approve, sign, reimburse, or post
anything to JDE.

## Evidence used and decisions made

The supplied files represented three different stages:

- The three `Employee Reimbursement Expense Report _JDE_10012025*.xlsx` files
  are byte-identical blank templates.
- `2026.03.19 Expense Report 2.xlsx` is a completed workbook example.
- One example is a one-page rendering of a completed form.
- One example is a 16-page packet: the completed form followed by 15 receipt
  pages.
- The approved RRH reference report contains the signed form first, one receipt
  second, job-only coding, and a reimbursement smaller than the receipt total.
- The approved submission artifact is the PDF. Excel remains useful only as an
  editable download and is not attached to the approval email.

The earlier completed examples remain non-authoritative where the approved RRH
report or a later product-owner direction conflicts with them. RRH now
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

For RRH, Employee Home Business Unit is derived from the account as `695`,
matching the approved Dane report. The default administrator name and email
come from private deployment configuration rather than public source. A
different reviewed administrator can still be entered.

RRH service year controls the Account / Cost Type default: `01AMA` for year 1,
`02AMA` for year 2, `03AMA` for year 3, and so on. Cost Code defaults to `5490`.

### 3. Review each receipt

The receipt image and editable fields remain together. The tool attempts to
extract:

- Merchant
- Transaction date
- Final charged amount
- Separately printed tax, for review only
- Currency
- Short receipt-based description
- Individually priced purchased items and extended line amounts
- Miscellaneous versus Entertainment suggestion
- Confidence and ambiguity notes

It does not infer accounting codes, job numbers, attendees, or a business
purpose that the receipt cannot support. If automatic reading fails, blank
required fields stay visible beside the receipt; they are never relabeled as
optional or moved into a hidden panel.

Job number, Account / Cost Type, and Cost Code appear directly under every
receipt. Following the confirmed report, RRH starts with `695400022`, the
service-year `AMA` value in Account / Cost Type, and `5490` in Cost Code. All
three are editable for that receipt; `695400023` is the usual Startup
alternative.

When two or more individually priced purchases are readable, the page shows
each detected item as its own checkbox. All purchased items begin selected.
Unchecking a personal or otherwise nonreimbursable item immediately recalculates
the first reimbursable-amount field. The deterministic calculation allocates the
receipt's final charged total in proportion to selected item prices, so a partial
selection receives a proportional share of receipt-level tax, tip, fees, or
discounts and selecting everything exactly matches the final total. If no final
total was readable, selected item prices are summed directly. The employee can
still override the resulting amount; that override survives ordinary reruns and
is replaced only when the item selection deliberately changes.

When one source receipt also needs several business purposes or coding routes,
the employee can split it into independently editable reimbursement lines. Each
line has its own description, reimbursable amount, section/contact, and JDE
coding. The first line begins with the selected-item aggregate; later lines
deliberately begin blank so a full receipt total cannot be duplicated
accidentally. The employee divides the selected aggregate across those lines.
Nonbusiness items remain unchecked. The workbook attaches the unchanged source
receipt only once and labels how many reimbursement lines it supports. A visible
warning appears when the reviewed line sum exceeds the amount the analyzer read.

Entertainment requires a contact name. Miscellaneous is the conservative
default because the supplied completed packet placed ordinary employee travel
meals in Miscellaneous.

### 4. Add mileage when applicable

Mileage is optional and supports up to eight form rows. Each entry collects:

- Travel date
- Business miles
- Business purpose
- Destination
- Editable job number, Account / Cost Type, and Cost Code

The travel date selects the IRS business rate. The dated table uses `$0.725`
through June 30, 2026 and `$0.76` beginning July 1, 2026, matching the
[initial 2026 IRS rate](https://www.irs.gov/newsroom/irs-sets-2026-business-standard-mileage-rate-at-725-cents-per-mile-up-25-cents)
and the [July 2026 IRS revision](https://www.irs.gov/irb/2026-29_irb).
Unknown future dates block instead of silently reusing an expired rate.

### 5. Confirm signature, generate, and open the approval draft

The page renders the employee name in a cursive signature preview and displays
the printed name beneath it. Generation remains disabled until the employee
confirms that signature and agrees to review it again before sending. The
signature, printed name, and report date are then placed on the form.

The normal path exposes one **Open approval email** action. Browser identity
selects the initial destination: attached-PDF Outlook draft on Windows and the
local default mail app on iPhone/iPad. A visible selector also supports Outlook
on the web. The editable Excel file, submission PDF, and generic
attachment-free fallback stay collapsed under **Other file and email options**.
The `.eml` contains the PDF only. Any edit changes the content fingerprint and
suppresses stale actions and downloads until regeneration.

## JDE allocation rules

The RRH workflow uses one allocation route:

| Required UI field | Form column |
|---|---|
| Job / Service Center | `I` |
| Account / Cost Type | `J` — `01AMA` in service year 1 |
| Cost Code | `K` — `5490` by default |

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
- `I:K`: job, Account / Cost Type, and Cost Code.
- Mileage total: `H18 = SUM(H10:H17)`.

### Expense rows and totals

- Miscellaneous rows: 24–38, maximum 15 reimbursement lines.
- Entertainment rows: 45–58, maximum 14 reimbursement lines.
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
- A receipt PDF may contain up to 10 pages. The first-page preview validates the
  complete source limit without rejecting a valid multipage receipt or rendering
  every page twice.
- Each page gets a header with source-receipt number, date, merchant, total
  reviewed reimbursement across its lines, and source filename.
- Split lines never duplicate the source image; one upload produces one receipt
  attachment group regardless of how many form rows it supports.
- Images are EXIF-rotated, converted to RGB, bounded to 1200×1600, and encoded
  as quality-78 JPEG for legibility and mail size.
- Images and PDF pages over 40 million raster pixels are rejected before a
  large decode/raster allocation or workbook insertion.
- Multi-page attachments receive manual row page breaks and Letter/portrait
  print settings.
- The PDF renderer uses an isolated LibreOffice user profile per generation to
  prevent cross-session profile locks.

If LibreOffice/Gotenberg fails, the official Excel workbook still succeeds and
the page explains that the PDF was unavailable. The approval email is withheld
because the confirmed submission artifact is the PDF; the Excel file remains
available in the collapsed options without crashing or requiring re-entry.

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
line_items: [{description, amount}, ...]
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
contains digits. The approved example reimburses only one business line item
from a larger receipt, so the UI explicitly tells the employee to replace the
prefill with only the business-reimbursable portion when appropriate.

Receipt text is untrusted input. The model prompt explicitly ignores
instructions/code printed inside a receipt. Deterministic normalization removes
obvious summary, discount/coupon, and tender rows from the selectable item list,
caps it at 60, keeps repeated purchased items separate, and adds a review note when detected item
prices differ substantially from the final charged total.

## Memory and privacy boundary

After a valid package, SQLite stores the latest defaults for the exact
hashed-browser-token/account pair:

- Employee name and number
- Administrator name and email
- Mail destination/satellite office

It also stores a separate employee-name/employee-number mapping for that same
browser and account. Entering a previously confirmed employee name recalls that
employee's number even if another employee generated the most recent report.
Matching ignores case and repeated whitespace but does not use fuzzy matching.
Changing to an unknown name clears the prior employee's number instead of
silently carrying it forward. Recalled numbers stay visible and editable, and a
corrected number replaces the old mapping only after a valid report is generated.

Approvers have a separate exact-account directory. The name control performs a
fuzzy type-ahead over people confirmed for the selected account and still
accepts a new name. Selecting a remembered person fills the paired email;
typing an unknown person clears a stale recalled email. A valid generation adds
one idempotent event, so Streamlit reruns do not inflate ranking. Correcting the
person on the same draft moves that event, and correcting the email updates the
stored pair. No approver suggestion crosses an account boundary.

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
| Receipt contains several applicable purposes/codes | Optional split control creates independent reviewed rows while attaching the source once. Later lines start blank. |
| Receipt contains many items but only some are business expenses | AI returns a bounded item list; all detected purchased items begin selected, the employee unchecks nonbusiness items, and the amount recalculates deterministically. The original source stays attached for audit. |
| Item prices omit tax/tip/fees or include a receipt-wide discount | Partial selections receive a proportional share of the final charged total; all-selected remains exactly equal to that total. The amount stays editable. |
| Item OCR is incomplete or wrong | Invalid rows are omitted with a review note; manual description/amount remain editable and the original receipt remains visible. |
| Receipt has more than 60 detected item rows | The selector is capped at 60 with a visible note; the employee uses the reviewed aggregate/manual amount rather than accepting silent truncation. |
| Split line sum exceeds the tool-read receipt total | Prominent review warning identifies both totals; generation still requires valid line-level values because tips, currency conversion, or analyzer error may explain the difference. |
| Image/PDF declares enormous dimensions | Pixel estimate is checked before frame copy or PDF rasterization, preventing a small compressed file from causing an unbounded memory allocation. |
| Receipt PDF exceeds 10 pages | Preflight rejects it before constructing the AI client; the employee gets a split-file instruction instead of an expensive failed request. |
| Invalid or ambiguous total | Strict positive currency parser; generation remains blocked. |
| Foreign currency | Currency warning requires the user to enter the approved USD reimbursement amount. No exchange rate is invented. |
| Receipt dated after report | Visible review warning. |
| Receipt more than one year old | Visible review warning. |
| Missing job/cost coding | Job, Account / Cost Type, and Cost Code stay visible on the affected receipt or mileage row and block generation. |
| Work Order or Other Expenses route reaches the generator | Validation rejects it; columns `L` and `N:Q` remain blank. |
| Leading-zero accounting code | All coding cells use Excel text format. |
| Employee/receipt text begins with an Excel formula character | Every user-editable text and code cell is forced to Excel string type; formulas exist only in the fixed total/mileage cells written by the generator. |
| Wrong RRH service-year Account / Cost Type | One service-year selector updates untouched receipt/mileage defaults from `01AMA` to `02AMA`, `03AMA`, etc.; manual row edits are preserved. |
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
| Wrong email route for the current device | User-agent and client-platform hints default Windows to the attached-PDF Outlook draft and iPhone/iPad—including iPad desktop-site identity—to the local mail app; all routes remain selectable. |
| Browser compose link loses the required attachment | Outlook web and `mailto:` routes state that the PDF must be attached; the combined PDF stays in the collapsed options. No route falsely claims that a URL can attach local bytes. |
| Too many competing completion buttons | The normal path shows one destination selector and one email action. Excel, PDF, and generic attachment-free email controls are collapsed. |
| Approver name selected from history | Exact-account fuzzy suggestions fill the paired email; a new name clears a stale email and remains editable. |
| Same report generated repeatedly | Approver event uses a stable report context and counts once; a correction moves the event instead of duplicating it. |
| Signature confirmed for a different name | Changing the employee name clears confirmation and blocks generation until the new preview is confirmed. |
| Employee name changes after a number was filled | Exact browser/account/name recall supplies the confirmed number; an unknown name clears the stale number. |
| Template drift | Anchor cells are verified before any write; a changed template fails closed. |

## Browser and platform behavior

Automated Streamlit coverage verifies the workflow switch, multi-file uploader,
AI-filled editable fields, required default coding, draft preservation across a
hidden-widget rerun, restored-plus-new receipt merging, individual receipt
removal, split reimbursement lines, the generation gate, collapsed file
options, attached-PDF Outlook draft, Outlook-web compose URL, local-mail URL,
platform defaults, and administrator recall.

Expected platform handoff:

| Platform | Receipt input | Approval handoff |
|---|---|---|
| iOS/iPadOS | Photos, Files, screenshots, HEIC, PDF; responsive single-column review | Defaults to the local mail app; attach the PDF from collapsed options; Excel remains optional |
| Windows Chrome | Multi-select or drag receipts into uploader | Defaults to download/open `.eml` in Outlook with the submission PDF included; Outlook-web route is selectable |
| Windows Edge | Same web controls and downloads as Chrome | Defaults to download/open `.eml` in Outlook with the submission PDF included; Outlook-web route is selectable |

A rendered Chromium 149 acceptance fixture exercised Windows Chrome identity,
Windows Edge identity, and iPad Safari identity against the generated-package
screen. Each profile showed exactly one visible email action, kept all secondary
files/actions inside a closed expander, used the expected platform default,
retained Ocean-Steel-on-Safety-Yellow button contrast, and had no horizontal
overflow. A second rendered 820×1180 touch fixture exercised the itemized
receipt selector: both checkbox rows were 44 pixels high, unchecking a $10 item
from a $33 receipt changed the field to $22, and the explanatory calculation
updated without overflow.

Physical device acceptance remains required before production promotion,
particularly Outlook's local `.eml` association and the iOS download/attach
sequence. The code does not claim that `mailto:` or an Outlook-web compose URL
can attach local files.

## Automated verification

Verification for this RRH policy revision:

```text
python -m pytest -q
272 passed

python -m py_compile app/*.py
silent success
```

Coverage includes:

- Exact template packaging
- Field/cell mapping and leading zeros
- Formula preservation and recalculation settings
- Receipt image normalization and ordering
- Split and partially applicable receipts with one source attachment
- Itemized receipt selection, proportional final-total allocation, manual
  override preservation, summary-row filtering, and long-list bounds
- Restored-plus-new uploader merging and individual receipt removal
- Formula-injection-safe workbook text fields
- Oversized/corrupt image and PDF preflight rejection
- Two-sheet Excel integrity
- Form-first multi-page PDF rendering
- Strict amount/response parsing
- Job-only allocation and prohibited-column blockers
- Dated IRS mileage rates and mileage-only reports
- Generated signature placement and confirmation reset
- PDF-only Outlook attachment
- Duplicate/date warnings
- Account/browser profile isolation
- Employee-number recall plus account-scoped approver type-ahead/email recall
- Renderer/deployment dependencies
- Full Streamlit expense generation path
- Platform-aware Outlook app, Outlook web, and iPhone/iPad mail actions with
  collapsed secondary downloads
- All pre-existing purchase-order regressions

## Confirmed RRH policy decisions

- Outlook email contains only the submission PDF; Excel is an optional editable
  download.
- Employee Home Business Unit is `695`, matching the approved Dane RRH report
  that the product owner identified as authoritative.
- The approved report controls the coding order: `01AMA` is written to
  Account / Cost Type in column `J`, and `5490` is written to Cost Code in
  column `K`.
- Employee cursive signature and printed name are generated after confirmation.
- Work Order and Other Expenses are never used.
- Mileage uses the official IRS business rate for each travel date.
- Foreign currency is deferred; the operator enters the bank-converted USD
  amount when it rarely occurs.
