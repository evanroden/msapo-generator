---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 59293a785a198ac017f0025b88ce8c5280a1bee4
workflow: Monthly report
status: local_validation_complete_ci_pending
---

# Monthly report resource budget

The owner reported repeated overload on the existing 0.5-CPU / 512 MB testing
instance and requested optimization, not an instance-plan change. Existing report
content, design pins, review gates, source objects and saved history must survive.

## Changes

- A section must be in the browser viewport before its automatic preview is
  scheduled. Unviewed sections do not convert on page open. Committed edits are
  coalesced for 1.5 seconds; obsolete queued work is discarded before assembly.
- A responsive scrolling component reports at most two visible pages. Only those
  pages are rasterized, using bounded 96/120/150-dpi JPEG display copies. Page
  position survives updates. The final report is not rasterized by this change.
- Session state retains opaque preview tickets rather than every PDF and a
  base64 rendering of every page. Across visitors, disposable PDF storage is
  bounded to 64 MB, raster memory to 8 MB, and each raster to 2 MB / 2.5 million
  pixels. Eviction is a cache miss, not a permanent render error. Tickets are
  scoped to their creating browser session, not a typed preparer name.
- One heavy monthly assembly is admitted at a time. Pending foreground exports
  take priority over previews. Background work defers under measured cgroup
  memory pressure. The existing thread/process conversion lock remains separate
  from assembly; nested wrappers for the same backend share the lease.
- Writer and Calc callers now share that converter lease. This includes the
  existing purchase-order and reimbursement backends; their document logic and
  user workflows are unchanged. A second workflow cannot launch a competing
  LibreOffice process while a monthly report converts.
- Each disposable LibreOffice profile uses a 48 MB graphic-cache threshold and
  lossless graphic swapping. Final-export image quality, fonts, crop, colors,
  geometry and PDF options are unchanged. Preview-only embedded rasters can be
  downsized without changing XML geometry or downloadable DOCX image bytes.
- Production numerical-library thread counts are bounded to one and allocator
  arenas to two. The Render plan and persistent-storage configuration are not
  changed. Save progress does not wait for a preview conversion.

## Verification

New regression coverage exercises offscreen scheduling, stale queued work,
cache eviction, ownership, byte/pixel bounds, visible-page reuse, low-memory
admission, foreground priority, nested-lock release and usable DOCX output after
PDF resource failure. A local Chromium DOM run verified visibility transitions,
scrolling from pages 1/2 to 4/5, and at most two requested pages. It is not a full
production browser upload/download test.

Existing preview UI tests now drive the real component's viewport callback
rather than looking for eager PNG iframes. Profile-boundary tests now return a
valid synthetic DOCX from their converter-copy stub because the disposable-image
step actually reads that ZIP; their assertions about profile/cover scope remain.
No rendering/privacy/review test is disabled or weakened.

`scripts/qa_monthly_report_resources.py` exercises a 13 MB synthetic native report
with eight 4,800 x 3,200 source photographs, two preview visitors and a final
export. A separate mandatory CI job runs it in the production image with
`--memory=512m --memory-swap=512m --cpus=0.5`, and verifies no OOM kill. Synthetic
probe output contains measurements only, never customer reports or font files.
The local locked Python 3.12 / Streamlit 1.61.1 full suite passed 1,730 tests,
zero failures or skips. The local CI-presence assertion was enabled explicitly;
this remains a local run, not GitHub Actions. LibreOffice 24.2 is available locally,
but its host lacks the production TeX Gyre font, so local visual checks are not
authentic-reference font-parity acceptance. Exact-head CI, production-font checks
and the 512 MB capped-container result remain required in the PR.

## Limits and rollback

These are bounded-preview/conversion controls, not proof that every combination
of source files or concurrent users fits indefinitely in 512 MB. Original source
inspection and full native assembly can still have substantial transient cost.
Blank-page, cover-placement and reference-PDF defects are separate acceptance
work; passing this resource probe does not close them.

There is no persistent data migration. Old preview caches are disposable and
are dropped. Revert the merge to roll back code; do not roll back or remove
report libraries, contact/capacity records or immutable design versions. Access
remains public testing with editor attribution, not authenticated access.
