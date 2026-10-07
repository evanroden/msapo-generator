---
document_type: engineering_handoff
date: 2026-10-07
base_commit: 012d4a85de7a364358ceee9b128a14d95509605c
status: tested_for_publication
---

# Monthly report milestone 4 evidence and CMMS mapping

## Scope and invariants

The monthly workflow needs source documents, editable classification/facts,
selected vendor/water pages and verified CMMS tables. This increment builds on
M3 (PR #59), without changing purchase-order or expense routing. EML/MSG are
read-only inputs; report output remains DOCX/PDF. Nothing is sent or uploaded.

Originals, extracted text and normalized assets are stored only beneath
EPC_DATA_DIR/monthly_reports. Public fixtures are generated synthetically.
No private sample content or extracted image enters git. Source facts, selected
pages and captions are frozen into report snapshots. Changing source facts or
selection invalidates prepared block versions and content-specific warnings.

## Parsing and bounds

Local parsing covers native-text PDFs, images including HEIC, bounded DOCX,
CSV/XLSX, MIME EML and read-only OLE MSG. MSG uses olefile 0.47; no embedded
object, macro, formula, HTML script or external resource executes. XLSX reads
stored formula results; absent cached results remain blank. Unsupported email
attachments and unreadable message objects produce visible notices.

Sources are cached/deduplicated by SHA-256. Limits are 50 files and 180 MB per
report including attachments, 30 MB per file except DOCX's independent 128 MB
bound, 800,000 extracted characters total and 400,000 per document. PDF native
text reads all pages up to a 500-page safety bound, independently of the existing
20-page vision budget. Scan pages are explicitly marked; paid extraction is not
automatic. M5 will prepare bounded vision requests and run network-only jobs.

Thumbnails are on demand, one page at a time. Print page images are normalized
serially and cached; embedding is limited to 150 selected pages / 60 MB of
normalized images. All pages start selected. Operators choose destinations and
captions explicitly. Prepared immutable assets do not alter profile defaults.
Changing selections requires preparing the new version; older versions cannot
silently remain selected behind the edit. DOCX units are logical extracted items,
not invented page numbers. Native vector drawings retain M3's explicit limits.

## CMMS and provenance

Operators map actual date, WO identity, site, description, area, tag, category
and completion-status columns. Date ordering is explicit. Facility aliases use
the confirmed profile, never add new members. An export lacking a facility
column requires explicit assignment. Unknown sites/invalid rows are shown.

The monthly service-call table includes only reporting-month completed rows.
Identical WO duplicates count once; conflicting identities are excluded with a
warning. Twelve months are displayed, but counts remain blank unless the
operator explicitly confirms complete coverage for those months and facilities.
Invalid/conflicting rows invalidate aggregate completeness. Unmapped categories
never become PM/CM counts. Zero is emitted only with explicit complete coverage.
Table schemas and source references remain pinned in the generated snapshot.

## Checkpoint verification and remaining work

Focused backend/editor/library/privacy tests passed (49 tests), including a
26-page native PDF, selected-page caching, genuine synthetic compound MSG,
MIME attachments, DOCX images, CSV/XLSX values, digest/integrity checks,
monthly filtering, explicit historical coverage and snapshot round trips.
Upload/CMMS AppTest lifecycle checks passed. The complete local suite passed
783 tests with one CI-only skip, with real Writer/Calc available. Compileall,
changed-module Ruff F/E9, pip check and diff whitespace passed. A nine-page
synthetic DOCX/PDF was generated and all pages visually reviewed: selected
vendor pages/captions, monthly service rows and blank unknown history are intact.
This is a tested publication checkpoint, not a merge/deployment assertion.
Read MONTHLY_REPORT_PROGRESS.md for exact pushed/merged/deployed state.

No real client-data acceptance test or private Render inspection was performed.
AI extraction/drafting, Copilot, issue-status editing and final layout/preview
polish remain M5–M6. Passcodes remain deferred by the owner.
