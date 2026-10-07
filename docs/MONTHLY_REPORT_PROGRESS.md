---
document_type: implementation_checkpoint
started: 2026-10-06
base_commit: 6ffaa1577f491694bd63950acd3a5838600368a2
---

# Monthly report implementation checkpoint

## Read first after any interruption

The owner requested the complete six-milestone Monthly report workflow for
Email Process Control. Each milestone must be independently tested and have its
own PR. This file is the durable restart point. Update it at every checkpoint;
push after coherent changes and approximately every 20–30 minutes of longer
work. Never rely on an ephemeral checkout or conversation summary alone.

Current branch: `feat/monthly-report-m1`.
Current stage: milestone 1 implemented; validation and PR publication in progress.
Next action: finish renderer/UI checks, publish milestone 1, then start library work.

## Owner decisions approved October 6

- Keep supplied logos, divider photos and graphics on the persistent disk.
  Commit only a content-free DOCX shell, code and synthetic fixtures.
- Latest owner direction: defer the passcode requirement while the feature is
  in testing. The owner was reminded that the public app exposes loaded content
  to anyone with its URL. Keep confirmation, typed-editor attribution, audit
  history and reversible library changes. Typed names are not verified identity.
  Revisit reader/editor passcodes before release from testing; do not introduce
  an unapproved login gate in the meantime. Never commit secret values.
- CMMS format is not yet supplied. Implement configurable CSV/XLSX column
  mapping and test synthetic data. Unknown historical counts remain unknown.
- Owner clarification: DOCX and PDF downloads ONLY. No EML or email workflow.
- Owner clarification: individual-facility, multi-site and regional reports are
  equally important from the first release. A contract can have any combination.
  Profiles explicitly store scope type, facility identities/aliases and title;
  never infer scope from a name or the number of facilities. Aliases must not
  create duplicate facilities. Membership is visible/editable and confirmed
  during profile setup/import. No automatic per-facility split is assumed.
- Invalidate review/acknowledgement when the content or its sources change.
- Use revision guards as well as atomic writes; preserve regenerated snapshots.
- Preserve the bounded receipt job runner's network-only worker rule. PDF/image
  preparation remains on the calling thread, incrementally and with caching.
- Deterministic DOCX ZIP metadata and core properties; PDF content/layout tests
  rather than assuming LibreOffice emits deterministic bytes.

## Ground rules

Public git must never contain client documents, real contact details, vendor
reports or photos extracted from the examples. All test names are synthetic;
email addresses use example.invalid. Extend the binary allowlist ONLY for the
content-free shell and verify its ZIP members/metadata contain no private data.

Runtime library is under EPC_DATA_DIR/monthly_reports, using the existing memory
data-directory policy. Use frozen dataclasses and report_-prefixed session state.
Mirror only operator widget values; do not mirror errors, futures, uploads or
generated output. Reuse config.operator_today(browser timezone), api_retry, OCR
budgets, receipt_jobs and pdf_converter. Do not change PO/expense
business rules. In particular preserve the recent expense approval routing.

All document text and Copilot responses are untrusted input. Reuse the receipt
prompt boundary; AI never invents figures or adds personal contacts to narrative.
Every AI paragraph is editable, source-linked and requires review. Evidence is
validated against actual source IDs/pages; old text is carry-forward/style, not
proof of this month's events.

## Milestones and acceptance

1. Skeleton/generation: frozen model; eleven sections plus optional RFI appendix;
   content-free Letter shell; cover/TOC/dividers/stock text; reorder/omit/renumber;
   editable text; placeholders and stale-period preflight; DOCX/PDF downloads;
   retain DOCX on converter failure; synthetic profile only; workflow draft mirror;
   three-option responsive control; model/generator/AppTest/renderer tests.
2. Library/swapping: data-driven profiles with facilities/title/template; versioned
   assets and editable tables; all seven block source choices; explicit org chart
   and other image replacement with one-off/save choices; side-by-side confirmation;
   audit/restore/usage counts; snapshots and last-month carry-forward; confirmed
   editor operations (passcodes deferred during testing). Prepared-by device/profile memory uses guarded
   migration if SQLite changes. Conflicting revisions cannot overwrite silently.
3. DOCX bootstrap: bounded ZIP/XML parsing, inline AND floating drawings, section
   mapping, extracted tables and prior text; mapping confirmation before saving.
   Imports need a separate bound because some example DOCX files exceed 80 MB.
   Use a generated synthetic DOCX in CI; never commit extracted real contents.
4. Uploads: PDF/images/HEIC/DOCX/XLSX/CSV/EML/MSG; digest deduplication; editable
   classification and metadata; date/facility warnings; selectable PDF thumbnails;
   captions; vendor/water pages; CMMS 12-month grids and monthly service rows.
   Preserve long-native-PDF behavior; cap aggregate vision work and byte sizes.
5. AI/Copilot: extraction cache, bounded jobs/progress, one call per draft type,
   strict defensive JSON, source cards, review gate, equipment issues with explicit
   resolved/ongoing/updated status and evidence; never silently remove resolved
   issues. Fully filled stock Copilot prompt and robust eight-section parser.
6. Polish: image normalization and budgets, fast lower-resolution PDF preview,
   mobile/tablet browser checks, full docs, end-to-end tests. Target
   output under 15 MB. Human acceptance uses private real data outside CI.

Required block types: image_page, image_grid (1–6 photos/page), pdf_pages,
rich_text, table (typed columns), stock_text, work_order_grid.
Library sources: Library, Last month, This month, Replace once, Replace and save
to library, Stock text, Omit. Cover/title/month and filename share one period.
The TOC follows actual section order/inclusion; page-number TOC is optional.

## Preflight and generation invariants

Block unresolved required content, unreviewed AI drafts and template instruction
phrases in every text/table/library field. Warnings need a content-specific
acknowledgement: stale dates/month headings, out-of-month documents, included empty
sections and estimated output above 15 MB. Intentional historical references such
as "since July" are exempt only in their local context.

Render DOCX with python-docx, separate chrome-free cover/divider sections and
continuous content-page numbering. Content pages use header branding from library
and a configured address footer. Compress images with EXIF correction, HEIC support,
frame-aware downscaling, line-art preservation; rasterize PDFs with PyMuPDF.
Store a resolved snapshot after generation; keep DOCX even if PDF conversion fails.
Snapshot provenance pins asset versions rather than following future replacements.

## Verification and release log

- Planning: current main inspected; no monthly-report modules yet. Existing runner
  allows two concurrent network jobs and reserves capacity before preparation.
- Open prerequisite: synthetic FacilityOne export. No real data has been
  published or deployed. Passcodes explicitly deferred during testing.
