---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: e02d9d2a73abadd268199ca3f9d98269398c3950
status: contact_table_pagination_under_validation
---

# Keep current table headings with their rows

## Reproduced problem: usability audit F15 / R13

A synthetic landscape report with a retained tall workflow picture and four
current contact rows reproduced the observed defect through real import mapping,
native generation and LibreOffice: the header printed below the diagram while
all four data rows started on the next page without their column headings.
Source data was synthetic; no directory or customer record was changed.

The native table writer cloned source row formatting but did not establish the
current header's pagination. A source consisting of a header-only table could
also copy its repeat/keep-with-next settings to every new data row. An explicitly
empty current contact table retained an old header when a neighboring unchanged
chart protected the larger source section from reflow.

## Repair and boundaries

Rebuilt tables with explicit current column headings and data now repeat only
their current first row. The header's paragraphs stay together and with the first
data row. Data rows are not chained into one unbreakable table, and an inherited
header flag is removed from data-row clones. The native grid, widths, row-height
values and table styles are unchanged by this helper. Paragraph/row properties
are inserted in OOXML schema order.

An explicitly empty current contact table no longer leaves its old header below
an independently retained chart. Removal is limited to un-emitted contact-table
prototypes without a section boundary; picture tables and other source tables
keep their existing handling. Current extra contact tables are not empty data.

Unchanged, content-proved imported tables bypass the writer and remain byte-for-
byte unchanged in the tested XML. No repeat header is inferred when the caller
has not supplied explicit columns. This does not repair the older source-header
inference or generic/native schema issues, every blank-page case, or complex
multirow/merged-cell schema reconstruction. It does not restyle the report or
change user approval, source/asset retention, privacy or pricing controls.

## Executed evidence

The first 11 new cases on the unchanged release tree had 9 failures and 2 passes.
The later 13-case before run had 10 failures and 3 passes. One new headerless
control was corrected to recognize the existing writer's inferred source header:
its current data starts in row two, not row one. It still asserts that this
unproved header is not promoted into repeating metadata. No pre-existing tests
were modified, disabled or weakened.

The independent before/after generation uses the same immutable synthetic source.
The four-row output remains three pages but now puts the header with all rows on
the third page. The empty-contact output is two pages without an orphan heading;
the 40-row output is six pages with repeated headings on all table pages.
All 40 current identities appear once. The retained diagram's PDF bounds are
identical and its entire crop is pixel-identical at 144 dpi; the divider is
pixel-identical at 72 dpi. Source bytes remain unchanged.

Visual inspection caught an initial seven-page long-table result with just one
row on its first table page, despite passing the initial header-presence checks.
A new rendered-page assertion failed that implementation. Six controlled renders
isolated the issue: keeping the first data row intact prevents the empty split
fragment; header keep-next/keep-lines changes alone did not. The corrected first
table page contains 11 current rows, not one. Subsequent rows remain splittable.

These are local LibreOffice 25.2 comparisons, not Microsoft Word execution or
authentic ENFRA PDF parity. Production LibreOffice 24.2/fonts and final CI must
run the renderer tests as well. Exact final local/CI counts and artifact identities
belong in the PR. Do not add overlapping focused runs to the full-suite total.

## Release and rollback

The combined reliability release PR99 is the baseline; it contains the original
PR96/97/98 history. This is a separate layout change. Public deployment and real
customer/iPad acceptance require independent evidence; this note claims neither.

Code-only revert is sufficient. No new storage schema, design version, saved
report mutation or migration is introduced. Existing historical reports and
original uploads are never rewritten.
