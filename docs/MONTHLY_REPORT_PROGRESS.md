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

Current implementation branch: `feat/monthly-report-sections`, based on main
`29476cbc5ec0c43f2b01b19492561e44f24b6cfd`. Working checkout:
`/workspace/scratch/monthly-report`; venv: `/workspace/scratch/monthly-report-venv`.
The earlier `ca2afe740bcd/monthly-report` checkout did not survive the environment
replacement. Do not restart the milestones from the stale status below.

M2 PR #58 merged at `73915b17cd1d3e5dbbe429719121e5a5400d29a8` (738 CI passes).
M3 PR #59 merged at `012d4a85de7a364358ceee9b128a14d95509605c` (758 CI passes).
M4 PR #60 merged at `d649cb8a90dd8382982a6a9c074997b78a152498`; exact-head Actions
run `37634255896`, job `112836173453`: **784 passed, zero skipped**. The public app
now shows the M4 entry text for monthly uploads/CMMS. No private Render access
or persistent production test content was used.

PR #62 merged at `29476cbc5ec0c43f2b01b19492561e44f24b6cfd`. Final head
`ddbe835226342749b89ec0fa53984fb7ad96a135` passed Actions `37652428282`:
802 tests, zero skipped. Public browser/health verified the upload-first entry,
month/year selectors and removal of demos. The owner then tested it and found
the item queue and empty identity grid confusing. That feedback is a release
blocker for the next increment; do not describe the earlier UI as solved.

Current local increment replaces the fragment queue with recognizable section
expanders, site selection and a visible remaining-steps list. Native pricing is
blocked from client output; pricing columns are removed from imported tables;
vendor page relevance/visual review is required before embedding. All eight
private DOCX samples have been inspected with this grouping (12–13 cards per
report). Three isolated AppTest walkthroughs with actual reports opened every
section and verified edit retention. Their visual previews exposed repeated logos
and tiny icons; the new importer groups identical design artwork and leaves small
icons unchecked with an explicit explanation. A four-page synthetic output was
rendered/visually checked, including price-column removal and zero/false retention.
The complete local suite passed **815 tests with one CI-only skip**. These
changes are NOT yet merged/deployed; exact-head CI and public checks are pending.

M5 draft PR #61 remains a documentation checkpoint, now integrated with main at
head `d9a974e46af6a1dd9d5050bf2d5b537eb749dfa9`. AI/Copilot is NOT implemented.
Directory work is parked on `feat/monthly-report-directory`, published head
`c410035342f1fae1cfde5a316385094ff41d07d8`, tree
`ffb5d03b5fdac3cbe923b080d97d16b2658cc508`. No PR/merge/deployment; its dedicated
tests are unfinished. Resume it after the usability/client-output fix, then M5/M6.

## Additional owner decisions October 7

- Client-facing monthly output must NEVER include prices. This overrides earlier
  cost/amount columns and the earlier Copilot prompt's permission to include
  stated amounts. Retain original evidence privately, but exclude priced pages,
  legal-only boilerplate and blank/signature-only pages from output. Native/OCR
  checks are assistive; visually confirm image pages and invalidate review when
  their content/captions change. Never claim OCR guarantees all prices were found.
- Test the actual supplied reports locally as a novice operator, not only
  synthetic fixtures. After upload, show section expanders with existing content
  and substitution/edit options. Never ask an asset manager to route hundreds of
  internal XML items. Originals remain unchanged; unmatched work stays reviewable.
- Only real saved reports in the UI; synthetic builders remain test fixtures.
- Start with contract and an uploaded preferred report, then confirm explicit
  scope, site identities and aliases. Save logical order/titles/table schemas
  and standing assets; do not require an empty profile to exist first.
- Asset managers need four clear stages: report, monthly work, standing site
  information, review/download. Advanced layout/library controls are secondary.
- Suggest last month on days 1–10, otherwise current month; always offer month
  and year selectors, never a day picker for the reporting period.
- A partial report can have a stale cover, mixed old/new narrative and only a
  few replaced vendor images. NEVER classify the whole upload by its title.
  Inspect item text and embedded images independently. Surface mixed/unknown
  dates. Visual/OCR reading is assistive and bounded, not a deletion decision.
  Keep/reference/exclude decisions require confirmation; preserve original DOCX
  and unmatched content on the runtime disk. Exclude means from this draft,
  not irreversible deletion. A same-month partial import must preserve/append
  current work; a deliberately new month resets monthly attachments/narrative
  while retaining standing information and previous saved versions.

## Owner decisions approved October 6

- Keep supplied logos, divider photos and graphics on the persistent disk.
  Commit only a content-free DOCX shell, code and synthetic fixtures.
- Latest owner direction: defer the passcode requirement while the feature is
  in testing. The owner was reminded that the public app exposes loaded content
  to anyone with its URL. Keep confirmation, typed-editor attribution, audit
  history and reversible library changes. Typed names are not verified identity.
  Revisit reader/editor passcodes before release from testing; do not introduce
  an unapproved login gate in the meantime. Never commit secret values.
- Owner authorized incremental commits, pushes and production deployments so
  they can test as work progresses. Continue to test each coherent increment
  before merging. Each milestone retains its own PR and engineering notes.
- Owner selected PUBLIC CHECKS ONLY for Render verification. Do not select a
  Render workspace or retrieve private deployment logs without new direction.
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

- M4 tested checkpoint: bounded local source parsing/cache, SHA-256 duplicates,
  editable facts/classification, selected/captioned pages, serial image preparation
  and explicit CMMS mapping are implemented. The complete local suite passed
  783 tests with one CI-only skip. New AppTest flows cover upload, page-selection
  invalidation, workflow switching/removal, mapped table use and map invalidation.
  Real LibreOffice produced a nine-page synthetic report; all pages were visually
  inspected. Selected vendor pages/captions, reporting-month service rows and
  blank unsupported historical counts were verified. Compileall, changed-module
  Ruff F/E9, pip check, diff whitespace, docs index and repository hygiene passed.
  Exact-head CI and public deployment remain release gates.

- M3 released: PR #59 merged at 012d4a85de7a364358ceee9b128a14d95509605c.
  Final feature head 0d792ca28ddcc2af5cb460033be476966381f776 passed Actions
  run 37629573026: 758 tests, zero skipped. Public browser verified the updated
  DOCX-import entry point and the 128 MB profile-setup guidance after deployment.
  Full mapping/save lifecycle was verified locally in AppTest; production had no
  saved test profile and no persistent test writes were made. M4 is in progress
  on feat/monthly-report-m4: local source ingestion and explicit CMMS mapping.

- October 7 resume: M2 local/published trees verified equal at
  a7011d91b8f4c269fd01fb57685da9620d8c64c6. Created PR #58 at published head
  237d0316d9df931419a0d8b5df0ea28d51199d5f. Actions run 37625889583 passed
  738 tests, zero skipped. Rechecked unchanged main and merged with expected-head
  protection at 73915b17cd1d3e5dbbe429719121e5a5400d29a8. Public production
  browser verified the library toggle, contract, facility aliases/scope,
  entered-editor confirmation and save controls. No persistent test writes.
- M3 checkpoint: bounded streaming DOCX inspector, one-item mapping/preview UI,
  confirmed batch library save and prior-snapshot import are implemented locally.
  Original package, temporary staging and extracted content stay outside git.
  Eight newly supplied DOCX files parsed within bounds; all eight were rendered
  outside git and representative cover/chart/body/training pages visually reviewed.
  The supplied PDF's structure and representative pages were reviewed too.
  Variations include split headings, floating/text-box drawings, alternate
  fallback duplication, merged cells, native vector charts and extra sections.
  The latter remain unmatched for operator review, not automatic new sections.
  Native Word shapes and unsupported image formats are explicitly flagged for
  replacement by exported images; the source is never executed or fetched.
  Synthetic tests exercise relationship/ZIP/XML safety, table schemas, image
  mapping and atomic guarded saves. The full local suite passed 757 tests with
  one CI-only skip, followed by focused checks after final comparison-UI/docs
  changes. Upload/mapping, confirmations, workflow switching, staged cleanup
  and table-schema restoration pass in AppTest/regressions. A six-page synthetic
  imported report was generated through real LibreOffice and all pages visually
  inspected. Exact-head CI and public deployment verification remain before
  release. See the M3 engineering notes.

- Planning: current main inspected; no monthly-report modules yet. Existing runner
  allows two concurrent network jobs and reserves capacity before preparation.
- Open prerequisite: synthetic FacilityOne export. No real data has been
  published or deployed. Passcodes explicitly deferred during testing.
- Milestone 1: PR #57 merged at bcdf9cc7dc86429c04a2372906bee334025beb78.
  GitHub Actions run 37553785932: 705 passed, zero skipped. Local final tree:
  704 passed, one CI-only skip, with bundled Writer/Calc enabled. Public production
  browser verified the Monthly report tab and both download buttons after
  generating the synthetic report. No private data or paid AI calls used.
- Milestone 2 checkpoint: versioned library backend with atomic/fsynced writes,
  revision guards, confirmation/attribution, asset hash checks, profile/block
  restore, snapshot history and usage counts. Fourteen backend tests passed.
  The library UI, typed tables, cover/logo/divider swaps, section/block ordering,
  image normalization/rendering and device/profile preparer memory are now in
  the worktree. Focused Monthly report suite: 67 passing tests including real
  LibreOffice; final complete run: 736 passed and one CI-only skip. One additional
  AppTest for blank typed editors and workflow cleanup passed independently.
  Five-page image-heavy DOCX/PDF
  rendered and visually inspected; actual page count matched the outline.
  Public-repository hygiene and documentation-index checks passed. Next:
  final regression gates, checkpoint branch, then merge/deploy for owner testing.
