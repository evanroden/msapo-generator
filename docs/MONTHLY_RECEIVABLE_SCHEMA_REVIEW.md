# Accounts Receivable source-schema discovery

Refs #494, #458, #493 and #270. Original discovery baseline: `a1b2aa61aa92c596d424c95dba29be66135f3441`; integrated with main `9cc96e6265fbf0ce40dbacf8d013cdc6b612e549`.

This is a prerequisite for future invoice intake, not an approved AR report,
a blanket financial-output exception, or a completed import workflow.
**Owner decision recorded in #458 on 28 October 2026:** the tool may show
financial amounts to its user, and monthly client output may contain amounts
verified in the contract or in ENFRA reports intended for clients (such as
MBCx). **Vendor-invoice totals must not appear in monthly client output**;
other vendor financial fields are not implicitly approved. Unknown or mixed
source/audience provenance is not an authorization.

`inspect_receivable_schema` is an isolated, read-only diagnostic, not a
display/export permission check. No current editor, importer, serializer or
renderer invokes it. It preserves source fields as evidence only; it does not
authorize monetary output or change any existing content-policy gate.

## Current capability and the gap

The optional Accounts Receivable section currently offers Facility, Item and
Status plus notes. Starting Report import recognizes native receivable tables,
and current content-policy code conservatively removes monetary columns from
ordinary client output. The newly recorded source-specific allowances in #458
still require separate verified-source implementation and tests; they are
not implemented by this inventory. It does not provide an invoice-specific review contract, establish a
duplicate identity, or calculate authorized AR Aging. A table stripped of its
financial columns is not a complete AR statement.

The new diagnostic inventories an existing `ReportTable` and retains every
source cell, including blank values, repeated rows and unfamiliar headers.
Headings receive conservative candidate roles only when their complete text is
recognized. Multiple columns competing for one role are explicitly listed;
unmapped columns are not discarded. The diagnostic never changes saved reports,
original files, source tables or existing content-policy decisions.

## Candidate fields for the owner review

| Candidate fields | Evidence retained | Decision still required |
| --- | --- | --- |
| Invoice ID, customer account and site | Exact strings and original column positions | Identity scope; handling duplicate IDs across customers/sites and conflicting rows |
| Invoice date and due date | Exact text, including blanks and ambiguous numeric dates | Supported date formats; which date controls aging |
| Status | Exact source text, including partial, credit, paid and closed states | Accepted status mapping and eligibility rules |
| Aging as-of date and days past due | Supplied values only | Explicit as-of date, calendar rules and bucket boundaries |
| Currency, invoice amount, balance, payment and credit | Original cells remain in diagnostic evidence | Verified source/audience and content eligibility; amount semantics; vendor-invoice-total exclusion; any reconciled permitted totals |
| Current and numbered aging buckets | Candidate only with invoice and financial-column context | Whether source buckets are usable and how they reconcile |
| Unknown/custom fields | Original headings and cells remain visible | Explicit mapping or deliberate exclusion |

Missing candidate headings and blank recognized cells remain separate findings.
The diagnostic does not choose a date locale, infer paid status from a zero,
calculate balances from payments, treat negative numbers as approved credits,
remove duplicate rows, convert CCJ identifiers to invoice IDs, sum money or
calculate aging. A field's candidate role is not permission to export it.

## Source identity and integration boundary

The caller must compute the original source's SHA-256 digest from verified
original bytes and supply the exact source-table reference. The diagnostic
validates digest syntax only, not access to or integrity of the original bytes.
Its deterministic fingerprint binds the supplied digest, table reference,
headings and all rows. Data-row references use one-based positions within that
table; they are not claimed PDF pages or workbook row numbers. Original
item/page/workbook provenance must remain attached by a future source adapter.

Before integration, **implement** #458's decided source/audience policy:
verify original source classification and invalidate eligibility when that
source changes; bind each financial field/page to its supported origin and
approved client audience; keep vendor-invoice totals out of monthly output,
including copied/aggregated values in another section. Other vendor amounts
remain unapproved unless independently evidenced. This boundary applies to
narrative text, tables, captions, imported artwork, source pages, previews,
Word and PDF, not just the optional AR section.

Define invoice identity/correction/conflict rules and map supported source
formats without losing their native references. Then add explicit editable
review, save/reopen and period behavior, followed by exact-head browser and
Section 10 DOCX/PDF acceptance. Date/as-of, partial payment, credit, duplicate
and reconciliation decisions remain outstanding; no missing balance or aging
figure may be invented. A status-only extract must not be called complete AR
Aging. The diagnostic's tests do not establish these downstream guarantees.

## Verification

Synthetic regression cases retain partial payments, credits, conflicting and
repeated rows, missing dates/identities/statuses, ambiguous numeric dates and
unknown columns. They distinguish technical Current/range columns from invoice
aging context, reject unidentified or nonrectangular source tables, and verify
immutable exact-content fingerprints. Adjacent existing content-policy and
Starting Report import tests keep their monetary exclusion requirements.

No genuine source material, production data, shared records or installed masters
are accessed. No existing financial gate or report output is changed.


## Reviewed Section 10 intake — scope of the 28 October decision

The owner permits amounts in the **internal application review** for the
source-bound invoice, payment, credit and balance fields. That review does not
grant client-output permission. The Section 10 derivative in this first
integration is explicitly a **nonfinancial open-invoice status and aging-bucket
view**, not a complete monetary AR Aging statement. It displays the original
invoice identity, confirmed report site, invoice/due dates (or a visible
unknown/ambiguous date), normalized status and historical due-date aging as of a human
confirmed date. It does **not** display balances, sums, aged dollar buckets,
payments, credit figures or vendor invoice totals in Word/PDF.

| Field family | Internal review | Monthly client report |
| --- | --- | --- |
| Invoice number, customer account, site, status | Exact original and deliberate corrections | Site, invoice number and status only; customer account remains internal |
| Invoice date, due date, as-of date, calculated aging category | Raw date, explicit as-of and any ambiguous/blank values | Dates or explicit unknown; aging **category**, never inferred monetary aging |
| Original amount, paid amount, credit amount, remaining balance, currency, source monetary bucket columns | Source values visible to the operator and retained in a bounded source receipt, including blanks, signed credits and partial payments | **Not emitted by this intake**, regardless of source category |
| Contract prices/amounts | Internally allowed | Permitted by owner **only when verified in contract** and attached to current field-level source/audience evidence; this intake does not invent that approval |
| ENFRA client-facing report amounts (e.g., MBCx) | Internally allowed | Permitted by owner only through the existing independent verified client-facing financial source/page gate |
| Vendor invoices, unknown/mixed sources | Internally visible for review | **No vendor-invoice totals or unverified amounts**, including aggregates moved into another section |

Rows are read from the existing shared source manager's verified original CSV
or XLSX. The intake re-reads original bytes and compares the exact table and
SHA-256 with the discovered table, preserving its number and each one-based
source-row reference. Manual row corrections are stored separately from every
original cell. A report-scoped fingerprint links the accepted status rows to
the source SHA, original table identity, report sites and reporting month.
Generation rejects stale/removed source/receipt or changed status rows; a
same-named file or identical invoice value is never substituted for another
source/occurrence. Existing generic table/narrative/image financial exclusions
remain authoritative outside this source-bound derivative.

**Historical status and aging rules (old saved reviews):** only explicit ISO YYYY-MM-DD
was interpreted, with no locale inference for dates such as 03/04/2026. A
human-specified aging as-of date and available due date determined Current,
1–30, 31–60, 61–90 or
91+ days past due. Paid/closed invoices are not aged as open receivables;
credits are distinguished, not silently treated as payment. Unknown due dates
remain unknown, not zero. Partial payments retain their status and source
amounts; no missing balance is derived. Where all four amounts are present,
original minus paid minus credit must equal source balance. Contradictory
closed balances, unmatched sites and duplicate (site, account, invoice)
identities require correction before acceptance.

This implementation does not certify a full monetary AR Aging statement.
The independently authorized contract and ENFRA client-report monetary path
must retain its established source/page approvals and cannot be inferred from
a selected category or reused from an invoice receipt. Synthetic unit checks
do not establish true original document or served Word/PDF acceptance.


## Prompt 06 follow-on: invoice-date aging and conservative output (12 November 2026)

New reviews of the shared CSV/XLSX source use **Invoice Date** and the selected
report month's **last calendar day**, not the due date or an arbitrary current
date. Current covers 0–30 days inclusive; then 31–60, 61–90, 91–120, and
121+ days. Future invoices are explicitly not aged; missing or ambiguous invoice
dates have unknown aging. Paid/closed rows and credit memos are not aged as open
receivables. Due dates remain visible for review but do not determine the
aging group. Excel 1900 date-system serials are accepted from XLSX only, with
phantom serial 60 rejected; CSV numeric dates are never locale-guessed. Source
days-past-due, when supplied, are checked separately against due dates.

Existing saved source receipts with no `aging_basis` marker retain the prior
due-date/as-of interpretation. Nothing silently recalculates installed reports.
New receipts bind invoice-date/month-end rules to the report and source and are
recomputed during output preflight. Fully supplied invoice, payment, credit and
balance cells must reconcile; signed credits in the reviewed credit field
reduce the open balance by their magnitude. Missing figures are unresolved, not
zero or an inferred balance. This reconciliation is internal only. Original row
strings and user corrections remain separate; a title/total masquerading as an
invoice is rejected instead of added to the register.

**Output restriction remains in force.** The app's current Section 10 client
Word/PDF/preview contribution is only an explicitly nonfinancial status and
aging-category derivative. Internally reviewed source amounts are **not**
proof of client output eligibility. No 7-column monetary aging or 11-column
financial detail is enabled until field/page-level source, audience, review
invalidation and every output path are independently enforced. Vendor-invoice
totals remain excluded even if copied elsewhere. Existing monetary gates
remain unchanged.

**Open gaps:** explicit per-site field mapping where aliases do not match;
source exports with leading title/total rows that need non-destructive row
selection; invoice-keyed notes carryover with contract/site conflict checks;
partial payment history with only summary balance; currency scope and verified
client amounts. The Tulane three-sheet workbook and Hampton PDF are separate
intake contracts, not established by synthetic UNO-like CSV/XLSX testing.
Physical browser/edit/reload, actual rendered DOCX/PDF and pixel-level
price-leak validation are still required for served acceptance.

**Explicit alias fallback:** a source with nonstandard column labels can map
exact source column indexes to invoice roles during review. Duplicate/unknown
role choices block the entire import; applied mappings are part of the
source-bound review receipt and are checked again against original bytes at
preflight. Standard aliases require no per-report mapping action. This does
not interpret title rows as headers or authorize client monetary output.

**Site attribution:** a missing source Location may default to a single-facility
profile only when that exact saved source's facility identity independently
matches the report facility key/title/alias. An unverified or missing source
facility, a multi-site profile, or a conflicting location rejects. This is not
site verification from filenames.
