---
document_type: implementation_notes
date: 2026-10-08
base_commit: f685aaa10285bce9587a4998ff0462894c5741ab
status: implementation_awaiting_full_validation
---

# Dedicated report-section design and first implementation

## Correction to the review approach

The owner meant one designer for each report section, exploring the simplest way
to use that particular section. Thirteen separate agents reviewed the cover,
eleven numbered sections and Appendix G. They inspected the current implementation
and retained private layouts; the designs and three first/partial/return acceptance
cases per section are preserved in [section designs](MONTHLY_REPORT_SECTION_DESIGNS.md).
These proposals are not a claim that thirteen new editors have shipped.

## Implemented in this increment

MBCx now has its own status-and-pages editor. The reusable update is a separate
`mbcx_status` block; `mbcx_report` retains monthly attachments. Detached legacy
normalization moves old text with provenance and review requirements, without
changing original snapshots. A genuine next-month start keeps the status and clears
monthly pages; same-month partial content remains intact. Conflicting explicit
omissions are retained for review. New reports do not automatically claim that
commissioning has not started. Sentence starters require an explicit click and are
editable. The interface accurately describes the existing upload path: section-local
PDF ingestion and one-step application are still proposed work.

A capital-specific inspection found a data-loss risk: a merged heading containing
Equipment / End of life / Cost / Description could make the description column look
like a price column. Ambiguous mixed headings now remain intact and block client
output. A targeted heading-correction form shows the data and asks for clear names;
only confirmed price columns are then omitted. Clear existing Cost/Amount columns
continue to be filtered. Editor state is keyed to corrected column schemas so old
widget rows cannot overwrite the corrected table. Original inputs/history remain
unchanged. Synthetic fixtures reproduce this structure without client data.

## Validation state

At this checkpoint focused tests passed. The full suite, publication, exact-head CI
and public deployment check are still pending. Previous docs PR #85 merged at
`f685aaa10285bce9587a4998ff0462894c5741ab` after Actions `37833282220` succeeded.

## Remaining section work

The design document records the remaining cover-first editor, grouped org chart
support, utility workspace, local evidence upload/application, typed vendor/request/
proposal/issue records, historical work-order/training ledgers and no invented
replacement-date precision. Existing directory/sample seeding remains pending.
The next implementation should use these section contracts rather than a generic
block editor with different labels.

Rollback: revert this feature commit; no destructive runtime migration. New snapshots
with mbcx_status require this version for full UI exposure, so preserve them before
rolling application code backward. Old snapshots continue to deserialize unchanged.
