---
document_type: implementation_handoff
base_commit: 6ffaa1577f491694bd63950acd3a5838600368a2
date: 2026-10-06
status: milestone_1_synthetic_only
---

# Monthly report: skeleton and generation

## Scope and owner decisions

Adds the third workflow without changing purchase-order or expense business
rules. This first milestone uses explicitly labelled synthetic profiles only.
It is a foundation for the remaining five milestones, not a finished client
report workflow. Individual-facility, multi-site and regional profiles are equal
choices. Facility membership is explicit; aliases never expand membership.

The owner requested DOCX and PDF downloads only. No Monthly report email draft,
email sending or outbound submission path is included or planned. Existing PO
and expense email features are unchanged.

The owner subsequently deferred passcodes during testing. Library writes in M2
will still require confirmation, typed-editor attribution, revision guards,
audit history and restore. The public-access privacy exposure was explained.
No passcode or private library exists in this milestone.

## Model and state

Frozen values describe profiles, facility aliases, periods, sections, block
specifications, resolved blocks and snapshots. The code skeleton contains all
eleven sections plus an optional Appendix G. Ordinary section numbers are
computed from included order; appendix identifiers remain stable. Both cover
and filename use the same ReportPeriod. The previous month uses operator_today
and the browser timezone, including January rollover and leap years.

The M1 demonstration substitutes clearly labelled editable text blocks for
private image/table assets. It also exercises the named utility-analysis,
MBCx and unknown-training-hours stock paragraphs. It does not claim missing
client charts or reports are complete. Image/PDF asset payloads are rejected
by generation until their resolver is present.

Only registered operator fields enter the report_draft_mirror. It is additive
across profiles, and saved before the workflow selector allows Streamlit to
clean hidden widgets. Reordering uses callbacks before rendering the next
frame. Generated files are not widget-mirrored; changing any draft input removes
the old download controls.

AI review is represented now so future integrations cannot bypass the gate:
the reviewed fingerprint binds the text and its source references. Changing
either invalidates review. Warnings have a separate checkbox keyed by the
complete draft fingerprint, so an acknowledgement never follows a changed draft.

## Generation and checks

The content-free shell is created with python-docx: Letter paper, styles,
header/footer and page-number field only. It contains no images, thumbnails,
embedded files or client content. The exact shell path is added to the public
repository binary allowlist; tests inspect its package and recreate it byte
for byte. No other binary exception is added.

Cover, plain-text TOC and divider layouts are assembled from the selected
sections. Content pages have headers and continuous PAGE fields. Cover/divider
sections unlink every header/footer variant and use zero margins. The current
dividers are generated text layouts; private photographic branding arrives
through the library milestone. Brand colour matches the existing app CSS.

Core-property dates and ZIP-entry metadata are fixed, and package member order
is canonical. Equal inputs produce equal DOCX bytes. PDF byte determinism is
not asserted because the converter includes its own metadata.

The same pure pre-flight gate is called by the UI and direct DOCX generation:
required content, source choices, duplicate identities, prepared-by, titles,
unreviewed AI paragraphs and maintained placeholder phrases are blockers.
Every included text block and table cell is scanned. Month names, ISO dates and
US dates outside the reporting period require acknowledgement. Local historical
wording such as 'since July' is exempt; it does not suppress later warnings.
Empty sections and estimated size above 15 MB are warnings. The M1 outline is
explicitly a minimum page count because arbitrary long text can overflow.

PDF conversion reuses pdf_converter.convert_to_pdf. Each run uses a unique
input stem to isolate the converter's shared output directory. Input and output
temporaries are removed. Any conversion failure leaves the finished DOCX
available, shows a recoverable error and permits a retry. No generated artifacts
or synthetic output documents are committed.

## Validation and limitations

- Full local suite with the runtime's Writer/Calc enabled: 703 passed, 1 CI-only
  skip before final documentation; final exact-tree result is recorded in PR.
- 37 new model, preflight, generation and AppTest cases cover scope types,
  section numbering, period/filename agreement, deterministic shell and output,
  placeholder coverage, wrong-year dates, review/acknowledgement invalidation,
  file retention/cleanup and cross-profile/cross-workflow draft persistence.
- Real Writer conversion produced the expected 24-page synthetic report.
  All pages were inspected as rendered contact sheets: no clipping or spurious
  blank pages; content-only header/footer alternation and continuous numbers.
- Existing PO/expense renderer tests also run with the bundled Writer/Calc.
- The selector uses three equal columns on tablets/desktop and full-width rows
  at 540px and below. AppTest/CSS assertions cover the rule; the cloud browser
  refuses localhost, so device-width visual verification remains outstanding.

This milestone does not yet upload, persist snapshots, manage real profiles,
bootstrap reports, extract CMMS data, draft with AI or embed private graphics.
Those are explicitly tracked in MONTHLY_REPORT_PROGRESS.md. Do not advertise
the demonstration as accepted for real data. No database schema, deployed
configuration or main-branch state is changed by this PR.

## Recovery and next checkpoint

Start from the milestone PR branch and read MONTHLY_REPORT_PROGRESS.md. M2 adds
runtime persistence and library swaps on top of these immutable values. Protect
asset resolution against path traversal and pin content hashes in snapshots.
No SQLite migration is needed yet. Reverting M1 has no persistent-data cleanup
requirement because it writes only short-lived conversion files.
