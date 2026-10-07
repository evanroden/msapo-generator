---
document_type: implementation_notes
date: 2026-10-07
base_commit: ad0a408668270f9f7d71854f73902fb793511e88
workflow: Monthly report
change_type: preview_layout_and_operator_guidance
status: merged_public_ui_verified
---

# Preview and report polish

The owner needs to understand what changes will look like while editing and to
work in any order. This increment adds a full-report preview at every guided
step, alongside the released live org-chart/contact/photo editors. First-time
instructions and an operator guide describe the actual site-first workflow.

Preview uses the same internal Word layout assembler as finished output, with
96-dpi normalized images. LibreOffice converts it, then each page is rasterized
at 96 dpi and watermarked. Bounds are 150 pages, 80 MB converter output and 25 MB
preview output; pages are processed sequentially and asset cache size is bounded.
Preview files are temporary under monthly_reports/previews; converter outputs
are cleaned separately. Preview failure never replaces a draft or finished
package. Content changes mark the cached preview stale and disable its download
until refreshed; its stored month labels the preview filename.

Only explicit unfinished-review checks are relaxed for the watermarked preview.
Prices, template instructions, malformed layout and unapproved source-page
selections remain blocked. The public final assembler always runs strict checks.
The private layout helper is not a finished-output path. Tests cover this boundary,
watermarks, bounds, stale UI state and converter failure. Images that have not yet
been visually confirmed can appear in a draft preview; that does not approve them
for a final client report. OCR is not a guarantee that all prices were found.

Runtime divider artwork fills the whole Letter page behind editable Word headings.
A green title band guarantees contrast, with a lime accent. Images are cropped only
for decorative divider backgrounds. Logos and report content keep their aspect
ratio; header logos now have a width and height bound. The checked-in content-free
shell is unchanged. Stock blue styling is overridden at assembly time. Table
headers repeat across pages, rows stay together, and large tables use a smaller
but readable font. Existing explicit site columns remain intact.

Size estimates include generated chart/photo/divider pages; finished DOCX and PDF
sizes are visible with a warning over the 15 MB target. This is a target rather
than an output-size guarantee. Reducing page selections/densifying photo layouts
is offered, without silently removing evidence or lowering final report quality.

A five-page synthetic report and watermarked preview were rendered with actual
LibreOffice and all pages visually inspected. Tests verify full-page divider
geometry, repeating table headings, retained final rows and deterministic DOCX.
The full local suite passed **871 tests, one CI-only skip** with LibreOffice.
Ruff F/E9, compileall, pip check, hygiene/docs and diff checks passed. Exact-head
CI passed at head `09bb359c2e1de280721f68d0bf3c39e33d3d7883`: Actions
`37679669121` / job `112992084258`, **872 passed, zero skipped**. PR #67 merged
at `d39670b52dc258f47f2f30e33703c794181e5f37` with expected-head protection
after rechecking main. The public app subsequently showed the new first-time
guidance, confirming this UI release reached production. No saved production
report was created or modified for this check.

Public checks never use private Render logs/workspaces. No private sample,
workbook, generated client report or extracted artwork is committed. The actual
private reports were exercised locally in earlier section/editor increments;
owner acceptance of a completed private report remains necessary. Actual phone
and iPad hardware is unavailable; cloud desktop keyboard behavior was verified,
not physical touch behavior. Public saved-report controls have not been exercised
without a persistent profile write. Paid model calls are not part of tests.

PO/expense routing is unchanged. No passcode, demos, EML output or sending is added.
Rollback can revert this increment without changing stored profiles/snapshots;
no storage schema changes are introduced here.
