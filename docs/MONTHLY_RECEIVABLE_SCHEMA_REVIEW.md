# Accounts Receivable source-schema discovery

Refs #494, #458, #493 and #270. Baseline: `a1b2aa61aa92c596d424c95dba29be66135f3441`.

This is a prerequisite for future invoice intake, not an approved AR report,
financial-output exception, or completed import workflow. The owner decision in
#458 is still pending. `inspect_receivable_schema` is an isolated, read-only
diagnostic; no current editor, importer, serializer or renderer invokes it.

## Current capability and the gap

The optional Accounts Receivable section currently offers Facility, Item and
Status plus notes. Starting Report import recognizes native receivable tables,
and existing content-policy code removes monetary columns from ordinary client
output. It does not provide an invoice-specific review contract, establish a
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
| Currency, invoice amount, balance, payment and credit | Original cells remain in diagnostic evidence | Audience, permitted fields, amount semantics and any permitted totals |
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

Before integration, record #458's output audience and field policy, define
invoice identity/correction/conflict rules, and map supported source formats
without losing their native references. Then add explicit editable review,
save/reopen and period behavior, followed by exact-head browser and Section 10
DOCX/PDF acceptance. Existing financial controls must still apply outside any
separately authorized output. None of these downstream obligations is satisfied
by this diagnostic's tests.

## Verification

Synthetic regression cases retain partial payments, credits, conflicting and
repeated rows, missing dates/identities/statuses, ambiguous numeric dates and
unknown columns. They distinguish technical Current/range columns from invoice
aging context, reject unidentified or nonrectangular source tables, and verify
immutable exact-content fingerprints. Adjacent existing content-policy and
Starting Report import tests keep their monetary exclusion requirements.

No genuine source material, production data, shared records or installed masters
are accessed. No existing financial gate or report output is changed.
