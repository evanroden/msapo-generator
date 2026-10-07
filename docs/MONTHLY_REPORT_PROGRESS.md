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

Current implementation branch: `feat/monthly-report-m5`, integrating main
`d385c43510160388a24a6c76f15db04118bdcba9`. Working checkout:
`/workspace/scratch/monthly-report-m5-work`; venv: `/workspace/scratch/monthly-report-venv`.
The separate `/workspace/scratch/monthly-report` checkout holds the released UI
increments. Do not restart from the earlier vanished ca2afe740bcd checkout.

M2 PR #58 merged at `73915b17cd1d3e5dbbe429719121e5a5400d29a8` (738 CI passes).
M3 PR #59 merged at `012d4a85de7a364358ceee9b128a14d95509605c` (758 CI passes).
M4 PR #60 merged at `d649cb8a90dd8382982a6a9c074997b78a152498` (784 CI passes).
PR #62 guided setup merged at `29476cbc5ec0c43f2b01b19492561e44f24b6cfd`
(802 CI passes). The owner then found the raw fragment queue confusing.

PR #63 replaced it with recognizable section expanders. Head
`41ea6ea8e27e185c1acd48f04c42fbad32d13e06` passed Actions `37666102415`
attempt 2 / job `112952646771`: **822 passed, zero skipped**. Attempt 1
timed out downloading LibreOffice before tests; a normal retry passed. GitHub
initially retained the old PR head after update_ref; reopening the existing PR
refreshed it and triggered CI on the correct commit. Merge:
`43269786db1e7f720772e9ea8efc1b2a657da1ec`.
Public browser verified synthetic upload, section cards, site entry, retained
independent table schemas, zero/No values and removal of a pricing column. No
persistent test profile was saved. All eight private DOCX samples were inspected
locally (12–13 grouped cards); three actual-report AppTest walkthroughs opened
every section and verified edit retention. Original private reports stay outside
git/production. Four synthetic DOCX/PDF pages were rendered and visually checked.

Directory PR #64 head `80bf6456162b261d548ec04c4887a3a8c97fc3d9`, tree
`a5312c90f03d4fb813b97fca14ce48a22fa72497`, passed Actions `37666662388` /
job `112947521546`: **835 passed, zero skipped**. Rechecked main and proved
its merged tree equaled the tested tree. Merge:
`99cdd2a688bae623d171bbba53a64ee6e59c8139`.
Public browser verified its optional directory entry, workbook upload screen
and confirmation workflow entry. No real workbook or contacts were uploaded
to production. The actual workbook's 25 tabs/22 detail tabs were read locally.

M5 is an unfinished draft PR #61, published head
`2df5cc47e89f3ff623e09a1d1acdc287062d8142`, verified tree
`bfb9179d5f4b0566719149a95d806a9df76a750a`. Worktree:
`/workspace/scratch/monthly-report-m5-work`. It has strict fact/draft JSON,
evidence citations, caches/bounds, network-only workers, optional OCR, Copilot
prompt/parser and reviewed suggestion UI. A focused 36-test run passed. It is
NOT merged/deployed or complete: finish carry-forward issue/proposal status,
source-review hardening, schema/merge integration and full validation first.
In particular, preserve old AI/manual source links when appending suggestions,
make stale-evidence review refresh explicit, and keep unsupported numbers blocked.

Latest owner feedback is the active priority: replace the one-option report
dropdown with contract cards and site checkboxes; choose a saved design by exact
membership, offer a same-contract design/general ENFRA template/upload when new,
remember optional group names and most recent saved designs, and allow free
navigation. This is implemented locally in the start modules. Final local full
suite: **840 passed, one CI-only skip** with LibreOffice; Ruff F/E9, dependency
consistency and diff checks passed. Two actual private DOCX walkthroughs used
the new contract cards/site selection/upload path, opened all 12/13 sections
and retained edits across closing/reopening. Expected review blockers remain
visible; no private data was uploaded to production. Reused designs
keep schemas/branding but clear other-site contacts, charts/photos and activity.
PR #65 head `106fa8ca36e4fa11cf9d7f8c0308249fc729899a`, tree
`f76c9b8aae5a0c73b71e4c5d3dc0f0a41ea33846`, passed Actions `37672489798`
/ job `112967509794`: **841 passed, zero skipped**. Rechecked main before
merging at `544e7d59b3274f8ffa9defc7b52a932f857c23b6`. Public browser showed
contract cards, the site checklist, month/year, combined-report name and the
template/upload alternatives. Two site selections and the name persisted using
keyboard controls; cloud-browser pointer clicks did not reliably operate the
clipped React Aria checkbox input, so pointer/mobile acceptance is not claimed.
No persistent test profile or private data was saved in production.

The next local increment adds editable org-chart fields/reporting lines, simple
contact fields and live photo-page layouts (one to six photos per page). Preview
images are the same ones embedded in DOCX/PDF. Replacing a supplied chart/contact
image is explicit, cycles and chart prices block output, and contact-row removal
does not resurrect stale widget values. Full local suite: **845 passed, one
CI-only skip**; after an advanced-editor preservation fix, 15 focused tests
passed. A synthetic six-page DOCX/PDF was rendered and visually checked. See
the visual-editing notes. PR #66 head `1be6e9038f5dc6f069829546198b391e16088655`,
tree `f7d9779841677046f972227eec84732de841d94c`, passed Actions `37674412210`
/ job `112974083657`: **847 passed, zero skipped**. Rechecked main before
merge `d385c43510160388a24a6c76f15db04118bdcba9`. Public editor controls have
not yet been exercised on a saved report in production; no persistent synthetic
profile was created for this check.
M6 remains unfinished; full preview PDF and final layout/size/mobile polish remain.

Local M5 hardening commit `73a32d4` preserves manual/old-AI citations, never
marks earlier unreviewed AI text reviewed on append, and exposes applied
paragraphs with editable text and current real fact/page choices. Quote
validation, unsupported numbers, strict JSON field types and conservative
Copilot vendor/meeting classification are covered. After merging the current
UI/model changes, 57 focused AI/UI/visual/site-start/hygiene/docs tests passed.
Carry-forward status/evidence and full M5 validation/release remain. This local
merge checkpoint is not yet the published PR #61 head recorded above.

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
- The owner supplied a private Excel contract/site/leadership/contact directory.
  Inspect it outside git; never publish its names, contacts, original or extracts.
  Add a generic reviewed runtime import, distinguishing index/summary sheets
  from site-detail sheets. Use confirmed site identities as setup suggestions,
  not automatic regional membership or authenticated manager identity. Contacts
  belong in confirmed contact tables, not AI narrative. Preserve source provenance,
  revision guards and restoration. The original workbook remains unchanged.

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
