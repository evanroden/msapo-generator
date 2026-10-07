---
document_type: engineering_handoff
base_commit: bcdf9cc7dc86429c04a2372906bee334025beb78
date: 2026-10-07
status: tested_for_publication
---

# Monthly report milestone 2: profile library and report assembly

## Purpose and owner decisions

The first milestone shipped a synthetic report builder. This milestone adds the
runtime profile library so an operator can assemble a real report using their
own site content, edit tables and text, and replace persistent images. Individual,
multi-site and regional profiles have equal support and explicit membership.
Aliases identify an existing facility; they do not add sites to a profile.

The owner authorized tested incremental production deployments. Passcodes are
explicitly deferred while the app is in internal testing. Consequently, library
content is accessible through the public application: a typed editor name is
attribution, not authentication. Shared changes still require confirmation,
revision checks, history and restoration. No email or EML workflow is added.

## Modules and data flow

- `monthly_report_library.py` owns profiles, asset hashes, manifest history,
  snapshots, confirmation and optimistic concurrency.
- `monthly_report_editor.py` provides profile creation/editing, block sources,
  image swaps, typed tables, section/block order, history and generation.
- `monthly_report_model.py` adds layout blocks, used-asset resolution and table
  column specifications. Values remain frozen dataclasses.
- `monthly_report_docx.py` normalizes print images, resolves assets and renders
  cover photos/logos, content-page branding, dividers, image pages and tables.
- `monthly_report_checks.py` gates missing typed content and unconfirmed shared
  replacements, including cover/divider library text and review state.
- `memory.py` remembers a completed report's preparer by hashed device, contract
  and profile. The additive table uses `CREATE TABLE IF NOT EXISTS`; no existing
  expense or PO table is altered or rewritten.

The demonstration remains available without touching site storage. Enable
**Use the profile library** to create a profile or work with saved profiles.
RRH is first through the existing contract catalog, not a duplicated name list.
The month defaults through `operator_today` in the browser timezone.

## Storage and durability

All site content is rooted at `memory._data_dir()/monthly_reports`, which follows
`EPC_DATA_DIR`. No uploaded or generated site data is written into git. Contract
directories combine a readable slug with a hash to prevent punctuation collisions;
profile keys and asset references reject path traversal.

Each profile has a manifest, immutable SHA-256-addressed normalized PNG/JPEG
assets, and numbered manifest history. Snapshots use `YYYY-MM.json` plus numbered
regeneration history. JSON writes use a same-directory temporary file, file
fsync, rename and directory fsync on Linux. A per-profile OS lock serializes
writers, and expected revisions reject stale saves. A failed manifest write
leaves the old head intact; an unreferenced asset can remain safely on disk.

Every shared save records the entered editor, timestamp and old/new content
hashes. Profile definitions and block versions can be restored by creating a new
revision. Restore controls show the content to be restored and require a fresh
confirmation. Asset usage counts count monthly snapshot heads, not each repeated
generation, and exclude omitted content.

One-time replacement assets are persisted for the snapshot without assigning a
current library slot. Starting from the next month's library template therefore
does not adopt them; starting from last month pins them deliberately. Later
library changes cannot alter an existing report snapshot.

## Editing and workflow state

All operator keys use `report_`. Text, choice and order fields use the workflow's
registered draft mirror. Tables retain their resolved data separately from
Streamlit's edit-delta widget state: the seed stays stable during reruns and is
rebuilt from the mirror after widget cleanup. Normalized upload bytes and hashes
are non-widget state, so switching to PO or Expense does not discard an image.

The builder exposes all seven sources: Library, Last month, This month, Replace
once, Replace and save to library, Stock text, and Omit. Saved images can be reused
from another library version. The org chart, workflows, contact matrix, cover,
logos and divider photos share the explicit replacement path. Side-by-side
previews and a content/revision-bound checkbox precede a shared replacement.
Generation stays blocked until that save completes or Replace once is chosen.

Section order, block order, inclusion and titles are stored in snapshots. Last
month restores those choices; profile template defaults apply when the operator
chooses the template. Tables use date, numeric/currency, checkbox or text column
types. Zero and false survive serialization. Facility identity keys remain
stable when display names are edited.

A conflicting snapshot never silently overwrites another report. The operator
compares the saved contents with their draft and explicitly accepts generating
a new version. Finished downloads remain available even if snapshot storage
fails, and the storage error is shown. A PDF conversion failure preserves DOCX;
a cleanup failure cannot discard either finished artifact.

## Images and output

Images share the OCR supported-format and decoded-pixel boundaries, while using
a print-specific encoder. EXIF orientation is applied; HEIC is decoded with
pillow-heif; images are limited to a 200-DPI frame; metadata is removed; alpha is
flattened on white. Line art remains PNG and photographs use JPEG quality 82.
Files above 30 MB and multi-frame images are rejected at this stage.

The shell remains content-free and reproducible. Site logos and photos are loaded
from runtime assets only. Core timestamps and ZIP metadata remain fixed for
deterministic DOCX bytes. PDF bytes are not promised deterministic by LibreOffice.
Used assets drive the size estimate; omitted sections cannot inflate it. The
outline includes dedicated image pages, with long prose/table overflow described
as an estimate. Full-bleed graphic styling and responsive preview polish remain
part of milestone 6.

## Validation at this checkpoint

The focused Monthly report suite passes 67 tests, including real LibreOffice
conversion. Coverage includes atomic write failure, two competing writers,
profile and block restore, hash integrity, schema preservation, snapshot history,
one-time versus shared image use, carry-forward ordering, typed values, HEIC,
EXIF/downscaling, device-memory isolation and additive migration.

AppTest drives actual workflow switching and library controls. Upload widgets are
stubbed only at the byte boundary because AppTest cannot select a native file;
normalization, source resolution, generation and snapshot persistence are real.
The complete suite passed 736 tests with one CI-only skip after the final caption
check. One subsequently added AppTest for blank typed editors/workflow cleanup
also passed independently. Compilation, dependency consistency, Ruff F/E9 and
patch hygiene passed. A synthetic image-heavy report rendered to five pages,
matching the outline; its cover, contents, divider, images and footer were
visually inspected. The PR records exact-head zero-skip CI before production merge.

## Recovery and next milestones

Read `MONTHLY_REPORT_PROGRESS.md` first after interruption. The M2 branch is
`feat/monthly-report-m2`. Keep current library/snapshot directories when rolling
back code. Reverting this increment removes the UI but does not delete disk data
or the additive preparer table. Do not restore a prior disk wholesale to reverse
one content edit; use the version restoration controls.

Milestone 3 adds bounded DOCX bootstrap and mapping. Milestone 4 adds monthly
documents, page selection and CMMS exports. Milestone 5 adds the Copilot round-trip,
cached extraction and reviewed AI drafts. Milestone 6 finishes preview/size/mobile
polish. This checkpoint does not claim any of those paths are enabled.
