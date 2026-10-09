---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 66f832f3f19f9ae4c67d4c7753a72b09e4b21790
status: integration_validation_in_progress
---

# Focused monthly report editing

The owner asked to continue simplifying the report builder after PR #86. This
increment implements the next set of the thirteen section designs instead of
adding another global checklist.

## Report-writer behavior

- This month's work and Site information each show one remembered section at a
  time. Switching sections keeps unsaved edits and all other section content.
- Cover details and artwork appear once in Report. Change photo, Change logos
  and Edit footer reveal only their controls. Existing logos remain in place.
- Organization shows Team chart, Daytime outage procedure, After-hours outage
  procedure and Facility contacts. Only the selected Change editor opens.
  Complex imported pages, native charts, custom tables and notes are preserved.
- Utility results and capacity share the scorecards workspace. Capacity still
  carries forward and remains part of standing-information confirmation.
- Maintenance, Water, MBCx and Utilities accept files within their section.
  Newly selected files are read once; pages are included or left out, then one
  Add reviewed pages action appends them. No destination selection or separate
  Read / Prepare / Add chain is required for these section-local pages.
- Activity keeps optional batch files and CMMS mapping. Writing help is optional
  and limited to the active section. Linked wording remains reviewable even when
  optional writing tools are hidden.
- Carried issues and proposals appear in their own sections, with compact
  Still open / Still correct / Update actions. Resolution still requires
  evidence; omission is explicit and confirmation remains period-bound.
- Save progress is the save action. An entered editor name and revision-conflict
  checks remain; the redundant save checkbox is removed.
- Review findings open the affected section, or Report when it must be included.

## Picture review and data compatibility

Review is stored per asset, caption, destination and source context. Changing
unrelated text, a table, another picture or photo layout does not invalidate an
unchanged picture. New or changed pictures are the default final-review queue;
already reviewed pictures have optional View or edit controls. Partial approvals
persist across saves and resumes. Removal preserves the original and other
evidence. Integrity-checked shared logos retain their existing approval.

The historical block content digest remains compatible. Exact valid legacy
whole-block approvals migrate on detached working copies; stale approvals do not.
No historical JSON is rewritten. Targeted source-context validation binds source
identity, page text/caption, vendor, site, date and work-order details separately
from whole-source fingerprints. Another page's selection/review does not invalidate
this page. Missing source evidence cannot be approved; export checks independently
validate the current source context.

Section-local uploads share the canonical source cache with batch/CMMS tools.
Switching views cannot replay stale vendor details, captions or page selections.
Additions are append-only and atomic at the draft boundary; existing page identity
prevents duplicate cross-section embedding. Aggregate page/image limits remain.
Prices, unsupported content, stale periods, missing evidence and save conflicts
remain gated. No automatic paid reading or source-generated facts are introduced.

## Validation and remaining work

Focused synthetic tests passed for first reports, section switching, partial edits,
direct save, hidden-source-reading completion, excluded sections, targeted review
links, unchanged picture approvals, changed captions, source provenance, logo
reuse and section-local upload decisions. The stable-tree full local run passed
1199 tests with 8 renderer-dependent skips. The first CI run with real LibreOffice
passed 1206 tests and found one older end-to-end test still expecting the former
always-open Organization editor. That test now follows the explicit Change action
on both the first report and the next month. A passing final CI run is required
before merge. Compilation, changed-file Ruff F/E9, dependency and diff checks
passed. PR #87 records the final CI and deployment outcomes.

This does not complete every proposed section design. Native Word chart-page
preservation beyond Organization, dated work-order/training ledgers, richer
vendor/RFI identity matching, water-visit/open-concern cards and conservative
scorecard table classification remain separate work. Native text/table source
uploads retain the existing editors/CMMS mapper; this local-upload increment
focuses on reviewed image/PDF pages.

No real contacts, private report originals, runtime assets or generated client
files are committed. Production checks remain public-only and create no persistent
synthetic profile or contact directory. Authentication remains as previously
deferred for testing. Rollback is a revert of the feature merge; retain newer
snapshots because older code will not understand individual-picture reviews.
