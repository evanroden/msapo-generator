---
document_type: implementation_checkpoint
base_commit: 59293a785a198ac017f0025b88ce8c5280a1bee4
date: 2026-10-09
status: focused_regressions_passed_pending_full_ci
---

# Replaced monthly-report pages: empty scaffolds and chart sizing

Baseline: `59293a785a198ac017f0025b88ce8c5280a1bee4` (merged PR 91).
This is a focused correction, not completion of the wider fidelity/remediation
handoff. No saved report, contact, asset approval, master version or profile pin
is migrated or overwritten.

## Operator-visible changes

Fresh native-master reports no longer retain old empty content pages simply
because the source report had paragraphs, page breaks, or header-only tables
there. Required section dividers remain. Blank input is not converted into a
claim that work did not occur. Existing verified source-content replay is
protected rather than compacted indiscriminately.

New/replacement organizational charts and technical pages use proportional
contain-fit in the native page's usable area, with header/footer clearance.
They do not inherit an unrelated old photograph's small frame or crop. A wide
chart remains wide, with all edges visible; it is not stretched to fill paper.
Unchanged source pictures keep their original representation and geometry.

A sentence that merely mentions a section name is no longer a section heading.
This removes the obsolete imported-report instruction from the MBCx content
page. Accepted current status text is placed without the old blank paragraph
padding. This does not finish divider typography/header-overlay calibration.

## Implementation and controls

`monthly_report_native_pages.NativePages` binds emitted text, tables and pictures
to the original Word-section geometry. Reflow requires positive replacement
accounting. Source dividers, mixed unproved ranges and independently proved
current source content are protected. Where a discarded range had supplied an
inherited header/footer, that exact effective relationship is restored only
where needed. Redundant terminal section breaks are not emitted as blank pages.

`monthly_report_native_layout` records current insertions and no longer uses a
whole table as a paragraph prototype. Source originals and persistence shapes
are unchanged. Pricing, image approval and final preflight gates are unchanged.
No PDF-page deletion or full-report raster flattening is used.

## Evidence

The synthetic regression file is `tests/test_monthly_report_native_reflow.py`.
Its pre-fix run produced ten failures covering narrative-as-heading, narrow
chart frames, obsolete instructions, empty sections, and rendered page counts.
Positive controls include real headings, compatibility duplicates, appendix
headings, split titles with preceding narrative, retained header inheritance,
and unchanged native-layout tests. Multi-page technical-image tests check actual
PDF page counts, bounds and all four corner markers.

A private diagnostic replay of a second source layout retained all 1,278 body
elements and every DOCX ZIP member unchanged. Two other source replays changed
only the obsolete MBCx instructional paragraph. These are lower-level diagnostic
comparisons, not newly granted picture approvals or final client exports.

Private reproduction used a supplied hospital Word master, not a recreated
screenshot. Under local LibreOffice 24.2, organization changed from 3 to 2 pages,
empty Scorecards from 5 to its single divider, and the newly initialized full
report from 38 to 16 pages while keeping its logical sections and RFI heading.
The MBCx status page no longer contains the old instruction or mid-page padding.
Those counts are fixture-specific, not a target for every report.

The local runtime has the locked Python dependencies and LibreOffice 24.2, but
not the exact production Arial Narrow font file. Local results are not proof of
full authored-PDF typography equivalence. Production-font rendering tests and
the container build/health gate remain mandatory in CI. Exact final test counts
and commit evidence belong in the PR, not inferred from historical test runs.
Private reports, images and detailed measurements remain outside Git/artifacts.

## Scope still open

This does not install the private portfolio capacity dataset into production,
finish native table-schema seeding, persist newly uploaded org charts across a
contract, change site-contact persistence, repair the cover-selection UX,
complete all F1-F8 findings, or guarantee operation within 512 MB. Those items
remain separate work, not implied by passing these regression tests.

Rollback: revert the code change. No data rollback or destructive migration is
required; saved originals, master versions, approvals and snapshots are intact.
