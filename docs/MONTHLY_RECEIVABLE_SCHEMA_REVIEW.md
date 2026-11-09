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
